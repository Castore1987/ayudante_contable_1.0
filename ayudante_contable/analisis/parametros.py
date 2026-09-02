"""Parámetros previsionales vigentes por período (base imponible mínima, alícuotas).

Diseño deliberado: **ninguna cifra legal está incrustada en el código**. Los
valores viven en un archivo JSON que el estudio contable mantiene y audita. Si
un período no tiene parámetro cargado, el validador lo informa como faltante en
lugar de asumir un valor: un informe previsional no puede apoyarse en números
que el sistema inventó.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from ..modelo.dominio import Periodo

__all__ = [
    "TramoParametro",
    "TramoAlicuota",
    "Tolerancias",
    "ParametrosPrevisionales",
    "RUTA_PARAMETROS_POR_DEFECTO",
    "ErrorParametros",
]

RUTA_PARAMETROS_POR_DEFECTO = (
    Path(__file__).resolve().parents[2] / "datos" / "parametros_previsionales.json"
)

VERSION_ESQUEMA = 1


class ErrorParametros(Exception):
    """El archivo de parámetros no se pudo leer o tiene un formato inválido."""


def _a_decimal(valor: Any, campo: str) -> Decimal:
    try:
        return Decimal(str(valor))
    except (InvalidOperation, TypeError) as exc:
        raise ErrorParametros(f"Valor no numérico en '{campo}': {valor!r}") from exc


@dataclass(frozen=True)
class TramoParametro:
    """Base imponible mínima vigente entre ``desde`` y ``hasta`` (inclusive)."""

    desde: Periodo
    hasta: Periodo | None
    valor: Decimal
    norma: str = ""
    verificado: bool = False

    def cubre(self, periodo: Periodo) -> bool:
        if periodo < self.desde:
            return False
        return self.hasta is None or periodo <= self.hasta


@dataclass(frozen=True)
class TramoAlicuota:
    """Alícuotas de aporte personal vigentes en un tramo de períodos."""

    desde: Periodo
    hasta: Periodo | None
    sipa: Decimal
    inssjp: Decimal = Decimal("0")
    norma: str = ""
    verificado: bool = False

    def cubre(self, periodo: Periodo) -> bool:
        if periodo < self.desde:
            return False
        return self.hasta is None or periodo <= self.hasta

    @property
    def total(self) -> Decimal:
        return self.sipa + self.inssjp


@dataclass(frozen=True)
class Tolerancias:
    """Márgenes admitidos antes de marcar una inconsistencia."""

    # Desvío relativo tolerado entre el aporte declarado y remuneración × alícuota.
    porcentaje_aporte: Decimal = Decimal("0.02")
    # Desvío relativo tolerado por debajo de la base mínima (redondeos de liquidación).
    porcentaje_base_minima: Decimal = Decimal("0.01")
    # Meses de interrupción que no se consideran corte de tramo de servicios.
    meses_interrupcion_tolerada: int = 0
    # Meses de hueco a partir de los cuales se informa una laguna previsional.
    meses_laguna_informable: int = 1

    @classmethod
    def desde_dict(cls, datos: dict[str, Any] | None) -> "Tolerancias":
        datos = datos or {}
        base = cls()
        return cls(
            porcentaje_aporte=_a_decimal(
                datos.get("porcentaje_aporte", base.porcentaje_aporte), "porcentaje_aporte"
            ),
            porcentaje_base_minima=_a_decimal(
                datos.get("porcentaje_base_minima", base.porcentaje_base_minima),
                "porcentaje_base_minima",
            ),
            meses_interrupcion_tolerada=int(
                datos.get("meses_interrupcion_tolerada", base.meses_interrupcion_tolerada)
            ),
            meses_laguna_informable=int(
                datos.get("meses_laguna_informable", base.meses_laguna_informable)
            ),
        )


@dataclass
class ParametrosPrevisionales:
    """Colección de parámetros con resolución por período."""

    bases_minimas: list[TramoParametro] = field(default_factory=list)
    alicuotas: list[TramoAlicuota] = field(default_factory=list)
    tolerancias: Tolerancias = field(default_factory=Tolerancias)
    origen: str = "(en memoria)"

    def __post_init__(self) -> None:
        self.bases_minimas = sorted(self.bases_minimas, key=lambda t: t.desde.ordinal)
        self.alicuotas = sorted(self.alicuotas, key=lambda t: t.desde.ordinal)
        self._verificar_solapamientos()

    def _verificar_solapamientos(self) -> None:
        for nombre, tramos in (("bases_minimas", self.bases_minimas), ("alicuotas", self.alicuotas)):
            for anterior, siguiente in zip(tramos, tramos[1:]):
                if anterior.hasta is None or anterior.hasta >= siguiente.desde:
                    raise ErrorParametros(
                        f"Tramos solapados o abiertos en '{nombre}': "
                        f"{anterior.desde} y {siguiente.desde} se pisan. "
                        f"Cerrá el tramo anterior con 'hasta'."
                    )

    # ---------------------------------------------------------------- consulta
    def base_minima(self, periodo: Periodo) -> TramoParametro | None:
        for tramo in reversed(self.bases_minimas):
            if tramo.cubre(periodo):
                return tramo
        return None

    def alicuota(self, periodo: Periodo) -> TramoAlicuota | None:
        for tramo in reversed(self.alicuotas):
            if tramo.cubre(periodo):
                return tramo
        return None

    @property
    def tiene_bases(self) -> bool:
        return bool(self.bases_minimas)

    @property
    def cobertura_bases(self) -> tuple[Periodo, Periodo | None] | None:
        if not self.bases_minimas:
            return None
        return self.bases_minimas[0].desde, self.bases_minimas[-1].hasta

    def periodos_sin_base(self, periodos: list[Periodo]) -> list[Periodo]:
        return sorted({p for p in periodos if self.base_minima(p) is None})

    def bases_no_verificadas(self) -> list[TramoParametro]:
        return [t for t in self.bases_minimas if not t.verificado]

    # --------------------------------------------------------------- carga E/S
    @classmethod
    def desde_archivo(cls, ruta: str | Path | None = None) -> "ParametrosPrevisionales":
        ruta = Path(ruta) if ruta else RUTA_PARAMETROS_POR_DEFECTO
        if not ruta.exists():
            raise ErrorParametros(
                f"No encontré el archivo de parámetros: {ruta}\n"
                "Creá uno a partir de datos/parametros_previsionales.json."
            )
        try:
            datos = json.loads(ruta.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ErrorParametros(f"JSON inválido en {ruta}: {exc}") from exc
        parametros = cls.desde_dict(datos)
        parametros.origen = str(ruta)
        return parametros

    @classmethod
    def desde_dict(cls, datos: dict[str, Any]) -> "ParametrosPrevisionales":
        version = datos.get("version", VERSION_ESQUEMA)
        if version != VERSION_ESQUEMA:
            raise ErrorParametros(
                f"Versión de esquema {version} no soportada (se esperaba {VERSION_ESQUEMA})."
            )

        bases = [
            TramoParametro(
                desde=Periodo.desde_valor(item["desde"]),
                hasta=Periodo.desde_valor(item["hasta"]) if item.get("hasta") else None,
                valor=_a_decimal(item["valor"], "bases_minimas.valor"),
                norma=str(item.get("norma", "")),
                verificado=bool(item.get("verificado", False)),
            )
            for item in datos.get("bases_minimas", [])
        ]

        alicuotas = [
            TramoAlicuota(
                desde=Periodo.desde_valor(item["desde"]),
                hasta=Periodo.desde_valor(item["hasta"]) if item.get("hasta") else None,
                sipa=_a_decimal(item["sipa"], "alicuotas.sipa"),
                inssjp=_a_decimal(item.get("inssjp", 0), "alicuotas.inssjp"),
                norma=str(item.get("norma", "")),
                verificado=bool(item.get("verificado", False)),
            )
            for item in datos.get("alicuotas_personales", [])
        ]

        return cls(
            bases_minimas=bases,
            alicuotas=alicuotas,
            tolerancias=Tolerancias.desde_dict(datos.get("tolerancias")),
        )

    def a_dict(self) -> dict[str, Any]:
        return {
            "version": VERSION_ESQUEMA,
            "bases_minimas": [
                {
                    "desde": t.desde.compacto,
                    "hasta": t.hasta.compacto if t.hasta else None,
                    "valor": str(t.valor),
                    "norma": t.norma,
                    "verificado": t.verificado,
                }
                for t in self.bases_minimas
            ],
            "alicuotas_personales": [
                {
                    "desde": t.desde.compacto,
                    "hasta": t.hasta.compacto if t.hasta else None,
                    "sipa": str(t.sipa),
                    "inssjp": str(t.inssjp),
                    "norma": t.norma,
                    "verificado": t.verificado,
                }
                for t in self.alicuotas
            ],
            "tolerancias": {
                "porcentaje_aporte": str(self.tolerancias.porcentaje_aporte),
                "porcentaje_base_minima": str(self.tolerancias.porcentaje_base_minima),
                "meses_interrupcion_tolerada": self.tolerancias.meses_interrupcion_tolerada,
                "meses_laguna_informable": self.tolerancias.meses_laguna_informable,
            },
        }

    def guardar(self, ruta: str | Path) -> None:
        ruta = Path(ruta)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text(
            json.dumps(self.a_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
