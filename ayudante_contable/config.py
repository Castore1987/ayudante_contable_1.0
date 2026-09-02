"""Rutas y ajustes del entorno de trabajo del estudio."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

__all__ = ["Configuracion", "VARIABLES_ENTORNO"]

VARIABLES_ENTORNO = {
    "AYUDANTE_DIR": "Carpeta de trabajo (por defecto ~/.ayudante-contable).",
    "AYUDANTE_CLAVE_MAESTRA": "Contraseña maestra de la bóveda, para uso desatendido.",
    "AYUDANTE_PARAMETROS": "Ruta alternativa a la tabla de parámetros previsionales.",
    "AYUDANTE_OPERADOR": "Nombre del operador que queda asentado en la auditoría.",
}


@dataclass(frozen=True)
class Configuracion:
    base: Path

    @classmethod
    def cargar(cls, base: str | Path | None = None) -> "Configuracion":
        raiz = Path(
            base or os.environ.get("AYUDANTE_DIR") or Path.home() / ".ayudante-contable"
        ).expanduser()
        return cls(base=raiz)

    def preparar(self) -> "Configuracion":
        """Crea la estructura de carpetas con permisos restringidos."""
        for carpeta in (self.base, self.descargas, self.informes):
            carpeta.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.base, 0o700)
        except OSError:  # pragma: no cover - sistemas sin permisos POSIX
            pass
        return self

    @property
    def boveda(self) -> Path:
        return self.base / "boveda.json"

    @property
    def auditoria(self) -> Path:
        return self.base / "auditoria.jsonl"

    @property
    def descargas(self) -> Path:
        return self.base / "descargas"

    @property
    def informes(self) -> Path:
        return self.base / "informes"

    @property
    def parametros(self) -> Path:
        from .analisis.parametros import RUTA_PARAMETROS_POR_DEFECTO

        desde_entorno = os.environ.get("AYUDANTE_PARAMETROS")
        if desde_entorno:
            return Path(desde_entorno).expanduser()
        propios = self.base / "parametros_previsionales.json"
        return propios if propios.exists() else RUTA_PARAMETROS_POR_DEFECTO
