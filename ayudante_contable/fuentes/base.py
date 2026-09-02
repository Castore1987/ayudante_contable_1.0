"""Contrato común de las fuentes de historia laboral."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..modelo.dominio import HistoriaLaboral

__all__ = ["FuenteHistoriaLaboral", "ErrorFuente", "CredencialesANSES"]


class ErrorFuente(Exception):
    """No se pudo obtener la historia laboral desde la fuente."""


@runtime_checkable
class FuenteHistoriaLaboral(Protocol):
    """Cualquier origen de datos capaz de devolver una historia laboral.

    La capa de análisis no sabe si los datos vinieron de la web de ANSES, de un
    PDF descargado a mano o de una planilla: eso permite trabajar sin tocar el
    portal cuando no hace falta.
    """

    nombre: str

    def obtener(self, cuil: str) -> HistoriaLaboral:  # pragma: no cover - protocolo
        ...


class CredencialesANSES:
    """CUIL + Clave de la Seguridad Social, con cuidado de no filtrarla.

    La clave se guarda en memoria y se borra al salir del contexto. ``repr`` y
    ``str`` nunca la exponen, para que no aparezca en un traceback, en un log
    ni en un ``print`` de depuración.
    """

    __slots__ = ("cuil", "_clave")

    def __init__(self, cuil: str, clave: str) -> None:
        from ..modelo.dominio import normalizar_cuil

        self.cuil = normalizar_cuil(cuil)
        self._clave = clave

    @property
    def clave(self) -> str:
        if self._clave is None:
            raise ErrorFuente("Las credenciales ya fueron descartadas de memoria.")
        return self._clave

    def descartar(self) -> None:
        self._clave = None

    def __enter__(self) -> "CredencialesANSES":
        return self

    def __exit__(self, *_excepcion) -> None:
        self.descartar()

    def __repr__(self) -> str:
        return f"CredencialesANSES(cuil={self.cuil[:2]}…{self.cuil[-1]}, clave=<oculta>)"

    __str__ = __repr__
