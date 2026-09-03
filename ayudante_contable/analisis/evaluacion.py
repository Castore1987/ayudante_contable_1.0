"""Evaluación mes a mes de un registro de la historia laboral.

Separado del validador y del armador de la línea de servicios porque ambos
necesitan exactamente el mismo juicio sobre cada mes y no pueden divergir.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from ..modelo.dominio import EstadoIngreso, RegistroMensual
from .parametros import ParametrosPrevisionales, TramoAlicuota, TramoParametro

__all__ = ["EvaluacionRegistro", "evaluar_registro", "evaluar_historia"]

CERO = Decimal("0")


@dataclass(frozen=True)
class EvaluacionRegistro:
    """Diagnóstico de un mes: base mínima, coherencia del aporte e ingreso."""

    registro: RegistroMensual
    base_minima: TramoParametro | None
    alicuota: TramoAlicuota | None
    bajo_minimo: bool
    faltante_base: Decimal
    aporte_esperado: Decimal | None
    desvio_relativo: Decimal | None
    aporte_incoherente: bool
    estado_ingreso: EstadoIngreso
    topeada: bool = False

    # ------------------------------------------------------------- derivados
    @property
    def periodo(self):
        return self.registro.periodo

    @property
    def sin_parametro(self) -> bool:
        """No hay base mínima cargada: el mes no se puede juzgar."""
        return self.base_minima is None and self.registro.tiene_remuneracion

    @property
    def no_ingresado(self) -> bool:
        return self.estado_ingreso == EstadoIngreso.NO_INGRESADO

    @property
    def regularizado(self) -> bool:
        """Deuda incluida en plan de pagos o moratoria: el mes computa."""
        return self.estado_ingreso == EstadoIngreso.REGULARIZADO

    @property
    def prescripto(self) -> bool:
        """Art. 1 Ley 25.321: el período no se contabiliza."""
        return self.estado_ingreso == EstadoIngreso.PRESCRIPTO

    @property
    def ingreso_parcial(self) -> bool:
        return self.estado_ingreso == EstadoIngreso.PARCIAL

    @property
    def ingreso_incierto(self) -> bool:
        return self.estado_ingreso == EstadoIngreso.DESCONOCIDO

    @property
    def computa_servicio(self) -> bool:
        """El mes suma como servicio con aportes (criterio conservador).

        Se cuenta el mes declarado salvo que conste que el aporte no ingresó.
        Un ingreso parcial o incierto se cuenta, pero queda señalado para que
        el profesional decida.
        """
        if self.prescripto:
            # Prescripto no es ni aporte ni deuda: simplemente no cuenta.
            return False
        if not self.registro.hay_servicio:
            return False
        return not self.no_ingresado

    @property
    def computa_con_reservas(self) -> bool:
        return self.computa_servicio and (
            self.ingreso_parcial or self.ingreso_incierto or self.regularizado
        )

    @property
    def tiene_observaciones(self) -> bool:
        return (
            self.bajo_minimo
            or self.no_ingresado
            or self.ingreso_parcial
            or self.regularizado
            or self.prescripto
            or self.aporte_incoherente
            or self.sin_parametro
        )


def _resolver_estado_ingreso(
    registro: RegistroMensual, tolerancia: Decimal
) -> EstadoIngreso:
    """Combina la columna de estado con los montos para decidir si ingresó."""
    # Estados que ya vienen resueltos por la fuente: no se recalculan a partir
    # de los montos, porque el motivo no está en los importes.
    if registro.estado_ingreso in (
        EstadoIngreso.NO_INGRESADO,
        EstadoIngreso.REGULARIZADO,
        EstadoIngreso.PRESCRIPTO,
    ):
        return registro.estado_ingreso

    ingresado = registro.aporte_ingresado
    if ingresado is not None:
        if ingresado <= CERO:
            # Sin remuneración declarada, un ingreso en cero no es una deuda.
            return (
                EstadoIngreso.NO_INGRESADO
                if registro.hay_servicio
                else EstadoIngreso.DESCONOCIDO
            )
        declarado = registro.aporte_declarado
        if declarado and declarado > CERO:
            piso = declarado * (Decimal("1") - tolerancia)
            if ingresado < piso:
                return EstadoIngreso.PARCIAL
        return EstadoIngreso.INGRESADO

    return registro.estado_ingreso


def evaluar_registro(
    registro: RegistroMensual, parametros: ParametrosPrevisionales
) -> EvaluacionRegistro:
    """Evalúa un mes contra los parámetros previsionales cargados."""
    tolerancias = parametros.tolerancias
    base = parametros.base_minima(registro.periodo)
    alicuota = parametros.alicuota(registro.periodo)

    bajo_minimo = False
    faltante = CERO
    prescripto = registro.estado_ingreso == EstadoIngreso.PRESCRIPTO
    if base is not None and registro.tiene_remuneracion and not prescripto:
        piso = base.valor * (Decimal("1") - tolerancias.porcentaje_base_minima)
        if registro.remuneracion_imponible < piso:
            bajo_minimo = True
            faltante = base.valor - registro.remuneracion_imponible

    topeada = bool(
        base is not None
        and base.maximo is not None
        and registro.remuneracion_imponible >= base.maximo
    )

    aporte_esperado: Decimal | None = None
    desvio: Decimal | None = None
    incoherente = False
    # El control de coherencia depende por completo de la alícuota. Si el tramo
    # no está verificado contra la norma, se calcula el esperado como dato
    # informativo pero NO se emite juicio: sería acusar de inconsistencia a
    # partir de un parámetro que nadie auditó.
    if alicuota is not None and registro.tiene_remuneracion:
        # La base de cálculo nunca supera el tope del período.
        base_calculo = registro.remuneracion_imponible
        if base is not None and base.maximo is not None:
            base_calculo = min(base_calculo, base.maximo)
        aporte_esperado = (base_calculo * alicuota.sipa).quantize(Decimal("0.01"))
        declarado = registro.aporte_declarado
        if declarado is not None and aporte_esperado > CERO:
            desvio = (declarado - aporte_esperado) / aporte_esperado
            # Se compara contra una BANDA, no contra un valor único: según la
            # fuente, el aporte declarado puede ser solo el de SIPA (11 %) o el
            # total de seguridad social con INSSJP incluido. ARCA informa el
            # total; el HLAB, solo la remuneración. Exigir el 11 % exacto
            # marcaba como incoherentes todos los meses que trae ARCA.
            piso = base_calculo * alicuota.sipa * (Decimal("1") - tolerancias.porcentaje_aporte)
            techo = base_calculo * max(alicuota.total, alicuota.sipa) * (
                Decimal("1") + tolerancias.porcentaje_aporte
            )
            incoherente = alicuota.verificado and not (piso <= declarado <= techo)

    estado = _resolver_estado_ingreso(registro, tolerancias.porcentaje_aporte)

    return EvaluacionRegistro(
        registro=registro,
        base_minima=base,
        alicuota=alicuota,
        bajo_minimo=bajo_minimo,
        faltante_base=faltante,
        aporte_esperado=aporte_esperado,
        desvio_relativo=desvio,
        aporte_incoherente=incoherente,
        estado_ingreso=estado,
        topeada=topeada,
    )


def evaluar_historia(historia, parametros: ParametrosPrevisionales) -> list[EvaluacionRegistro]:
    return [evaluar_registro(r, parametros) for r in historia.registros]
