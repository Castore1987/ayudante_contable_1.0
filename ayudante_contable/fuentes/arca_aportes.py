"""Lector del export «Aportes en Línea» de ARCA (relación de dependencia).

El archivo llega con extensión ``.xls`` pero **es HTML**: una tabla exportada
desde el sitio. Se parsea como HTML, sin depender de librerías de Excel.

Es la pieza que cierra el hueco del HLAB. Donde el HLAB solo informa la
remuneración declarada, este export trae dos columnas por mes:

* ``Declarado`` — lo que el empleador declaró en la DDJJ.
* ``Depositado`` — lo que **efectivamente ingresó**.

Comparar ambas es el control de aportes realizados en relación de dependencia,
y es lo que permite pasar de «sin dato» a confirmado o reclamable.

El propio archivo aclara su alcance: "Esta planilla muestra sus datos en
relación de dependencia […] para autónomo/monotributo/casas particulares
oprimir Ver pagos SICAM". Autónomos y monotributo se leen con ``sicam.py``.
"""

from __future__ import annotations

import html as html_lib
import re
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Sequence

from ..modelo.dominio import (
    EstadoIngreso,
    HistoriaLaboral,
    Periodo,
    RegistroMensual,
    TipoAporte,
    normalizar_cuil,
)
from .base import ErrorFuente
from .planilla import parsear_decimal

__all__ = ["leer_aportes_arca", "LecturaARCA", "ImportadorARCA", "es_aportes_arca"]

CERO = Decimal("0")

_RE_FILA = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
_RE_CELDA = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S | re.I)
_RE_TAG = re.compile(r"<[^>]+>")
_RE_ESPACIOS = re.compile(r"\s+")
_RE_NO_DIGITOS = re.compile(r"\D")
_RE_PERIODO = re.compile(r"^\s*(\d{4})(\d{2})\s*$")

_TILDES = str.maketrans("áéíóúÁÉÍÓÚüÜñÑ", "aeiouAEIOUuUnN")


def _texto(bruto: str) -> str:
    return _RE_ESPACIOS.sub(" ", html_lib.unescape(_RE_TAG.sub(" ", bruto))).strip()


def _celdas(fila: str) -> list[str]:
    return [_texto(c) for c in _RE_CELDA.findall(fila)]


def _clave(texto: str) -> str:
    return _RE_ESPACIOS.sub(" ", texto.translate(_TILDES).lower()).strip()


@dataclass
class LecturaARCA:
    """Contenido del export, antes de armarlo como historia laboral."""

    cuil: str | None = None
    nombre: str | None = None
    registros: list[RegistroMensual] = field(default_factory=list)
    advertencias: list[str] = field(default_factory=list)
    # Aportes de obra social, por si el estudio los necesita aparte.
    obra_social: dict[Periodo, tuple[Decimal | None, Decimal | None]] = field(
        default_factory=dict
    )


def _leer_cabecera(celdas: Sequence[str], lectura: LecturaARCA) -> bool:
    """Detecta la fila ``CUIL | nnn | Apellido y nombre | XXX``."""
    if len(celdas) < 2 or _clave(celdas[0]) != "cuil":
        return False
    try:
        lectura.cuil = normalizar_cuil(celdas[1])
    except ValueError:
        return False
    if len(celdas) >= 4 and _clave(celdas[2]).startswith("apellido"):
        lectura.nombre = celdas[3] or None
    return True


def _mapear_columnas(celdas: Sequence[str]) -> dict[str, int] | None:
    """Ubica las columnas de la fila de encabezados.

    La cabecera es de dos niveles: una fila agrupa "Aportes de seguridad
    social" / "Aportes de obra social" y la siguiente repite Declarado /
    Depositado bajo cada grupo. Por eso los pares se toman por orden de
    aparición: el primero es seguridad social, el segundo obra social.
    """
    claves = [_clave(c) for c in celdas]
    if "periodo" not in claves:
        return None

    mapa: dict[str, int] = {"periodo": claves.index("periodo")}
    for nombre, alias in (
        ("cuit", ("cuit",)),
        ("razon_social", ("razon social",)),
        ("remuneracion", ("remun. total bruta", "remun total bruta", "remuneracion")),
    ):
        for indice, clave in enumerate(claves):
            if any(clave.startswith(a) for a in alias):
                mapa[nombre] = indice
                break

    declarados = [i for i, c in enumerate(claves) if c.startswith("declarado")]
    depositados = [i for i, c in enumerate(claves) if c.startswith("depositado")]
    if not declarados or not depositados:
        return None

    mapa["declarado_ss"] = declarados[0]
    mapa["depositado_ss"] = depositados[0]
    if len(declarados) > 1:
        mapa["declarado_os"] = declarados[1]
    if len(depositados) > 1:
        mapa["depositado_os"] = depositados[1]
    return mapa


def _valor(celdas: Sequence[str], mapa: dict[str, int], campo: str) -> str | None:
    indice = mapa.get(campo)
    if indice is None or indice >= len(celdas):
        return None
    return celdas[indice] or None


def _estado(declarado: Decimal | None, depositado: Decimal | None, tolerancia: Decimal) -> EstadoIngreso:
    """Resuelve el ingreso comparando lo declarado con lo depositado."""
    if declarado is None and depositado is None:
        return EstadoIngreso.DESCONOCIDO
    if depositado is None:
        return EstadoIngreso.DESCONOCIDO
    if depositado <= CERO:
        return EstadoIngreso.NO_INGRESADO if (declarado or CERO) > CERO else EstadoIngreso.DESCONOCIDO
    if declarado is None or declarado <= CERO:
        return EstadoIngreso.INGRESADO
    # Un depósito apenas menor al declarado son centavos de redondeo, no deuda.
    if depositado < declarado * (Decimal("1") - tolerancia):
        return EstadoIngreso.PARCIAL
    return EstadoIngreso.INGRESADO


def _fila_a_registro(
    celdas: Sequence[str], mapa: dict[str, int], lectura: LecturaARCA, tolerancia: Decimal
) -> RegistroMensual | None:
    crudo = _valor(celdas, mapa, "periodo")
    if not crudo:
        return None
    coincidencia = _RE_PERIODO.match(crudo)
    if not coincidencia:
        return None
    periodo = Periodo(int(coincidencia.group(1)), int(coincidencia.group(2)))

    declarado = parsear_decimal(_valor(celdas, mapa, "declarado_ss"))
    depositado = parsear_decimal(_valor(celdas, mapa, "depositado_ss"))
    remuneracion = parsear_decimal(_valor(celdas, mapa, "remuneracion")) or CERO

    cuit = _valor(celdas, mapa, "cuit")
    if cuit:
        cuit = _RE_NO_DIGITOS.sub("", cuit) or None

    lectura.obra_social[periodo] = (
        parsear_decimal(_valor(celdas, mapa, "declarado_os")),
        parsear_decimal(_valor(celdas, mapa, "depositado_os")),
    )

    observaciones = ["ARCA Aportes en Línea"]
    if declarado is not None and depositado is not None:
        diferencia = declarado - depositado
        if diferencia > CERO:
            observaciones.append(f"falta depositar {diferencia}")

    return RegistroMensual(
        periodo=periodo,
        cuit_empleador=cuit,
        empleador=_valor(celdas, mapa, "razon_social"),
        tipo=TipoAporte.RELACION_DEPENDENCIA,
        # ARCA informa la remuneración TOTAL BRUTA, sin topear. El control del
        # mínimo se hace sobre la imponible del HLAB; acá se guarda como dato.
        remuneracion_imponible=remuneracion,
        aporte_declarado=declarado,
        aporte_ingresado=depositado,
        estado_ingreso=_estado(declarado, depositado, tolerancia),
        observaciones="; ".join(observaciones),
    )


def es_aportes_arca(ruta: str | Path) -> bool:
    """¿El archivo es el export «Aportes en Línea» de ARCA?"""
    try:
        cabeza = Path(ruta).read_text(encoding="utf-8", errors="replace")[:4000]
    except OSError:
        return False
    minusculas = cabeza.lower()
    return "aportes en linea" in minusculas or "aportes en línea" in minusculas


def leer_aportes_arca(
    ruta: str | Path,
    cuil: str | None = None,
    nombre: str | None = None,
    tolerancia: Decimal = Decimal("0.02"),
) -> HistoriaLaboral:
    """Lee el export de ARCA y devuelve la historia laboral con pagos reales."""
    ruta = Path(ruta)
    if not ruta.exists():
        raise ErrorFuente(f"No encontré el archivo: {ruta}")

    for codificacion in ("utf-8", "latin-1"):
        try:
            contenido = ruta.read_text(encoding=codificacion)
            break
        except UnicodeDecodeError:
            continue

    filas = [_celdas(f) for f in _RE_FILA.findall(contenido)]
    if not filas:
        raise ErrorFuente(
            f"{ruta.name} no tiene filas de tabla. El export de ARCA llega con "
            "extensión .xls pero es HTML; si te dieron un .xlsx real, convertilo "
            "a CSV y usá --planilla."
        )

    lectura = LecturaARCA()
    mapa: dict[str, int] | None = None

    for celdas in filas:
        if not celdas:
            continue
        if mapa is None:
            if _leer_cabecera(celdas, lectura):
                continue
            mapa = _mapear_columnas(celdas)
            continue
        registro = _fila_a_registro(celdas, mapa, lectura, tolerancia)
        if registro is not None:
            lectura.registros.append(registro)

    if mapa is None:
        raise ErrorFuente(
            f"No encontré la fila de encabezados en {ruta.name}. Se esperaban las "
            "columnas Periodo, Declarado y Depositado."
        )
    if not lectura.registros:
        raise ErrorFuente(f"No pude extraer ningún período de {ruta.name}.")

    cuil_final = normalizar_cuil(cuil) if cuil else lectura.cuil
    if cuil_final is None:
        raise ErrorFuente(f"No pude determinar el CUIL en {ruta.name}. Pasalo con --cuil.")
    if cuil and lectura.cuil and normalizar_cuil(cuil) != lectura.cuil:
        raise ErrorFuente(
            "El CUIL indicado no coincide con el del export de ARCA. Verificá que "
            "el archivo corresponda al cliente que estás analizando."
        )

    advertencias = list(lectura.advertencias)
    advertencias.append(
        "ARCA «Aportes en Línea» cubre únicamente relación de dependencia. "
        "Autónomos y monotributo se leen desde SICAM."
    )

    historia = HistoriaLaboral(
        cuil=cuil_final,
        registros=lectura.registros,
        nombre=nombre or lectura.nombre,
        fuente=f"arca-aportes:{ruta.name}",
        advertencias_origen=advertencias,
    )
    historia.lectura_arca = lectura
    return historia


class ImportadorARCA:
    """Adaptador de :class:`FuenteHistoriaLaboral` sobre el export de ARCA."""

    nombre = "arca-aportes"

    def __init__(self, ruta: str | Path, nombre_afiliado: str | None = None) -> None:
        self.ruta = Path(ruta)
        self.nombre_afiliado = nombre_afiliado

    def obtener(self, cuil: str) -> HistoriaLaboral:
        return leer_aportes_arca(self.ruta, cuil, self.nombre_afiliado)
