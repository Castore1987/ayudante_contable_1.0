"""Lector del PDF «Historia Laboral» (HLAB) que emite ANSES.

El HLAB no es una tabla: es un documento por secciones, cada una con su propio
formato. Este módulo las reconoce y las unifica en el modelo interno.

Secciones que se leen:

``RESUMEN HISTORIA LABORAL``
    La línea de servicios según ANSES. Se conserva como referencia para
    contrastarla con la que calcula el sistema.

``APORTES EN RELACIÓN DE DEPENDENCIA ANTERIORES AL 06/94``
    Servicios anuales, con rango de meses y sin remuneración. Se expanden a
    meses de servicio reconocido: no traen sueldo, pero son antigüedad.

``APORTES EN RELACIÓN DE DEPENDENCIA POSTERIORES AL 07/94 (INCLUSIVE)``
    Un renglón por mes. La columna que vale para el control del mínimo es
    **REM IMP. SS**, no REM TOTAL: la primera ya viene topeada por ANSES.

``PADRÓN ÚNICO CONTRIBUYENTE (PUC)`` + ``DETALLE DE PAGOS/TRANSFERENCIA``
    Categorías de autónomo/monotributo con su período de alta, y los pagos
    efectivamente acreditados. Cruzar ambas es lo que permite afirmar que un
    aporte de autónomo ingresó o no.

Un límite del documento que conviene tener presente: **para la relación de
dependencia el HLAB informa la remuneración declarada, no si el aporte
ingresó.** Esos meses quedan con estado de ingreso «sin dato» y así se
informan. Afirmar lo contrario sería inventar.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Iterable

from ..modelo.dominio import (
    EstadoIngreso,
    HistoriaLaboral,
    Periodo,
    RegistroMensual,
    TipoAporte,
    normalizar_cuil,
)
from .base import ErrorFuente

__all__ = [
    "leer_hlab",
    "armar_historia",
    "analizar_lineas",
    "LecturaHLAB",
    "BloquePUC",
    "TramoDeclarado",
    "CategoriaPUC",
    "PagoRegistrado",
    "ImportadorHLAB",
    "es_hlab",
]

CERO = Decimal("0")

_RE_IMPORTE = re.compile(r"\d{1,3}(?:\.\d{3})*,\d{2}")
_RE_PERIODO = re.compile(r"\b(\d{2})/(\d{4})\b")
_RE_CUIT = re.compile(r"\b\d{2}-\d{8}-\d\b")
_RE_FECHA = re.compile(r"\b\d{2}/\d{2}/\d{4}\b")

_RE_CABECERA_CUIL = re.compile(r"CUIT/?L?\s*:?\s*(?:VIGENTE\s*:?\s*)?(\d{2}-\d{8}-\d)")
_RE_CABECERA_NOMBRE = re.compile(r"APELLIDO Y NOMBRE\s*:\s*(.+?)\s*(?:CUIT|ACREDITADO|$)")
_RE_CABECERA_FECHA = re.compile(r"^\d{11}\s+(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2}:\d{2})")

_RE_RESUMEN = re.compile(
    r"^(?P<razon>.+?)\s+(?P<cuenta>\d{2}-\d{8}-\d|\d{6,})\s+"
    r"(?P<desde>\d{2}/\d{4})\s+(?P<hasta>\d{2}/\d{4})\s*$"
)
_RE_DEPENDENCIA = re.compile(
    r"^(?P<razon>.+?)\s+(?P<cuit>\d{2}-\d{8}-\d)\s+(?P<marcas>[A-Z0-9.\s]{0,12}?)\s*"
    r"(?P<periodo>\d{2}/\d{4})\s+(?P<dias>\d{1,3})\s+(?P<horas>\d{1,4})\s+(?P<montos>.+)$"
)
_RE_PRE94 = re.compile(
    r"^(?P<razon>.+?)\s+(?P<cuenta>\d{6,})\s+(?P<anio>\d{4})\s+(?P<caracter>\d{2})\s+"
    r"(?P<d1>\d{2})/(?P<m1>\d{2})\s*-\s*(?P<d2>\d{2})/(?P<m2>\d{2})"
    r"(?:\s+(?P<meses>\d{1,2}))?\s*$"
)
_RE_PUC = re.compile(
    r"^(?P<categoria>[A-Z0-9]{1,6})\s+(?P<desde>\d{2}/\d{4})\s+(?P<hasta>\d{2}/\d{4}|-)\s+"
    r"(?P<impuesto>[A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ ]*?)\s+(?P<estado>[A-Z]{2})\s+"
    r"(?P<f_estado>\d{2}/\d{2}/\d{4})\s+(?P<f_actualizacion>\d{2}/\d{2}/\d{4})\s*$"
)
_RE_PAGO = re.compile(
    r"^(?P<marca>[A-Z])\s+(?P<periodo>\d{2}/\d{4})\s+(?P<concepto>[A-Z0-9]{2,6})\s+"
    r"(?P<importe>[\d.]*\d,\d{2})\s+(?P<deposito>\d{2}/\d{2}/\d{4})\s+"
    r"(?P<acreditacion>\d{2}/\d{2}/\d{4})\s*$"
)

# Secciones del documento, en el orden en que aparecen.
_SECCIONES = (
    ("RESUMEN HISTORIA LABORAL", "resumen"),
    ("RELACIÓN LABORAL", "relacion_laboral"),
    ("ANTERIORES AL 06/94", "pre94"),
    ("POSTERIORES AL 07/94", "post94"),
    ("HISTÓRICO DE AUTÓNOMOS", "autonomos"),
    ("PADRÓN ÚNICO CONTRIBUYENTE", "puc"),
    ("DETALLE DE PAGOS/TRANSFERENCIA", "pagos"),
    ("MONOTRIBUTO SOCIAL", "otros"),
    ("SEGURO DE CAPACITACIÓN", "otros"),
    ("TALLERES PROTEGIDOS", "otros"),
    ("ACOMP. SOCIAL", "otros"),
    ("RECONOCIMIENTO DE SERVICIOS", "otros"),
    ("RECONOCIMIENTOS PROVINCIALES", "otros"),
)

_IMPUESTO_A_TIPO = {
    "AUTONOMO": TipoAporte.AUTONOMO,
    "AUTÓNOMO": TipoAporte.AUTONOMO,
    "MONOTRIBUTO": TipoAporte.MONOTRIBUTO,
    "MONOTRIBUTISTA": TipoAporte.MONOTRIBUTO,
}


def _decimal(texto: str) -> Decimal:
    return Decimal(texto.replace(".", "").replace(",", "."))


def _periodo(texto: str) -> Periodo:
    mes, anio = texto.split("/")
    return Periodo(int(anio), int(mes))


# --------------------------------------------------------------- estructuras


@dataclass(frozen=True)
class TramoDeclarado:
    """Un renglón del RESUMEN: la línea de servicios según ANSES."""

    razon_social: str
    cuenta: str
    desde: Periodo
    hasta: Periodo

    @property
    def meses(self) -> int:
        return self.hasta.ordinal - self.desde.ordinal + 1


@dataclass(frozen=True)
class CategoriaPUC:
    """Alta en el padrón de autónomos o monotributo."""

    categoria: str
    desde: Periodo
    hasta: Periodo | None
    impuesto: str
    estado: str

    @property
    def tipo(self) -> TipoAporte:
        """El padrón usa etiquetas compuestas ('MONOTRIBUTO APORTANTE')."""
        etiqueta = self.impuesto.strip().upper()
        for clave, tipo in _IMPUESTO_A_TIPO.items():
            if etiqueta.startswith(clave):
                return tipo
        return TipoAporte.DESCONOCIDO


@dataclass(frozen=True)
class PagoRegistrado:
    """Un pago acreditado del régimen de autónomos/monotributo."""

    periodo: Periodo
    concepto: str
    importe: Decimal
    deposito: str
    acreditacion: str


@dataclass
class BloquePUC:
    """Un padrón (autónomos o monotributo) junto con SUS pagos.

    El HLAB trae un bloque por régimen. Mezclarlos en una sola bolsa haría que
    un pago de monotributo diera por cancelado un mes de autónomo.
    """

    categorias: list[CategoriaPUC] = field(default_factory=list)
    pagos: list[PagoRegistrado] = field(default_factory=list)

    def pagos_por_periodo(self) -> dict[Periodo, Decimal]:
        totales: dict[Periodo, Decimal] = {}
        for pago in self.pagos:
            totales[pago.periodo] = totales.get(pago.periodo, CERO) + pago.importe
        return totales


@dataclass
class LecturaHLAB:
    """Contenido crudo del documento, antes de armar la historia laboral."""

    cuil: str | None = None
    nombre: str | None = None
    fecha_consulta: str | None = None
    periodo_consulta: Periodo | None = None
    tramos_declarados: list[TramoDeclarado] = field(default_factory=list)
    registros_dependencia: list[RegistroMensual] = field(default_factory=list)
    servicios_pre94: list[RegistroMensual] = field(default_factory=list)
    bloques_puc: list[BloquePUC] = field(default_factory=list)
    advertencias: list[str] = field(default_factory=list)

    @property
    def categorias_puc(self) -> list[CategoriaPUC]:
        return [c for bloque in self.bloques_puc for c in bloque.categorias]

    @property
    def pagos(self) -> list[PagoRegistrado]:
        return [p for bloque in self.bloques_puc for p in bloque.pagos]


# ------------------------------------------------------------------- lectura


def _lineas_del_pdf(ruta: Path) -> list[str]:
    try:
        import pdfplumber
    except ImportError as exc:
        raise ErrorFuente(
            "Leer el HLAB de ANSES necesita pdfplumber:  pip install pdfplumber"
        ) from exc

    lineas: list[str] = []
    with pdfplumber.open(str(ruta)) as pdf:
        for pagina in pdf.pages:
            lineas.extend((pagina.extract_text() or "").splitlines())
    return [l.strip() for l in lineas if l.strip()]


def es_hlab(ruta: str | Path) -> bool:
    """¿El PDF tiene la estructura del HLAB de ANSES?"""
    try:
        lineas = _lineas_del_pdf(Path(ruta))
    except ErrorFuente:
        return False
    cabeza = "\n".join(lineas[:60]).upper()
    return "RESUMEN HISTORIA LABORAL" in cabeza or "HISTORIA LABORAL" in cabeza


def _seccion_de(linea: str) -> str | None:
    mayusculas = linea.upper()
    for marca, seccion in _SECCIONES:
        if marca in mayusculas:
            return seccion
    return None


def _leer_cabecera(linea: str, lectura: LecturaHLAB) -> None:
    if lectura.fecha_consulta is None:
        fecha = _RE_CABECERA_FECHA.match(linea)
        if fecha:
            lectura.fecha_consulta = f"{fecha.group(1)} {fecha.group(2)}"
            dia, mes, anio = fecha.group(1).split("/")
            lectura.periodo_consulta = Periodo(int(anio), int(mes))

    if lectura.nombre is None and "APELLIDO Y NOMBRE" in linea.upper():
        nombre = _RE_CABECERA_NOMBRE.search(linea)
        if nombre:
            lectura.nombre = nombre.group(1).strip(" :,")

    if lectura.cuil is None:
        cuil = _RE_CABECERA_CUIL.search(linea)
        if cuil:
            lectura.cuil = normalizar_cuil(cuil.group(1))


def _fila_dependencia(linea: str, lectura: LecturaHLAB) -> bool:
    coincidencia = _RE_DEPENDENCIA.match(linea)
    if not coincidencia:
        return False

    # Los importes se pegan entre sí cuando son anchos ("2.000.000,002.000.000,00"),
    # así que se extraen por patrón en vez de partir por espacios.
    montos = _RE_IMPORTE.findall(coincidencia.group("montos"))
    if len(montos) < 2:
        lectura.advertencias.append(
            f"Renglón de dependencia con importes ilegibles, se omitió: {linea[:70]}…"
        )
        return True

    remuneracion_total = _decimal(montos[0])
    remuneracion_imponible = _decimal(montos[1])
    sac = _decimal(montos[3]) if len(montos) > 3 else None

    observaciones = [f"rem. total {remuneracion_total}"]
    if sac:
        observaciones.append(f"SAC {sac}")

    lectura.registros_dependencia.append(
        RegistroMensual(
            periodo=_periodo(coincidencia.group("periodo")),
            cuit_empleador=re.sub(r"\D", "", coincidencia.group("cuit")),
            empleador=coincidencia.group("razon").strip(),
            tipo=TipoAporte.RELACION_DEPENDENCIA,
            remuneracion_imponible=remuneracion_imponible,
            # El HLAB informa la remuneración declarada; no dice si el aporte
            # ingresó. Se deja explícitamente sin dato.
            estado_ingreso=EstadoIngreso.DESCONOCIDO,
            observaciones="; ".join(observaciones),
        )
    )
    return True


def _fila_pre94(linea: str, lectura: LecturaHLAB) -> bool:
    coincidencia = _RE_PRE94.match(linea)
    if not coincidencia:
        return False

    anio = int(coincidencia.group("anio"))
    mes_desde = int(coincidencia.group("m1"))
    mes_hasta = int(coincidencia.group("m2"))

    if not (1 <= mes_desde <= 12 and 1 <= mes_hasta <= 12) or mes_hasta < mes_desde:
        # "00/00 - 00/00" es un renglón sin servicios: no se inventa antigüedad.
        return True

    for periodo in Periodo.rango(Periodo(anio, mes_desde), Periodo(anio, mes_hasta)):
        lectura.servicios_pre94.append(
            RegistroMensual(
                periodo=periodo,
                cuit_empleador=coincidencia.group("cuenta"),
                empleador=coincidencia.group("razon").strip(),
                tipo=TipoAporte.RELACION_DEPENDENCIA,
                remuneracion_imponible=CERO,
                servicio_reconocido=True,
                estado_ingreso=EstadoIngreso.DESCONOCIDO,
                observaciones="servicio anterior a 06/94, sin dato de remuneración",
            )
        )
    return True


def _fila_puc(linea: str, lectura: LecturaHLAB) -> bool:
    coincidencia = _RE_PUC.match(linea)
    if not coincidencia:
        return False
    hasta = coincidencia.group("hasta")
    lectura.bloques_puc[-1].categorias.append(
        CategoriaPUC(
            categoria=coincidencia.group("categoria"),
            desde=_periodo(coincidencia.group("desde")),
            hasta=_periodo(hasta) if hasta != "-" else None,
            impuesto=coincidencia.group("impuesto").strip(),
            estado=coincidencia.group("estado"),
        )
    )
    return True


def _fila_pago(linea: str, lectura: LecturaHLAB) -> bool:
    coincidencia = _RE_PAGO.match(linea)
    if not coincidencia:
        return False
    lectura.bloques_puc[-1].pagos.append(
        PagoRegistrado(
            periodo=_periodo(coincidencia.group("periodo")),
            concepto=coincidencia.group("concepto"),
            importe=_decimal(coincidencia.group("importe")),
            deposito=coincidencia.group("deposito"),
            acreditacion=coincidencia.group("acreditacion"),
        )
    )
    return True


def _fila_resumen(linea: str, lectura: LecturaHLAB) -> bool:
    coincidencia = _RE_RESUMEN.match(linea)
    if not coincidencia:
        return False
    lectura.tramos_declarados.append(
        TramoDeclarado(
            razon_social=coincidencia.group("razon").strip(),
            cuenta=coincidencia.group("cuenta"),
            desde=_periodo(coincidencia.group("desde")),
            hasta=_periodo(coincidencia.group("hasta")),
        )
    )
    return True


def analizar_lineas(lineas: Iterable[str]) -> LecturaHLAB:
    """Recorre el documento por secciones y extrae cada formato."""
    lectura = LecturaHLAB()
    seccion: str | None = None

    for linea in lineas:
        _leer_cabecera(linea, lectura)

        nueva = _seccion_de(linea)
        if nueva is not None:
            seccion = nueva
            # Cada padrón abre un bloque nuevo; los pagos que siguen son suyos.
            if nueva == "puc":
                lectura.bloques_puc.append(BloquePUC())
            continue

        if seccion == "resumen":
            _fila_resumen(linea, lectura)
        elif seccion == "pre94":
            _fila_pre94(linea, lectura)
        elif seccion == "post94":
            _fila_dependencia(linea, lectura)
        elif seccion == "puc":
            _fila_puc(linea, lectura)
        elif seccion == "pagos":
            _fila_pago(linea, lectura)

    return lectura


# ------------------------------------------------ autónomos: alta contra pago


def _registros_autonomos(lectura: LecturaHLAB) -> list[RegistroMensual]:
    """Cruza el alta en el padrón con los pagos acreditados, mes por mes.

    Es el único punto del HLAB donde se puede afirmar que un aporte ingresó:
    hay fecha de depósito y de acreditación. El cruce se hace dentro de cada
    bloque, para no dar por pagado un mes de autónomo con un pago de
    monotributo.
    """
    registros: list[RegistroMensual] = []

    for bloque in lectura.bloques_puc:
        pagos_por_periodo = bloque.pagos_por_periodo()
        # Un padrón sin ningún pago listado NO prueba que el afiliado no pagó:
        # prueba que el HLAB no informa esos pagos. Afirmar deuda con esto
        # sería inventar un reclamo.
        informa_pagos = bool(bloque.pagos)
        tope = lectura.periodo_consulta or (
            max(pagos_por_periodo) if pagos_por_periodo else None
        )

        cubiertos: set[Periodo] = set()
        for categoria in bloque.categorias:
            if categoria.tipo == TipoAporte.DESCONOCIDO:
                continue
            hasta = categoria.hasta or tope
            if hasta is None or hasta < categoria.desde:
                lectura.advertencias.append(
                    f"Categoría {categoria.categoria} ({categoria.impuesto}) desde "
                    f"{categoria.desde} sin período de cierre determinable; se omitió."
                )
                continue

            for periodo in Periodo.rango(categoria.desde, hasta):
                ingresado = pagos_por_periodo.get(periodo)
                cubiertos.add(periodo)
                registros.append(
                    RegistroMensual(
                        periodo=periodo,
                        cuit_empleador=None,
                        empleador=f"{categoria.impuesto.title()} (cat. {categoria.categoria})",
                        tipo=categoria.tipo,
                        remuneracion_imponible=CERO,
                        aporte_ingresado=ingresado,
                        servicio_reconocido=True,
                        estado_ingreso=_estado_del_mes(ingresado, informa_pagos),
                        observaciones=(
                            f"alta en padrón {categoria.desde}"
                            + (f" a {categoria.hasta}" if categoria.hasta else " (vigente)")
                        ),
                    )
                )

        # El padrón no siempre cubre todos los pagos: hay aportes acreditados de
        # períodos sin alta registrada (habitual en los años noventa). Son meses
        # aportados igual, y omitirlos le borraría antigüedad al afiliado.
        etiqueta = _etiqueta_del_bloque(bloque)
        for periodo in sorted(set(pagos_por_periodo) - cubiertos):
            registros.append(
                RegistroMensual(
                    periodo=periodo,
                    cuit_empleador=None,
                    empleador=f"{etiqueta} sin alta en padrón",
                    tipo=_tipo_del_bloque(bloque),
                    remuneracion_imponible=CERO,
                    aporte_ingresado=pagos_por_periodo[periodo],
                    servicio_reconocido=True,
                    estado_ingreso=EstadoIngreso.INGRESADO,
                    observaciones="pago acreditado sin categoría vigente en el padrón",
                )
            )

    return registros


def _estado_del_mes(ingresado: Decimal | None, informa_pagos: bool) -> EstadoIngreso:
    if ingresado and ingresado > CERO:
        return EstadoIngreso.INGRESADO
    return EstadoIngreso.NO_INGRESADO if informa_pagos else EstadoIngreso.DESCONOCIDO


def _tipo_del_bloque(bloque: BloquePUC) -> TipoAporte:
    for categoria in bloque.categorias:
        if categoria.tipo != TipoAporte.DESCONOCIDO:
            return categoria.tipo
    return TipoAporte.AUTONOMO


def _etiqueta_del_bloque(bloque: BloquePUC) -> str:
    return _tipo_del_bloque(bloque).etiqueta


# ------------------------------------------------------------------- fachada


def armar_historia(
    lectura: LecturaHLAB,
    cuil: str | None = None,
    nombre: str | None = None,
    fuente: str = "hlab-anses",
) -> HistoriaLaboral:
    """Convierte una lectura del documento en una historia laboral del modelo."""
    cuil_final = normalizar_cuil(cuil) if cuil else lectura.cuil
    if cuil_final is None:
        raise ErrorFuente("No pude determinar el CUIL del documento. Pasalo con --cuil.")
    if cuil and lectura.cuil and normalizar_cuil(cuil) != lectura.cuil:
        raise ErrorFuente(
            "El CUIL indicado no coincide con el del documento. Verificá que el "
            "archivo corresponda al cliente que estás analizando."
        )

    registros = (
        lectura.servicios_pre94
        + lectura.registros_dependencia
        + _registros_autonomos(lectura)
    )
    if not registros:
        raise ErrorFuente(
            "No reconocí ningún período en el documento. ¿Es un HLAB de ANSES? "
            "Si el formato cambió, revisá las expresiones de hlab_anses.py."
        )

    advertencias = list(lectura.advertencias)
    for bloque in lectura.bloques_puc:
        if bloque.categorias and not bloque.pagos:
            advertencias.append(
                f"El padrón de {_etiqueta_del_bloque(bloque).lower()} llegó sin detalle "
                "de pagos: esos meses quedan con ingreso «sin dato». No se puede "
                "afirmar deuda sobre ellos con este documento."
            )
    if lectura.registros_dependencia:
        advertencias.append(
            "Relación de dependencia: el HLAB informa la remuneración declarada, "
            "no si el aporte ingresó. Esos meses quedan con ingreso «sin dato»; "
            "para confirmarlos hace falta la constancia de pago del empleador."
        )

    historia = HistoriaLaboral(
        cuil=cuil_final,
        registros=registros,
        nombre=nombre or lectura.nombre,
        fecha_consulta=lectura.fecha_consulta,
        fuente=fuente,
        advertencias_origen=advertencias,
        tramos_declarados=lectura.tramos_declarados,
    )
    historia.lectura = lectura
    return historia


def leer_hlab(
    ruta: str | Path, cuil: str | None = None, nombre: str | None = None
) -> HistoriaLaboral:
    """Lee un PDF de Historia Laboral de ANSES y lo convierte al modelo interno."""
    ruta = Path(ruta)
    if not ruta.exists():
        raise ErrorFuente(f"No encontré el archivo: {ruta}")

    lineas = _lineas_del_pdf(ruta)
    if not lineas:
        raise ErrorFuente(
            f"{ruta.name} no tiene capa de texto (probablemente sea un escaneo). "
            "Pedí el HLAB en PDF nativo o pasale OCR."
        )

    return armar_historia(
        analizar_lineas(lineas), cuil, nombre, fuente=f"hlab-anses:{ruta.name}"
    )


class ImportadorHLAB:
    """Adaptador de :class:`FuenteHistoriaLaboral` sobre un HLAB en PDF."""

    nombre = "hlab-anses"

    def __init__(self, ruta: str | Path, nombre_afiliado: str | None = None) -> None:
        self.ruta = Path(ruta)
        self.nombre_afiliado = nombre_afiliado

    def obtener(self, cuil: str) -> HistoriaLaboral:
        return leer_hlab(self.ruta, cuil, self.nombre_afiliado)
