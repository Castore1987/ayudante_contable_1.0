"""Consolidación de varias fuentes en una sola historia laboral.

Ninguna fuente alcanza sola, y cada una es buena en algo distinto:

======================  ===============================  ========================
Fuente                  Aporta                           No aporta
======================  ===============================  ========================
HLAB de ANSES           Remuneración **imponible**       Si el aporte ingresó
                        (ya topeada), mes a mes
ARCA «Aportes en Línea» Declarado vs **depositado**      Remuneración imponible
                        en relación de dependencia       (informa la bruta)
SICAM                   Deuda y prescripción de          Nada de relación de
                        autónomos y monotributo          dependencia
======================  ===============================  ========================

De ahí la regla de precedencia: **el pago efectivo manda sobre la
declaración**, y la remuneración imponible se toma de quien la informa como
imponible. Cuando dos fuentes se contradicen, la diferencia no se resuelve en
silencio: queda registrada como conflicto para que la mire el profesional.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from ..modelo.dominio import (
    EstadoIngreso,
    HistoriaLaboral,
    Periodo,
    RegistroMensual,
    formatear_cuil,
)

__all__ = ["consolidar", "ConflictoFuentes", "clase_de_fuente"]

CERO = Decimal("0")

# Quién manda para la remuneración imponible.
_PRIORIDAD_REMUNERACION = {"hlab": 4, "planilla": 3, "pdf": 3, "arca": 2, "sicam": 1}
# Quién manda para el ingreso efectivo del aporte.
_PRIORIDAD_INGRESO = {"arca": 4, "sicam": 4, "planilla": 2, "pdf": 2, "hlab": 1}

# Qué concepto de remuneración informa cada fuente. El HLAB informa la
# imponible (topeada) y ARCA la total bruta: no son el mismo número y no tiene
# sentido tratarlos como una contradicción entre fuentes.
_CONCEPTO_REMUNERACION = {
    "hlab": "imponible",
    "planilla": "imponible",
    "pdf": "imponible",
    "arca": "bruta",
    "sicam": "sin_remuneracion",
}

# Estados que constituyen una respuesta; DESCONOCIDO no desplaza a nadie.
_ESTADOS_DEFINIDOS = frozenset(
    {
        EstadoIngreso.INGRESADO,
        EstadoIngreso.NO_INGRESADO,
        EstadoIngreso.PARCIAL,
        EstadoIngreso.REGULARIZADO,
        EstadoIngreso.PRESCRIPTO,
    }
)


def clase_de_fuente(fuente: str) -> str:
    """Reduce ``"hlab-anses:archivo.pdf"`` a ``"hlab"``."""
    raiz = (fuente or "").split(":", 1)[0].lower()
    for clase in ("hlab", "arca", "sicam", "planilla", "pdf"):
        if raiz.startswith(clase):
            return clase
    return raiz or "desconocida"


@dataclass(frozen=True)
class ConflictoFuentes:
    """Dos fuentes dicen cosas distintas del mismo mes."""

    periodo: Periodo
    empleador: str
    campo: str
    valor_a: str
    fuente_a: str
    valor_b: str
    fuente_b: str

    @property
    def mensaje(self) -> str:
        return (
            f"{self.empleador} {self.periodo}: {self.campo} difiere entre fuentes "
            f"({self.fuente_a} dice {self.valor_a}; {self.fuente_b} dice {self.valor_b})."
        )


@dataclass
class _Aporte:
    """Un registro con la clase de fuente de la que vino."""

    registro: RegistroMensual
    clase: str


@dataclass
class ResultadoConsolidacion:
    historia: HistoriaLaboral
    conflictos: list[ConflictoFuentes] = field(default_factory=list)
    fuentes: list[str] = field(default_factory=list)


def _mejor(aportes: list[_Aporte], prioridades: dict[str, int]) -> _Aporte:
    return max(aportes, key=lambda a: prioridades.get(a.clase, 0))


def _fusionar(
    aportes: list[_Aporte], conflictos: list[ConflictoFuentes]
) -> RegistroMensual:
    """Combina los registros de un mismo mes y empleador."""
    if len(aportes) == 1:
        return aportes[0].registro

    con_remuneracion = [a for a in aportes if a.registro.remuneracion_imponible > CERO]
    fuente_remuneracion = (
        _mejor(con_remuneracion, _PRIORIDAD_REMUNERACION) if con_remuneracion else aportes[0]
    )

    con_estado = [
        a for a in aportes if a.registro.estado_ingreso in _ESTADOS_DEFINIDOS
    ]
    fuente_estado = _mejor(con_estado, _PRIORIDAD_INGRESO) if con_estado else aportes[0]

    base = fuente_remuneracion.registro
    estado = fuente_estado.registro

    # Conflicto de remuneración: solo entre fuentes que informan el MISMO
    # concepto. La diferencia entre la imponible del HLAB y la bruta de ARCA es
    # esperada —la primera viene topeada— y marcarla sería ruido.
    concepto_base = _CONCEPTO_REMUNERACION.get(fuente_remuneracion.clase)
    for otro in con_remuneracion:
        if otro is fuente_remuneracion:
            continue
        if _CONCEPTO_REMUNERACION.get(otro.clase) != concepto_base:
            continue
        a, b = base.remuneracion_imponible, otro.registro.remuneracion_imponible
        if a and abs(a - b) > max(a * Decimal("0.01"), Decimal("1")):
            conflictos.append(
                ConflictoFuentes(
                    periodo=base.periodo,
                    empleador=base.nombre_visible,
                    campo="remuneración imponible",
                    valor_a=f"{a:.2f}",
                    fuente_a=fuente_remuneracion.clase,
                    valor_b=f"{b:.2f}",
                    fuente_b=otro.clase,
                )
            )

    # Conflicto de estado de ingreso entre fuentes que ambas lo afirman.
    for otro in con_estado:
        if otro is fuente_estado:
            continue
        if otro.registro.estado_ingreso != estado.estado_ingreso:
            conflictos.append(
                ConflictoFuentes(
                    periodo=base.periodo,
                    empleador=base.nombre_visible,
                    campo="estado del aporte",
                    valor_a=estado.estado_ingreso.value,
                    fuente_a=fuente_estado.clase,
                    valor_b=otro.registro.estado_ingreso.value,
                    fuente_b=otro.clase,
                )
            )

    notas = []
    for aporte in aportes:
        if aporte.registro.observaciones:
            notas.append(f"[{aporte.clase}] {aporte.registro.observaciones}")

    return RegistroMensual(
        periodo=base.periodo,
        cuit_empleador=base.cuit_empleador or estado.cuit_empleador,
        # El HLAB trunca la razón social; se conserva la más larga.
        empleador=max(
            (a.registro.empleador or "" for a in aportes), key=len, default=None
        ) or None,
        tipo=base.tipo if base.tipo.value != "desconocido" else estado.tipo,
        remuneracion_imponible=base.remuneracion_imponible,
        aporte_declarado=estado.aporte_declarado or base.aporte_declarado,
        aporte_ingresado=estado.aporte_ingresado or base.aporte_ingresado,
        estado_ingreso=estado.estado_ingreso,
        servicio_reconocido=any(a.registro.servicio_reconocido for a in aportes),
        observaciones="; ".join(notas),
    )


def consolidar(
    historias: list[HistoriaLaboral], nombre: str | None = None
) -> ResultadoConsolidacion:
    """Une varias historias laborales del mismo afiliado en una sola."""
    if not historias:
        raise ValueError("No hay ninguna fuente para consolidar.")

    cuiles = {h.cuil for h in historias}
    if len(cuiles) > 1:
        raise ValueError(
            "Las fuentes corresponden a CUIL distintos: "
            + ", ".join(sorted(formatear_cuil(c) for c in cuiles))
            + ". Revisá que todos los archivos sean del mismo cliente."
        )

    agrupado: dict[tuple[int, str], list[_Aporte]] = {}
    for historia in historias:
        clase = clase_de_fuente(historia.fuente)
        for registro in historia.registros:
            clave = (registro.periodo.ordinal, registro.clave_empleador)
            agrupado.setdefault(clave, []).append(_Aporte(registro, clase))

    conflictos: list[ConflictoFuentes] = []
    registros = [_fusionar(aportes, conflictos) for _, aportes in sorted(agrupado.items())]

    advertencias: list[str] = []
    tramos_declarados: list = []
    for historia in historias:
        etiqueta = clase_de_fuente(historia.fuente)
        advertencias.extend(f"[{etiqueta}] {a}" for a in historia.advertencias_origen)
        tramos_declarados.extend(historia.tramos_declarados)

    fuentes = [h.fuente for h in historias]
    consolidada = HistoriaLaboral(
        cuil=historias[0].cuil,
        registros=registros,
        nombre=nombre or next((h.nombre for h in historias if h.nombre), None),
        fecha_consulta=next((h.fecha_consulta for h in historias if h.fecha_consulta), None),
        fuente="consolidado(" + ", ".join(sorted({clase_de_fuente(f) for f in fuentes})) + ")",
        advertencias_origen=advertencias,
        tramos_declarados=tramos_declarados,
    )
    return ResultadoConsolidacion(
        historia=consolidada, conflictos=conflictos, fuentes=fuentes
    )
