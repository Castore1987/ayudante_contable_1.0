"""Registro de auditoría: qué se consultó, cuándo y con qué resultado.

Trabajar con credenciales de terceros exige poder responder después "quién miró
qué cuenta y cuándo". El registro es append-only, en JSON Lines, y nunca guarda
la clave: solo el CUIL enmascarado.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .redaccion import enmascarar_cuil, redactar

__all__ = ["RegistroAuditoria", "EventoAuditoria"]


@dataclass(frozen=True)
class EventoAuditoria:
    momento: str
    accion: str
    cuil_enmascarado: str
    resultado: str
    detalle: dict[str, Any]

    def a_json(self) -> str:
        return json.dumps(
            {
                "momento": self.momento,
                "accion": self.accion,
                "cuil": self.cuil_enmascarado,
                "resultado": self.resultado,
                "detalle": self.detalle,
                "operador": os.environ.get("AYUDANTE_OPERADOR", os.environ.get("USER", "?")),
            },
            ensure_ascii=False,
        )


class RegistroAuditoria:
    """Escribe eventos en un archivo JSONL con permisos restringidos."""

    def __init__(self, ruta: str | Path) -> None:
        self.ruta = Path(ruta)
        self.ruta.parent.mkdir(parents=True, exist_ok=True)

    def registrar(
        self,
        accion: str,
        cuil: str = "",
        resultado: str = "ok",
        **detalle: Any,
    ) -> EventoAuditoria:
        evento = EventoAuditoria(
            momento=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            accion=accion,
            cuil_enmascarado=enmascarar_cuil(str(cuil)) if cuil else "",
            resultado=resultado,
            detalle={k: redactar(v) for k, v in detalle.items()},
        )
        nuevo = not self.ruta.exists()
        with self.ruta.open("a", encoding="utf-8") as archivo:
            archivo.write(evento.a_json() + "\n")
        if nuevo:
            os.chmod(self.ruta, 0o600)
        return evento

    def leer(self, limite: int | None = None) -> list[dict[str, Any]]:
        if not self.ruta.exists():
            return []
        lineas = self.ruta.read_text(encoding="utf-8").splitlines()
        if limite:
            lineas = lineas[-limite:]
        return [json.loads(l) for l in lineas if l.strip()]
