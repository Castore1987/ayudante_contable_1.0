"""Lectura de la historia laboral en PDF descargada de Mi ANSES.

Estrategia en dos pasadas, de la más confiable a la más tolerante:

1. **Tablas**: si el PDF trae tablas reales, se extraen y se reutiliza el mismo
   mapeo de encabezados del importador de planillas.
2. **Líneas**: si el PDF es un volcado de texto sin estructura, se recorre línea
   por línea buscando un período, un CUIT y los importes.

Un PDF escaneado (imagen sin capa de texto) no se puede leer acá: hay que
pasarle OCR antes, o pedir la exportación en planilla.
"""

from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterator

from ..modelo.dominio import (
    EstadoIngreso,
    HistoriaLaboral,
    Periodo,
    RegistroMensual,
    TipoAporte,
)
from .base import ErrorFuente
from .planilla import _mapear_encabezados, _fila_a_registro, parsear_decimal

__all__ = ["leer_pdf_historia_laboral", "ImportadorPDF", "extraer_texto"]

_RE_PERIODO = re.compile(r"\b(?:(0?[1-9]|1[0-2])[/\-](\d{4})|(\d{4})(0[1-9]|1[0-2]))\b")
_RE_CUIT = re.compile(r"\b(\d{2}[-\s]?\d{8}[-\s]?\d)\b")
_RE_IMPORTE = re.compile(r"\b\d{1,3}(?:\.\d{3})*,\d{2}\b|\b\d+\.\d{2}\b|\b\d{4,}\b")
_RE_NO_DIGITOS = re.compile(r"\D")

_MARCAS_IMPAGO = ("sin ingreso", "no ingresad", "impag", "deuda", "adeud", "no registra pago")
_MARCAS_PAGO = ("ingresad", "cancelad", "pago", "abonad")


def extraer_texto(ruta: Path) -> tuple[str, list[list[list[Any]]]]:
    """Devuelve ``(texto_completo, tablas)`` usando pdfplumber o pypdf."""
    try:
        import pdfplumber
    except ImportError:
        return _extraer_con_pypdf(ruta), []

    partes: list[str] = []
    tablas: list[list[list[Any]]] = []
    with pdfplumber.open(str(ruta)) as pdf:
        for pagina in pdf.pages:
            partes.append(pagina.extract_text() or "")
            for tabla in pagina.extract_tables() or []:
                if tabla and len(tabla) > 1:
                    tablas.append(tabla)
    return "\n".join(partes), tablas


def _extraer_con_pypdf(ruta: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise ErrorFuente(
            "Para leer PDF instalá una de estas opciones:\n"
            "    pip install pdfplumber      (recomendada, también lee tablas)\n"
            "    pip install pypdf           (solo texto)\n"
            "Alternativa sin dependencias: exportá la historia laboral a CSV."
        ) from exc

    lector = PdfReader(str(ruta))
    return "\n".join((pagina.extract_text() or "") for pagina in lector.pages)


# ------------------------------------------------------------------- tablas


def _registros_desde_tablas(
    tablas: list[list[list[Any]]], advertencias: list[str]
) -> list[RegistroMensual]:
    registros: list[RegistroMensual] = []
    for tabla in tablas:
        try:
            mapa = _mapear_encabezados(tabla[0])
        except ErrorFuente:
            continue
        for numero, fila in enumerate(tabla[1:], start=2):
            registro = _fila_a_registro(fila, mapa, numero, advertencias)
            if registro is not None:
                registros.append(registro)
    return registros


# -------------------------------------------------------------------- líneas


def _periodo_de_linea(linea: str) -> tuple[Periodo, str] | None:
    coincidencia = _RE_PERIODO.search(linea)
    if not coincidencia:
        return None
    if coincidencia.group(1):
        periodo = Periodo(int(coincidencia.group(2)), int(coincidencia.group(1)))
    else:
        periodo = Periodo(int(coincidencia.group(3)), int(coincidencia.group(4)))
    resto = linea[: coincidencia.start()] + " " + linea[coincidencia.end() :]
    return periodo, resto


def _estado_de_linea(linea: str) -> EstadoIngreso:
    minusculas = linea.lower()
    if any(marca in minusculas for marca in _MARCAS_IMPAGO):
        return EstadoIngreso.NO_INGRESADO
    if any(marca in minusculas for marca in _MARCAS_PAGO):
        return EstadoIngreso.INGRESADO
    return EstadoIngreso.DESCONOCIDO


def _importes_de_linea(resto: str) -> list[Decimal]:
    valores = []
    for texto in _RE_IMPORTE.findall(resto):
        valor = parsear_decimal(texto)
        if valor is not None:
            valores.append(valor)
    return valores


def _nombre_empleador(resto: str) -> str | None:
    """Toma la corrida más larga de palabras alfabéticas como razón social."""
    candidatos = re.findall(r"[A-ZÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÜÑáéíóúüñ&.\-' ]{3,}", resto)
    if not candidatos:
        return None
    mejor = max(candidatos, key=lambda c: len(c.strip()))
    limpio = re.sub(r"\s+", " ", mejor).strip(" .-")
    return limpio or None


def _registros_desde_lineas(texto: str, cuil_titular: str) -> Iterator[RegistroMensual]:
    for linea_cruda in texto.splitlines():
        linea = linea_cruda.strip()
        if len(linea) < 8:
            continue

        analizado = _periodo_de_linea(linea)
        if analizado is None:
            continue
        periodo, resto = analizado

        cuit = None
        coincidencia_cuit = _RE_CUIT.search(resto)
        if coincidencia_cuit:
            candidato = _RE_NO_DIGITOS.sub("", coincidencia_cuit.group(1))
            # El CUIL del titular aparece en el encabezado: no es un empleador.
            if candidato != cuil_titular:
                cuit = candidato
            resto = resto[: coincidencia_cuit.start()] + " " + resto[coincidencia_cuit.end() :]

        importes = _importes_de_linea(resto)
        if not importes and cuit is None:
            continue

        remuneracion = importes[0] if importes else Decimal("0")
        aporte = importes[1] if len(importes) > 1 else None

        yield RegistroMensual(
            periodo=periodo,
            cuit_empleador=cuit,
            empleador=_nombre_empleador(resto),
            tipo=TipoAporte.desde_texto(resto),
            remuneracion_imponible=remuneracion,
            aporte_declarado=aporte,
            estado_ingreso=_estado_de_linea(linea),
        )


# -------------------------------------------------------------------- fachada


def leer_pdf_historia_laboral(
    ruta: str | Path, cuil: str, nombre: str | None = None
) -> HistoriaLaboral:
    """Lee un PDF de historia laboral y lo convierte al modelo interno."""
    from ..modelo.dominio import normalizar_cuil

    ruta = Path(ruta)
    if not ruta.exists():
        raise ErrorFuente(f"No encontré el archivo: {ruta}")

    cuil_normalizado = normalizar_cuil(cuil)
    texto, tablas = extraer_texto(ruta)
    advertencias: list[str] = []

    registros = _registros_desde_tablas(tablas, advertencias)
    metodo = "tablas"

    if not registros:
        registros = list(_registros_desde_lineas(texto, cuil_normalizado))
        metodo = "líneas"
        advertencias.append(
            "El PDF no traía tablas legibles: los períodos se extrajeron por "
            "análisis de texto. Cotejá una muestra contra el original antes de "
            "usar el informe."
        )

    if not registros:
        if not texto.strip():
            raise ErrorFuente(
                f"{ruta.name} no tiene capa de texto (probablemente sea un escaneo). "
                "Pasale OCR o pedí la historia laboral en formato planilla."
            )
        raise ErrorFuente(
            f"No pude reconocer ningún período en {ruta.name}. "
            "Revisá el formato del archivo o importá una planilla CSV."
        )

    return HistoriaLaboral(
        cuil=cuil_normalizado,
        registros=registros,
        nombre=nombre,
        fuente=f"pdf:{ruta.name} ({metodo})",
        advertencias_origen=advertencias,
    )


class ImportadorPDF:
    """Adaptador de :class:`FuenteHistoriaLaboral` sobre un PDF local."""

    nombre = "pdf"

    def __init__(self, ruta: str | Path, nombre_afiliado: str | None = None) -> None:
        self.ruta = Path(ruta)
        self.nombre_afiliado = nombre_afiliado

    def obtener(self, cuil: str) -> HistoriaLaboral:
        return leer_pdf_historia_laboral(self.ruta, cuil, self.nombre_afiliado)
