"""Armado de la línea de servicios a partir de la historia laboral.

Produce dos vistas que el estudio necesita para distinta cosa:

* **Tramos por empleador**: cada relación laboral con su fecha de inicio y fin,
  que es lo que se vuelca en el formulario de servicios.
* **Línea consolidada**: los meses de calendario con servicio, fusionando
  empleos simultáneos, para contar antigüedad sin computar dos veces el mismo
  mes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from ..modelo.dominio import HistoriaLaboral, Periodo, TipoAporte, TramoServicio
from .evaluacion import EvaluacionRegistro, evaluar_historia
from .parametros import ParametrosPrevisionales

__all__ = [
    "IntervaloConsolidado",
    "LineaServicios",
    "construir_linea_servicios",
]

CERO = Decimal("0")


@dataclass(frozen=True)
class IntervaloConsolidado:
    """Meses corridos con servicio, sin distinguir empleador."""

    inicio: Periodo
    fin: Periodo
    empleadores: tuple[str, ...]

    @property
    def meses(self) -> int:
        return self.fin.ordinal - self.inicio.ordinal + 1

    def __str__(self) -> str:
        return f"{self.inicio} a {self.fin}"


@dataclass
class LineaServicios:
    """Resultado del armado: tramos, consolidado, lagunas y totales."""

    cuil: str
    tramos: list[TramoServicio] = field(default_factory=list)
    consolidado: list[IntervaloConsolidado] = field(default_factory=list)
    lagunas: list[IntervaloConsolidado] = field(default_factory=list)
    meses_computables: int = 0
    meses_con_reservas: int = 0
    meses_descartados: int = 0
    primer_periodo: Periodo | None = None
    ultimo_periodo: Periodo | None = None

    @property
    def anios_computables(self) -> Decimal:
        return (Decimal(self.meses_computables) / Decimal(12)).quantize(Decimal("0.01"))

    @property
    def antiguedad_texto(self) -> str:
        anios, meses = divmod(self.meses_computables, 12)
        return f"{anios} año(s) y {meses} mes(es)"

    @property
    def meses_laguna(self) -> int:
        return sum(l.meses for l in self.lagunas)


def _cortar_en_tramos(
    evaluaciones: list[EvaluacionRegistro], interrupcion_tolerada: int
) -> list[list[EvaluacionRegistro]]:
    """Parte una serie de meses en bloques continuos.

    Un hueco de hasta ``interrupcion_tolerada`` meses no corta el tramo: sirve
    para empleadores que no declaran un mes puntual sin que haya baja.
    """
    if not evaluaciones:
        return []

    bloques: list[list[EvaluacionRegistro]] = [[evaluaciones[0]]]
    for anterior, actual in zip(evaluaciones, evaluaciones[1:]):
        hueco = actual.periodo.ordinal - anterior.periodo.ordinal - 1
        if hueco > interrupcion_tolerada:
            bloques.append([actual])
        else:
            bloques[-1].append(actual)
    return bloques


def _tramo_desde_bloque(bloque: list[EvaluacionRegistro]) -> TramoServicio:
    primero = bloque[0].registro
    periodos = {e.periodo for e in bloque}
    return TramoServicio(
        empleador=primero.nombre_visible,
        cuit_empleador=primero.cuit_empleador,
        tipo=primero.tipo if primero.tipo != TipoAporte.DESCONOCIDO else _tipo_dominante(bloque),
        inicio=min(periodos),
        fin=max(periodos),
        meses_declarados=len(periodos),
        meses_con_remuneracion=len({e.periodo for e in bloque if e.registro.tiene_remuneracion}),
        meses_sin_aporte_ingresado=len({e.periodo for e in bloque if e.no_ingresado}),
        meses_bajo_minimo=len({e.periodo for e in bloque if e.bajo_minimo}),
        remuneracion_total=sum(
            (e.registro.remuneracion_imponible for e in bloque), start=CERO
        ),
    )


def _tipo_dominante(bloque: list[EvaluacionRegistro]) -> TipoAporte:
    conteo: dict[TipoAporte, int] = {}
    for evaluacion in bloque:
        tipo = evaluacion.registro.tipo
        if tipo != TipoAporte.DESCONOCIDO:
            conteo[tipo] = conteo.get(tipo, 0) + 1
    if not conteo:
        return TipoAporte.DESCONOCIDO
    return max(conteo.items(), key=lambda par: par[1])[0]


def _consolidar(
    meses: dict[Periodo, set[str]], interrupcion_tolerada: int
) -> list[IntervaloConsolidado]:
    """Fusiona meses sueltos en intervalos corridos."""
    if not meses:
        return []

    ordenados = sorted(meses)
    intervalos: list[IntervaloConsolidado] = []
    inicio = anterior = ordenados[0]
    empleadores: set[str] = set(meses[inicio])

    for periodo in ordenados[1:]:
        if periodo.ordinal - anterior.ordinal - 1 > interrupcion_tolerada:
            intervalos.append(
                IntervaloConsolidado(inicio, anterior, tuple(sorted(empleadores)))
            )
            inicio = periodo
            empleadores = set()
        empleadores |= meses[periodo]
        anterior = periodo

    intervalos.append(IntervaloConsolidado(inicio, anterior, tuple(sorted(empleadores))))
    return intervalos


def _detectar_lagunas(
    meses_con_servicio: set[Periodo],
    desde: Periodo,
    hasta: Periodo,
    minimo_informable: int,
) -> list[IntervaloConsolidado]:
    """Meses sin servicio entre el primer y el último aporte del afiliado."""
    lagunas: list[IntervaloConsolidado] = []
    inicio: Periodo | None = None
    anterior: Periodo | None = None

    for periodo in Periodo.rango(desde, hasta):
        if periodo in meses_con_servicio:
            if inicio is not None and anterior is not None:
                lagunas.append(IntervaloConsolidado(inicio, anterior, ()))
                inicio = None
            continue
        if inicio is None:
            inicio = periodo
        anterior = periodo

    if inicio is not None and anterior is not None:
        lagunas.append(IntervaloConsolidado(inicio, anterior, ()))

    return [l for l in lagunas if l.meses >= minimo_informable]


def construir_linea_servicios(
    historia: HistoriaLaboral,
    parametros: ParametrosPrevisionales,
    evaluaciones: list[EvaluacionRegistro] | None = None,
) -> LineaServicios:
    """Arma la línea de servicios completa con fechas de inicio y fin."""
    evaluaciones = evaluaciones if evaluaciones is not None else evaluar_historia(
        historia, parametros
    )
    tolerancia = parametros.tolerancias.meses_interrupcion_tolerada

    # --- tramos por empleador ------------------------------------------------
    por_empleador: dict[str, list[EvaluacionRegistro]] = {}
    for evaluacion in evaluaciones:
        por_empleador.setdefault(evaluacion.registro.clave_empleador, []).append(evaluacion)

    tramos: list[TramoServicio] = []
    for grupo in por_empleador.values():
        grupo.sort(key=lambda e: e.periodo.ordinal)
        for bloque in _cortar_en_tramos(grupo, tolerancia):
            tramos.append(_tramo_desde_bloque(bloque))
    tramos.sort(key=lambda t: (t.inicio.ordinal, t.fin.ordinal, t.empleador))

    # --- consolidado por mes de calendario -----------------------------------
    meses_computables: dict[Periodo, set[str]] = {}
    meses_con_reservas: set[Periodo] = set()
    meses_descartados: set[Periodo] = set()

    for evaluacion in evaluaciones:
        periodo = evaluacion.periodo
        if evaluacion.computa_servicio:
            meses_computables.setdefault(periodo, set()).add(
                evaluacion.registro.nombre_visible
            )
            if evaluacion.computa_con_reservas:
                meses_con_reservas.add(periodo)
        elif evaluacion.registro.tiene_remuneracion:
            meses_descartados.add(periodo)

    # Un mes con un empleador que sí ingresó deja de estar "descartado".
    meses_descartados -= set(meses_computables)
    meses_con_reservas &= set(meses_computables)

    consolidado = _consolidar(meses_computables, tolerancia)

    todos = [e.periodo for e in evaluaciones]
    primer_periodo = min(todos) if todos else None
    ultimo_periodo = max(todos) if todos else None

    lagunas: list[IntervaloConsolidado] = []
    if primer_periodo and ultimo_periodo:
        lagunas = _detectar_lagunas(
            set(meses_computables),
            primer_periodo,
            ultimo_periodo,
            parametros.tolerancias.meses_laguna_informable,
        )

    return LineaServicios(
        cuil=historia.cuil,
        tramos=tramos,
        consolidado=consolidado,
        lagunas=lagunas,
        meses_computables=len(meses_computables),
        meses_con_reservas=len(meses_con_reservas),
        meses_descartados=len(meses_descartados),
        primer_periodo=primer_periodo,
        ultimo_periodo=ultimo_periodo,
    )
