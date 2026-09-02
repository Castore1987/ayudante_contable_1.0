"""Validación previsional: detecta aportes bajo el mínimo, impagos y lagunas.

Los hallazgos se agrupan en rangos de meses consecutivos. Una historia laboral
de treinta años con un empleador que nunca llegó al mínimo debe producir un
hallazgo con su rango, no trescientos sesenta hallazgos sueltos.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Callable, Iterable

from ..modelo.dominio import (
    HistoriaLaboral,
    Hallazgo,
    Periodo,
    Severidad,
    cuil_valido,
    formatear_cuil,
)
from .evaluacion import EvaluacionRegistro, evaluar_historia
from .linea_servicios import LineaServicios, construir_linea_servicios
from .parametros import ParametrosPrevisionales

__all__ = ["Informe", "analizar", "CODIGOS"]

CODIGOS = {
    "SIN_REGISTROS": "La historia laboral no trajo ningún período.",
    "CUIL_INVALIDO": "El CUIL no supera la verificación de dígito verificador.",
    "PARAMETROS_SIN_CARGAR": "No hay base imponible mínima cargada.",
    "PARAMETROS_NO_VERIFICADOS": "Hay tramos de parámetros sin verificar contra la norma.",
    "SIN_PARAMETRO_BASE_MINIMA": "Períodos sin base imponible mínima cargada.",
    "APORTE_BAJO_MINIMO": "Remuneración imponible por debajo de la base mínima.",
    "APORTE_NO_INGRESADO": "Aporte declarado sin ingreso registrado.",
    "APORTE_INGRESO_PARCIAL": "El monto ingresado es menor al declarado.",
    "APORTE_INGRESO_INCIERTO": "La fuente no informa si el aporte ingresó.",
    "APORTE_INCOHERENTE": "El aporte declarado no guarda relación con la remuneración.",
    "LAGUNA_PREVISIONAL": "Meses sin servicios entre el primer y el último aporte.",
    "EMPLEOS_SIMULTANEOS": "Meses con más de un empleador declarando a la vez.",
    "TRAMO_INTERRUMPIDO": "Tramo con meses sin declaración en el medio.",
    "MENOS_QUE_ANSES": "Meses que ANSES reconoce y el sistema no computó.",
    "MAS_QUE_ANSES": "Meses computados que ANSES no reconoce en su resumen.",
}


@dataclass
class Informe:
    """Resultado completo del análisis de una historia laboral."""

    historia: HistoriaLaboral
    evaluaciones: list[EvaluacionRegistro]
    linea: LineaServicios
    hallazgos: list[Hallazgo] = field(default_factory=list)
    parametros_origen: str = ""

    def por_severidad(self, severidad: Severidad) -> list[Hallazgo]:
        return [h for h in self.hallazgos if h.severidad == severidad]

    @property
    def errores(self) -> list[Hallazgo]:
        return self.por_severidad(Severidad.ERROR)

    @property
    def advertencias(self) -> list[Hallazgo]:
        return self.por_severidad(Severidad.ADVERTENCIA)

    @property
    def apto_para_certificar(self) -> bool:
        """Sin errores no significa 'jubilable': significa 'sin inconsistencias'."""
        return not self.errores

    @property
    def resumen(self) -> dict[str, int]:
        return {
            "registros": len(self.historia.registros),
            "meses_computables": self.linea.meses_computables,
            "meses_con_reservas": self.linea.meses_con_reservas,
            "meses_descartados": self.linea.meses_descartados,
            "meses_laguna": self.linea.meses_laguna,
            "tramos": len(self.linea.tramos),
            "errores": len(self.errores),
            "advertencias": len(self.advertencias),
        }


# --------------------------------------------------------------- agrupamiento


def _agrupar_rangos(periodos: Iterable[Periodo]) -> list[tuple[Periodo, Periodo]]:
    """Convierte meses sueltos en rangos consecutivos ``(inicio, fin)``."""
    ordenados = sorted(set(periodos))
    if not ordenados:
        return []

    rangos: list[tuple[Periodo, Periodo]] = []
    inicio = anterior = ordenados[0]
    for periodo in ordenados[1:]:
        if periodo.ordinal - anterior.ordinal > 1:
            rangos.append((inicio, anterior))
            inicio = periodo
        anterior = periodo
    rangos.append((inicio, anterior))
    return rangos


def _hallazgos_por_empleador(
    evaluaciones: list[EvaluacionRegistro],
    predicado: Callable[[EvaluacionRegistro], bool],
    codigo: str,
    severidad: Severidad,
    mensaje: Callable[[str, list[EvaluacionRegistro]], str],
) -> list[Hallazgo]:
    """Agrupa los meses que cumplen ``predicado`` por empleador y rango."""
    por_empleador: dict[str, list[EvaluacionRegistro]] = {}
    for evaluacion in evaluaciones:
        if predicado(evaluacion):
            por_empleador.setdefault(evaluacion.registro.nombre_visible, []).append(evaluacion)

    hallazgos: list[Hallazgo] = []
    for empleador, grupo in sorted(por_empleador.items()):
        indice = {e.periodo: e for e in grupo}
        for inicio, fin in _agrupar_rangos(indice):
            del_rango = [indice[p] for p in Periodo.rango(inicio, fin) if p in indice]
            hallazgos.append(
                Hallazgo(
                    codigo=codigo,
                    severidad=severidad,
                    mensaje=mensaje(empleador, del_rango),
                    periodo=inicio,
                    periodo_fin=fin,
                    empleador=empleador,
                    detalle={"meses": str(len(del_rango))},
                )
            )
    return hallazgos


def _formato_monto(valor: Decimal) -> str:
    return f"$ {valor:,.2f}".replace(",", "@").replace(".", ",").replace("@", ".")


# ------------------------------------------------------------------ controles


def _control_cuil(historia: HistoriaLaboral) -> list[Hallazgo]:
    if cuil_valido(historia.cuil):
        return []
    return [
        Hallazgo(
            codigo="CUIL_INVALIDO",
            severidad=Severidad.ERROR,
            mensaje=(
                f"El CUIL {formatear_cuil(historia.cuil)} no pasa la verificación de "
                "dígito verificador. Revisá el dato antes de usar este informe."
            ),
        )
    ]


def _control_parametros(
    evaluaciones: list[EvaluacionRegistro], parametros: ParametrosPrevisionales
) -> list[Hallazgo]:
    hallazgos: list[Hallazgo] = []

    if not parametros.tiene_bases:
        hallazgos.append(
            Hallazgo(
                codigo="PARAMETROS_SIN_CARGAR",
                severidad=Severidad.ADVERTENCIA,
                mensaje=(
                    "No hay bases imponibles mínimas cargadas: el control de mínimo "
                    f"no se ejecutó. Cargá los valores oficiales en {parametros.origen}."
                ),
            )
        )
    else:
        sin_parametro = [e.periodo for e in evaluaciones if e.sin_parametro]
        for inicio, fin in _agrupar_rangos(sin_parametro):
            meses = fin.ordinal - inicio.ordinal + 1
            hallazgos.append(
                Hallazgo(
                    codigo="SIN_PARAMETRO_BASE_MINIMA",
                    severidad=Severidad.ADVERTENCIA,
                    mensaje=(
                        f"{meses} mes(es) sin base imponible mínima cargada: no se "
                        "emitió juicio sobre el mínimo en ese tramo."
                    ),
                    periodo=inicio,
                    periodo_fin=fin,
                )
            )

    no_verificados = parametros.bases_no_verificadas()
    if no_verificados:
        hallazgos.append(
            Hallazgo(
                codigo="PARAMETROS_NO_VERIFICADOS",
                severidad=Severidad.ADVERTENCIA,
                mensaje=(
                    f"{len(no_verificados)} tramo(s) de base mínima están sin verificar "
                    "contra la norma. El informe usa esos valores, pero no están auditados."
                ),
                detalle={"tramos": ", ".join(str(t.desde) for t in no_verificados[:12])},
            )
        )

    return hallazgos


def _control_minimo(evaluaciones: list[EvaluacionRegistro]) -> list[Hallazgo]:
    def mensaje(empleador: str, grupo: list[EvaluacionRegistro]) -> str:
        faltante = sum((e.faltante_base for e in grupo), start=Decimal("0"))
        return (
            f"{empleador}: {len(grupo)} mes(es) con remuneración imponible por debajo "
            f"de la base mínima. Diferencia acumulada {_formato_monto(faltante)}."
        )

    return _hallazgos_por_empleador(
        evaluaciones, lambda e: e.bajo_minimo, "APORTE_BAJO_MINIMO", Severidad.ERROR, mensaje
    )


def _control_ingreso(evaluaciones: list[EvaluacionRegistro]) -> list[Hallazgo]:
    hallazgos: list[Hallazgo] = []

    hallazgos += _hallazgos_por_empleador(
        evaluaciones,
        lambda e: e.no_ingresado and e.registro.hay_servicio,
        "APORTE_NO_INGRESADO",
        Severidad.ERROR,
        lambda emp, grupo: (
            f"{emp}: {len(grupo)} mes(es) con servicio declarado y sin aporte ingresado. "
            "Esos meses no computan como servicio con aportes."
        ),
    )

    hallazgos += _hallazgos_por_empleador(
        evaluaciones,
        lambda e: e.ingreso_parcial,
        "APORTE_INGRESO_PARCIAL",
        Severidad.ADVERTENCIA,
        lambda emp, grupo: (
            f"{emp}: {len(grupo)} mes(es) con ingreso menor al aporte declarado."
        ),
    )

    hallazgos += _hallazgos_por_empleador(
        evaluaciones,
        lambda e: e.ingreso_incierto and e.registro.hay_servicio,
        "APORTE_INGRESO_INCIERTO",
        Severidad.ADVERTENCIA,
        lambda emp, grupo: (
            f"{emp}: {len(grupo)} mes(es) sin dato de ingreso efectivo. Se computaron "
            "como servicio, pero conviene pedir la constancia de pago."
        ),
    )

    return hallazgos


def _control_coherencia(evaluaciones: list[EvaluacionRegistro]) -> list[Hallazgo]:
    return _hallazgos_por_empleador(
        evaluaciones,
        lambda e: e.aporte_incoherente,
        "APORTE_INCOHERENTE",
        Severidad.ADVERTENCIA,
        lambda emp, grupo: (
            f"{emp}: {len(grupo)} mes(es) donde el aporte declarado se aparta de "
            "remuneración × alícuota más allá de la tolerancia configurada."
        ),
    )


def _control_lagunas(linea: LineaServicios) -> list[Hallazgo]:
    return [
        Hallazgo(
            codigo="LAGUNA_PREVISIONAL",
            severidad=Severidad.INFORMACION,
            mensaje=f"{laguna.meses} mes(es) sin servicios computables.",
            periodo=laguna.inicio,
            periodo_fin=laguna.fin,
            detalle={"meses": str(laguna.meses)},
        )
        for laguna in linea.lagunas
    ]


def _control_simultaneidad(evaluaciones: list[EvaluacionRegistro]) -> list[Hallazgo]:
    por_periodo: dict[Periodo, set[str]] = {}
    for evaluacion in evaluaciones:
        if evaluacion.registro.hay_servicio:
            por_periodo.setdefault(evaluacion.periodo, set()).add(
                evaluacion.registro.clave_empleador
            )

    simultaneos = [p for p, empleadores in por_periodo.items() if len(empleadores) > 1]
    return [
        Hallazgo(
            codigo="EMPLEOS_SIMULTANEOS",
            severidad=Severidad.INFORMACION,
            mensaje=(
                f"{fin.ordinal - inicio.ordinal + 1} mes(es) con más de un empleador "
                "declarando en simultáneo. El mes se computa una sola vez."
            ),
            periodo=inicio,
            periodo_fin=fin,
        )
        for inicio, fin in _agrupar_rangos(simultaneos)
    ]


def _control_contraste(
    historia: HistoriaLaboral, evaluaciones: list[EvaluacionRegistro]
) -> list[Hallazgo]:
    """Contrasta el cómputo propio contra la línea que declara la fuente.

    El HLAB trae su propio RESUMEN: la antigüedad según ANSES. Compararla con
    la calculada es el control más barato y más útil del informe. Una
    diferencia no significa que alguno esté mal: significa que hay meses en
    discusión, y son justo los que hay que mirar.
    """
    if not historia.tramos_declarados:
        return []

    meses_fuente: set[Periodo] = set()
    for tramo in historia.tramos_declarados:
        meses_fuente |= set(Periodo.rango(tramo.desde, tramo.hasta))
    if not meses_fuente:
        return []

    meses_propios = {e.periodo for e in evaluaciones if e.computa_servicio}

    hallazgos: list[Hallazgo] = []
    for inicio, fin in _agrupar_rangos(meses_fuente - meses_propios):
        hallazgos.append(
            Hallazgo(
                codigo="MENOS_QUE_ANSES",
                severidad=Severidad.ADVERTENCIA,
                mensaje=(
                    f"{fin.ordinal - inicio.ordinal + 1} mes(es) que el resumen de "
                    "ANSES reconoce y el sistema no computó. Revisá si se perdió "
                    "algún renglón al leer el documento."
                ),
                periodo=inicio,
                periodo_fin=fin,
            )
        )

    for inicio, fin in _agrupar_rangos(meses_propios - meses_fuente):
        hallazgos.append(
            Hallazgo(
                codigo="MAS_QUE_ANSES",
                severidad=Severidad.ADVERTENCIA,
                mensaje=(
                    f"{fin.ordinal - inicio.ordinal + 1} mes(es) computados que el "
                    "resumen de ANSES no reconoce. Son los meses en discusión: "
                    "salvo que aparezca el respaldo del aporte, ANSES no los va a contar."
                ),
                periodo=inicio,
                periodo_fin=fin,
            )
        )

    return hallazgos


def _control_tramos(linea: LineaServicios) -> list[Hallazgo]:
    return [
        Hallazgo(
            codigo="TRAMO_INTERRUMPIDO",
            severidad=Severidad.INFORMACION,
            mensaje=(
                f"{tramo.empleador}: el tramo abarca {tramo.meses_calendario} mes(es) "
                f"pero solo {tramo.meses_declarados} tienen declaración "
                f"({tramo.meses_faltantes} sin declarar)."
            ),
            periodo=tramo.inicio,
            periodo_fin=tramo.fin,
            empleador=tramo.empleador,
        )
        for tramo in linea.tramos
        if not tramo.continuo
    ]


# --------------------------------------------------------------------- fachada


def analizar(historia: HistoriaLaboral, parametros: ParametrosPrevisionales) -> Informe:
    """Ejecuta todos los controles y arma la línea de servicios."""
    evaluaciones = evaluar_historia(historia, parametros)
    linea = construir_linea_servicios(historia, parametros, evaluaciones)

    hallazgos: list[Hallazgo] = []
    hallazgos += _control_cuil(historia)

    if not historia.registros:
        hallazgos.append(
            Hallazgo(
                codigo="SIN_REGISTROS",
                severidad=Severidad.ERROR,
                mensaje=(
                    "La historia laboral llegó vacía. Revisá la fuente antes de "
                    "concluir que el afiliado no registra aportes."
                ),
            )
        )
    else:
        hallazgos += _control_parametros(evaluaciones, parametros)
        hallazgos += _control_minimo(evaluaciones)
        hallazgos += _control_ingreso(evaluaciones)
        hallazgos += _control_coherencia(evaluaciones)
        hallazgos += _control_lagunas(linea)
        hallazgos += _control_simultaneidad(evaluaciones)
        hallazgos += _control_tramos(linea)
        hallazgos += _control_contraste(historia, evaluaciones)

    for advertencia in historia.advertencias_origen:
        hallazgos.append(
            Hallazgo(
                codigo="ORIGEN_DATOS",
                severidad=Severidad.ADVERTENCIA,
                mensaje=advertencia,
            )
        )

    hallazgos.sort(
        key=lambda h: (
            h.severidad.orden,
            h.periodo.ordinal if h.periodo else 0,
            h.codigo,
        )
    )

    return Informe(
        historia=historia,
        evaluaciones=evaluaciones,
        linea=linea,
        hallazgos=hallazgos,
        parametros_origen=parametros.origen,
    )
