"""Constructores compartidos por las pruebas."""

from decimal import Decimal

from ayudante_contable.analisis.parametros import (
    ParametrosPrevisionales,
    Tolerancias,
    TramoAlicuota,
    TramoParametro,
)
from ayudante_contable.modelo.dominio import (
    EstadoIngreso,
    HistoriaLaboral,
    Periodo,
    RegistroMensual,
    TipoAporte,
)

CUIL = "20-12345678-6"


def parametros(base=Decimal("1000"), desde=(2020, 1), **tolerancias) -> ParametrosPrevisionales:
    return ParametrosPrevisionales(
        bases_minimas=[
            TramoParametro(
                desde=Periodo(*desde), hasta=None, valor=base, norma="prueba", verificado=True
            )
        ],
        alicuotas=[
            TramoAlicuota(
                desde=Periodo(*desde),
                hasta=None,
                sipa=Decimal("0.11"),
                norma="prueba",
                verificado=True,
            )
        ],
        tolerancias=Tolerancias(**tolerancias) if tolerancias else Tolerancias(),
        origen="(prueba)",
    )


def meses(
    desde,
    hasta,
    cuit="30111111112",
    empleador="ACME SA",
    remuneracion="5000",
    estado=EstadoIngreso.INGRESADO,
    tipo=TipoAporte.RELACION_DEPENDENCIA,
    aporte_declarado=None,
    aporte_ingresado=None,
):
    """Genera registros mensuales continuos entre dos períodos ``(año, mes)``."""
    registros = []
    for periodo in Periodo.rango(Periodo(*desde), Periodo(*hasta)):
        remuneracion_decimal = Decimal(remuneracion)
        registros.append(
            RegistroMensual(
                periodo=periodo,
                cuit_empleador=cuit,
                empleador=empleador,
                tipo=tipo,
                remuneracion_imponible=remuneracion_decimal,
                aporte_declarado=(
                    Decimal(aporte_declarado)
                    if aporte_declarado is not None
                    else (remuneracion_decimal * Decimal("0.11")).quantize(Decimal("0.01"))
                ),
                aporte_ingresado=(
                    Decimal(aporte_ingresado) if aporte_ingresado is not None else None
                ),
                estado_ingreso=estado,
            )
        )
    return registros


def historia(*grupos, cuil=CUIL) -> HistoriaLaboral:
    registros = [registro for grupo in grupos for registro in grupo]
    return HistoriaLaboral(cuil=cuil, registros=registros, fuente="prueba")
