"""Modelo de dominio del ayudante contable previsional.

Todas las estructuras son inmutables salvo los contenedores de agregación.
Los importes se manejan siempre con ``Decimal`` para evitar errores de coma
flotante en montos de aportes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Iterator

__all__ = [
    "Periodo",
    "TipoAporte",
    "EstadoIngreso",
    "Severidad",
    "RegistroMensual",
    "HistoriaLaboral",
    "TramoServicio",
    "Hallazgo",
    "cuil_valido",
    "normalizar_cuil",
    "formatear_cuil",
]

_MESES = 12

_RE_PERIODO_BARRA = re.compile(r"^\s*(\d{1,2})\s*[/\-]\s*(\d{4})\s*$")
_RE_PERIODO_BARRA_INV = re.compile(r"^\s*(\d{4})\s*[/\-]\s*(\d{1,2})\s*$")
_RE_PERIODO_COMPACTO = re.compile(r"^\s*(\d{4})(\d{2})\s*$")


@dataclass(frozen=True, order=True)
class Periodo:
    """Un período mensual devengado (año/mes), la unidad de cómputo de ANSES."""

    anio: int
    mes: int

    def __post_init__(self) -> None:
        if not 1900 <= self.anio <= 2200:
            raise ValueError(f"Año fuera de rango: {self.anio}")
        if not 1 <= self.mes <= _MESES:
            raise ValueError(f"Mes fuera de rango: {self.mes}")

    # ---------------------------------------------------------------- parseo
    @classmethod
    def desde_texto(cls, texto: str) -> "Periodo":
        """Acepta ``MM/AAAA``, ``AAAA/MM``, ``AAAAMM``, ``MM-AAAA``."""
        if not isinstance(texto, str):
            raise TypeError(f"Se esperaba texto, llegó {type(texto).__name__}")

        m = _RE_PERIODO_COMPACTO.match(texto)
        if m:
            return cls(int(m.group(1)), int(m.group(2)))

        m = _RE_PERIODO_BARRA_INV.match(texto)
        if m:
            return cls(int(m.group(1)), int(m.group(2)))

        m = _RE_PERIODO_BARRA.match(texto)
        if m:
            return cls(int(m.group(2)), int(m.group(1)))

        raise ValueError(f"No pude interpretar el período: {texto!r}")

    @classmethod
    def desde_valor(cls, valor: "Periodo | str | int") -> "Periodo":
        if isinstance(valor, Periodo):
            return valor
        if isinstance(valor, int):
            return cls.desde_texto(str(valor))
        return cls.desde_texto(valor)

    # ------------------------------------------------------------ aritmética
    @property
    def ordinal(self) -> int:
        """Cantidad de meses desde el año 0; permite restar períodos."""
        return self.anio * _MESES + (self.mes - 1)

    @classmethod
    def desde_ordinal(cls, ordinal: int) -> "Periodo":
        return cls(ordinal // _MESES, ordinal % _MESES + 1)

    def sumar_meses(self, meses: int) -> "Periodo":
        return Periodo.desde_ordinal(self.ordinal + meses)

    def __add__(self, meses: int) -> "Periodo":
        return self.sumar_meses(meses)

    def __sub__(self, otro: "Periodo | int") -> "Periodo | int":
        if isinstance(otro, Periodo):
            return self.ordinal - otro.ordinal
        return self.sumar_meses(-otro)

    def distancia(self, otro: "Periodo") -> int:
        """Meses entre dos períodos (siempre >= 0)."""
        return abs(self.ordinal - otro.ordinal)

    @staticmethod
    def rango(desde: "Periodo", hasta: "Periodo") -> Iterator["Periodo"]:
        """Itera de ``desde`` a ``hasta`` inclusive."""
        if hasta < desde:
            return
        for ordinal in range(desde.ordinal, hasta.ordinal + 1):
            yield Periodo.desde_ordinal(ordinal)

    # ------------------------------------------------------------- formateo
    def __str__(self) -> str:
        return f"{self.mes:02d}/{self.anio}"

    @property
    def compacto(self) -> str:
        return f"{self.anio}{self.mes:02d}"


class TipoAporte(str, Enum):
    """Régimen bajo el cual se registró el aporte."""

    RELACION_DEPENDENCIA = "relacion_dependencia"
    AUTONOMO = "autonomo"
    MONOTRIBUTO = "monotributo"
    CASAS_PARTICULARES = "casas_particulares"
    DESCONOCIDO = "desconocido"

    @classmethod
    def desde_texto(cls, texto: str | None) -> "TipoAporte":
        if not texto:
            return cls.DESCONOCIDO
        clave = _normalizar(texto)
        tabla = {
            "relacion de dependencia": cls.RELACION_DEPENDENCIA,
            "relacion dependencia": cls.RELACION_DEPENDENCIA,
            "dependencia": cls.RELACION_DEPENDENCIA,
            "rd": cls.RELACION_DEPENDENCIA,
            "empleado": cls.RELACION_DEPENDENCIA,
            "autonomo": cls.AUTONOMO,
            "autonomos": cls.AUTONOMO,
            "monotributo": cls.MONOTRIBUTO,
            "monotributista": cls.MONOTRIBUTO,
            "casas particulares": cls.CASAS_PARTICULARES,
            "servicio domestico": cls.CASAS_PARTICULARES,
            "personal de casas particulares": cls.CASAS_PARTICULARES,
        }
        return tabla.get(clave, cls.DESCONOCIDO)

    @property
    def etiqueta(self) -> str:
        return {
            TipoAporte.RELACION_DEPENDENCIA: "Relación de dependencia",
            TipoAporte.AUTONOMO: "Autónomo",
            TipoAporte.MONOTRIBUTO: "Monotributo",
            TipoAporte.CASAS_PARTICULARES: "Casas particulares",
            TipoAporte.DESCONOCIDO: "Sin determinar",
        }[self]


class EstadoIngreso(str, Enum):
    """Si el aporte declarado fue efectivamente ingresado al sistema."""

    INGRESADO = "ingresado"
    NO_INGRESADO = "no_ingresado"
    PARCIAL = "parcial"
    # Deuda incluida en un plan de pagos o una moratoria: el mes computa.
    REGULARIZADO = "regularizado"
    # Alcanzado por el Art. 1 Ley 25.321: el período está prescripto y NO se
    # contabiliza. No es deuda a reclamar ni un aporte a acreditar.
    PRESCRIPTO = "prescripto"
    DESCONOCIDO = "desconocido"

    @classmethod
    def desde_texto(cls, texto: str | None) -> "EstadoIngreso":
        if texto is None:
            return cls.DESCONOCIDO
        clave = _normalizar(texto)
        if clave in {"si", "s", "true", "1", "ingresado", "pagado", "ok", "cancelado"}:
            return cls.INGRESADO
        if clave in {"no", "n", "false", "0", "no ingresado", "impago", "adeudado", "deuda"}:
            return cls.NO_INGRESADO
        if clave in {"parcial", "parcialmente", "pago parcial"}:
            return cls.PARCIAL
        if clave in {"regularizado", "plan de pagos", "moratoria", "plan"}:
            return cls.REGULARIZADO
        if clave in {"prescripto", "prescripta", "prescripcion"}:
            return cls.PRESCRIPTO
        return cls.DESCONOCIDO


class Severidad(str, Enum):
    ERROR = "error"
    ADVERTENCIA = "advertencia"
    INFORMACION = "informacion"

    @property
    def orden(self) -> int:
        return {Severidad.ERROR: 0, Severidad.ADVERTENCIA: 1, Severidad.INFORMACION: 2}[self]


@dataclass(frozen=True)
class RegistroMensual:
    """Una fila de la historia laboral: un mes aportado por un empleador."""

    periodo: Periodo
    cuit_empleador: str | None = None
    empleador: str | None = None
    tipo: TipoAporte = TipoAporte.DESCONOCIDO
    remuneracion_imponible: Decimal = Decimal("0")
    aporte_declarado: Decimal | None = None
    aporte_ingresado: Decimal | None = None
    estado_ingreso: EstadoIngreso = EstadoIngreso.DESCONOCIDO
    servicio_reconocido: bool = False
    observaciones: str = ""

    @property
    def clave_empleador(self) -> str:
        """Identificador estable del empleador para agrupar tramos.

        Sin CUIT, el régimen forma parte de la clave: un afiliado que pasó de
        monotributo a autónomo tiene dos tramos distintos aunque la fuente los
        rotule igual ("Actividad independiente").
        """
        if self.cuit_empleador:
            return self.cuit_empleador
        if self.empleador:
            return f"{self.tipo.value}|nombre:{_normalizar(self.empleador)}"
        return f"tipo:{self.tipo.value}"

    @property
    def nombre_visible(self) -> str:
        return self.empleador or self.cuit_empleador or self.tipo.etiqueta

    @property
    def tiene_remuneracion(self) -> bool:
        return self.remuneracion_imponible > 0

    @property
    def hay_servicio(self) -> bool:
        """El mes registra servicio, con o sin dato de remuneración.

        Los servicios anteriores a 06/94 y los períodos de autónomo se informan
        sin remuneración: son meses de servicio igual, y no computarlos sería
        borrarle antigüedad al afiliado.
        """
        return self.tiene_remuneracion or self.servicio_reconocido


@dataclass
class HistoriaLaboral:
    """Historia laboral completa de un afiliado, tal como la devuelve ANSES."""

    cuil: str
    registros: list[RegistroMensual] = field(default_factory=list)
    nombre: str | None = None
    fecha_consulta: str | None = None
    fuente: str = "desconocida"
    advertencias_origen: list[str] = field(default_factory=list)
    # Línea de servicios tal como la declara la fuente (el RESUMEN del HLAB),
    # para contrastarla con la que calcula el sistema.
    tramos_declarados: list = field(default_factory=list)

    def __post_init__(self) -> None:
        self.cuil = normalizar_cuil(self.cuil)
        self.registros = sorted(
            self.registros, key=lambda r: (r.periodo.ordinal, r.clave_empleador)
        )

    def __len__(self) -> int:
        return len(self.registros)

    @property
    def periodo_inicial(self) -> Periodo | None:
        return self.registros[0].periodo if self.registros else None

    @property
    def periodo_final(self) -> Periodo | None:
        return self.registros[-1].periodo if self.registros else None

    def por_empleador(self) -> dict[str, list[RegistroMensual]]:
        agrupado: dict[str, list[RegistroMensual]] = {}
        for registro in self.registros:
            agrupado.setdefault(registro.clave_empleador, []).append(registro)
        return agrupado

    def periodos_unicos(self) -> set[Periodo]:
        """Meses distintos con actividad, sin importar cuántos empleadores."""
        return {r.periodo for r in self.registros}


@dataclass(frozen=True)
class TramoServicio:
    """Un tramo continuo de servicios con un mismo empleador/régimen."""

    empleador: str
    cuit_empleador: str | None
    tipo: TipoAporte
    inicio: Periodo
    fin: Periodo
    meses_declarados: int
    meses_con_remuneracion: int
    meses_sin_aporte_ingresado: int
    meses_bajo_minimo: int
    remuneracion_total: Decimal

    @property
    def meses_calendario(self) -> int:
        """Extensión del tramo, incluyendo meses sin declaración interna."""
        return self.fin.ordinal - self.inicio.ordinal + 1

    @property
    def meses_faltantes(self) -> int:
        return self.meses_calendario - self.meses_declarados

    @property
    def continuo(self) -> bool:
        return self.meses_faltantes == 0


@dataclass(frozen=True)
class Hallazgo:
    """Observación detectada por el validador."""

    codigo: str
    severidad: Severidad
    mensaje: str
    periodo: Periodo | None = None
    periodo_fin: Periodo | None = None
    empleador: str | None = None
    detalle: dict[str, str] = field(default_factory=dict)

    @property
    def rango_texto(self) -> str:
        if self.periodo is None:
            return "—"
        if self.periodo_fin and self.periodo_fin != self.periodo:
            return f"{self.periodo} a {self.periodo_fin}"
        return str(self.periodo)


# --------------------------------------------------------------------- CUIL

_RE_NO_DIGITOS = re.compile(r"\D")


def normalizar_cuil(cuil: str) -> str:
    """Deja el CUIL en 11 dígitos sin guiones. No valida el dígito verificador."""
    if cuil is None:
        raise ValueError("CUIL vacío")
    limpio = _RE_NO_DIGITOS.sub("", str(cuil))
    if len(limpio) != 11:
        raise ValueError(f"El CUIL debe tener 11 dígitos, recibí {len(limpio)}")
    return limpio


def formatear_cuil(cuil: str) -> str:
    limpio = normalizar_cuil(cuil)
    return f"{limpio[:2]}-{limpio[2:10]}-{limpio[10:]}"


def cuil_valido(cuil: str) -> bool:
    """Verifica el dígito verificador (módulo 11) del CUIL/CUIT."""
    try:
        limpio = normalizar_cuil(cuil)
    except ValueError:
        return False
    pesos = (5, 4, 3, 2, 7, 6, 5, 4, 3, 2)
    suma = sum(int(d) * p for d, p in zip(limpio[:10], pesos))
    resto = suma % 11
    verificador = 11 - resto
    if verificador == 11:
        verificador = 0
    elif verificador == 10:
        verificador = 9
    return verificador == int(limpio[10])


# ---------------------------------------------------------------- auxiliares

_RE_ESPACIOS = re.compile(r"\s+")
_TILDES = str.maketrans("áéíóúÁÉÍÓÚüÜñÑ", "aeiouAEIOUuUnN")


def _normalizar(texto: str) -> str:
    return _RE_ESPACIOS.sub(" ", texto.translate(_TILDES).strip().lower())
