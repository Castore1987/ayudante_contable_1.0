"""Procesamiento por lote: muchos clientes en una pasada.

Pensado para el trabajo repetitivo del estudio. Dos garantías que definen el
diseño:

* **Un cliente que falla no voltea el lote.** Cada expediente se procesa
  aislado; los errores se juntan y se informan al final, no cortan la corrida.
* **Nada queda en silencio.** El resumen distingue los que salieron limpios, los
  que tienen hallazgos y los que directamente no se pudieron procesar. Un
  expediente que falló nunca se cuenta como "en orden".
"""

from __future__ import annotations

import csv
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator

from .analisis.parametros import ParametrosPrevisionales
from .analisis.validador import Informe, analizar
from .fuentes.base import ErrorFuente
from .modelo.dominio import formatear_cuil, normalizar_cuil
from .seguridad.auditoria import RegistroAuditoria

__all__ = [
    "ClienteLote",
    "ResultadoCliente",
    "ResumenLote",
    "leer_padron",
    "procesar_lote",
    "ErrorLote",
]


class ErrorLote(Exception):
    """El lote no se pudo armar (padrón ilegible, vacío o mal formado)."""


_ALIAS_PADRON = {
    "cuil": ("cuil", "cuit", "documento", "cuil cliente"),
    "nombre": ("nombre", "apellido y nombre", "afiliado", "cliente", "razon social"),
    "archivo": ("archivo", "planilla", "historia laboral", "ruta", "path", "historia"),
    "nota": ("nota", "notas", "observaciones", "obs", "comentario"),
}

_TILDES = str.maketrans("áéíóúÁÉÍÓÚüÜñÑ", "aeiouAEIOUuUnN")


def _clave(texto: str) -> str:
    limpio = re.sub(r"[^a-z0-9]+", " ", str(texto or "").translate(_TILDES).lower())
    return re.sub(r"\s+", " ", limpio).strip()


@dataclass(frozen=True)
class ClienteLote:
    """Una fila del padrón: a quién procesar y con qué archivo."""

    cuil: str
    nombre: str | None = None
    archivo: Path | None = None
    nota: str = ""

    @property
    def cuil_legible(self) -> str:
        return formatear_cuil(self.cuil)

    @property
    def etiqueta(self) -> str:
        return f"{self.cuil_legible}" + (f" — {self.nombre}" if self.nombre else "")


@dataclass
class ResultadoCliente:
    """Qué pasó con un expediente del lote."""

    cliente: ClienteLote
    informe: Informe | None = None
    error: str | None = None
    archivos: list[Path] = field(default_factory=list)
    segundos: float = 0.0

    @property
    def fallo(self) -> bool:
        return self.informe is None

    @property
    def con_errores(self) -> bool:
        return self.informe is not None and bool(self.informe.errores)

    @property
    def limpio(self) -> bool:
        return self.informe is not None and not self.informe.errores

    @property
    def estado(self) -> str:
        if self.fallo:
            return "no procesado"
        return "con errores" if self.con_errores else "en orden"


@dataclass
class ResumenLote:
    """Resultado consolidado de la corrida."""

    resultados: list[ResultadoCliente] = field(default_factory=list)
    parametros_origen: str = ""
    segundos: float = 0.0

    def __len__(self) -> int:
        return len(self.resultados)

    @property
    def fallidos(self) -> list[ResultadoCliente]:
        return [r for r in self.resultados if r.fallo]

    @property
    def con_errores(self) -> list[ResultadoCliente]:
        return [r for r in self.resultados if r.con_errores]

    @property
    def limpios(self) -> list[ResultadoCliente]:
        return [r for r in self.resultados if r.limpio]

    @property
    def requiere_atencion(self) -> bool:
        """Hay algo que mirar: expedientes con errores o que no se procesaron."""
        return bool(self.con_errores or self.fallidos)

    @property
    def conteo(self) -> dict[str, int]:
        return {
            "total": len(self.resultados),
            "en_orden": len(self.limpios),
            "con_errores": len(self.con_errores),
            "no_procesados": len(self.fallidos),
        }

    def hallazgos_frecuentes(self, tope: int = 8) -> list[tuple[str, int]]:
        """Códigos de hallazgo más repetidos en todo el lote."""
        conteo: dict[str, int] = {}
        for resultado in self.resultados:
            if resultado.informe is None:
                continue
            for codigo in {h.codigo for h in resultado.informe.hallazgos}:
                conteo[codigo] = conteo.get(codigo, 0) + 1
        return sorted(conteo.items(), key=lambda par: (-par[1], par[0]))[:tope]


# ----------------------------------------------------------------- el padrón


def leer_padron(ruta: str | Path) -> list[ClienteLote]:
    """Lee el listado de clientes a procesar.

    Formato mínimo: una columna con el CUIL. Opcionales: ``nombre``, ``archivo``
    (ruta a la historia laboral, relativa al padrón) y ``nota``.
    """
    ruta = Path(ruta)
    if not ruta.exists():
        raise ErrorLote(f"No encontré el padrón: {ruta}")

    for codificacion in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            contenido = ruta.read_text(encoding=codificacion)
            break
        except UnicodeDecodeError:
            continue

    muestra = contenido[:2048]
    delimitador = ";" if muestra.count(";") >= muestra.count(",") else ","
    filas = [f for f in csv.reader(contenido.splitlines(), delimiter=delimitador) if any(f)]
    if not filas:
        raise ErrorLote(f"El padrón {ruta.name} está vacío.")

    encabezados = [_clave(c) for c in filas[0]]
    mapa: dict[str, int] = {}
    for campo, alias in _ALIAS_PADRON.items():
        for indice, encabezado in enumerate(encabezados):
            if encabezado in alias and indice not in mapa.values():
                mapa[campo] = indice
                break

    if "cuil" not in mapa:
        raise ErrorLote(
            f"El padrón {ruta.name} no tiene una columna de CUIL reconocible. "
            f"Encabezados leídos: {filas[0]}"
        )

    def celda(fila: list[str], campo: str) -> str | None:
        indice = mapa.get(campo)
        if indice is None or indice >= len(fila):
            return None
        return (fila[indice] or "").strip() or None

    clientes: list[ClienteLote] = []
    vistos: set[str] = set()
    for numero, fila in enumerate(filas[1:], start=2):
        crudo = celda(fila, "cuil")
        if not crudo:
            continue
        try:
            cuil = normalizar_cuil(crudo)
        except ValueError as exc:
            raise ErrorLote(f"Padrón, fila {numero}: {exc}") from exc
        if cuil in vistos:
            raise ErrorLote(
                f"Padrón, fila {numero}: {formatear_cuil(cuil)} aparece más de una vez."
            )
        vistos.add(cuil)

        archivo = celda(fila, "archivo")
        clientes.append(
            ClienteLote(
                cuil=cuil,
                nombre=celda(fila, "nombre"),
                archivo=(ruta.parent / archivo).resolve() if archivo else None,
                nota=celda(fila, "nota") or "",
            )
        )

    if not clientes:
        raise ErrorLote(f"El padrón {ruta.name} no tiene ninguna fila con CUIL.")
    return clientes


# ------------------------------------------------------------- procesamiento


def _historia_desde_archivo(cliente: ClienteLote):
    from .fuentes.pdf_anses import leer_pdf_historia_laboral
    from .fuentes.planilla import leer_planilla

    if cliente.archivo is None:
        raise ErrorFuente(
            "El padrón no indica archivo para este cliente y el lote corre en "
            "modo local. Agregá la columna 'archivo' o usá el modo portal."
        )
    if cliente.archivo.suffix.lower() == ".pdf":
        return leer_pdf_historia_laboral(cliente.archivo, cliente.cuil, cliente.nombre)
    return leer_planilla(cliente.archivo, cliente.cuil, cliente.nombre)


def procesar_lote(
    clientes: list[ClienteLote],
    parametros: ParametrosPrevisionales,
    obtener_historia: Callable[[ClienteLote], object] | None = None,
    al_terminar_cliente: Callable[[ResultadoCliente], None] | None = None,
    exportar: Callable[[Informe, ClienteLote], list[Path]] | None = None,
    auditoria: RegistroAuditoria | None = None,
    pausa_segundos: float = 0.0,
) -> ResumenLote:
    """Procesa el lote completo, aislando la falla de cada expediente.

    ``obtener_historia`` permite cambiar el origen (archivo local, portal, o un
    doble en las pruebas) sin tocar la orquestación.
    """
    obtener_historia = obtener_historia or _historia_desde_archivo
    resumen = ResumenLote(parametros_origen=parametros.origen)
    comienzo_lote = time.monotonic()

    for indice, cliente in enumerate(clientes):
        comienzo = time.monotonic()
        resultado = ResultadoCliente(cliente=cliente)

        try:
            historia = obtener_historia(cliente)
            resultado.informe = analizar(historia, parametros)
            if exportar is not None:
                resultado.archivos = exportar(resultado.informe, cliente)
        except Exception as exc:  # el lote no se corta por un expediente
            from .seguridad.redaccion import redactar

            resultado.error = redactar(exc)

        resultado.segundos = time.monotonic() - comienzo
        resumen.resultados.append(resultado)

        if auditoria is not None:
            auditoria.registrar(
                "lote.cliente",
                cliente.cuil,
                resultado="error" if resultado.fallo else "ok",
                estado=resultado.estado,
                detalle=resultado.error or "",
            )
        if al_terminar_cliente is not None:
            al_terminar_cliente(resultado)

        # Espaciar los accesos cuando el origen es un servicio externo.
        if pausa_segundos and indice < len(clientes) - 1:
            time.sleep(pausa_segundos)

    resumen.segundos = time.monotonic() - comienzo_lote
    return resumen
