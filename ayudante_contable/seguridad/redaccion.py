"""Redacción de datos sensibles antes de que lleguen a un log o a la pantalla.

Una clave de la Seguridad Social filtrada en un traceback es un incidente. Todo
texto que salga del sistema (logs, mensajes de error, capturas) pasa por acá.
"""

from __future__ import annotations

import re

__all__ = ["redactar", "enmascarar_cuil", "registrar_secreto", "limpiar_secretos"]

OCULTO = "«oculto»"

_SECRETOS: set[str] = set()

# Cada patrón deja el valor sensible en el grupo llamado 'valor'.
_PATRONES = (
    re.compile(
        r"(?i)\bclave\s+(?:de\s+)?(?:la\s+)?seguridad\s+social\b\s*[\"']?\s*[:=]\s*"
        r"[\"']?(?P<valor>[^\s\"',;}\]]+)"
    ),
    re.compile(
        r"(?i)\b(?:clave|password|passwd|contrase(?:n|ñ)a|pass|pwd|token|secreto|secret)\b"
        r"\s*[\"']?\s*[:=]\s*[\"']?(?P<valor>[^\s\"',;}\]]+)"
    ),
)

_RE_CUIL = re.compile(r"\b(\d{2})-?(\d{8})-?(\d)\b")


def registrar_secreto(valor: str | None) -> None:
    """Marca un valor concreto para que nunca aparezca en texto redactado."""
    if valor and len(valor) >= 4:
        _SECRETOS.add(valor)


def limpiar_secretos() -> None:
    _SECRETOS.clear()


def enmascarar_cuil(texto: str) -> str:
    """Deja visibles el prefijo y el dígito verificador: ``20-****5678-9``."""
    return _RE_CUIL.sub(lambda m: f"{m.group(1)}-****{m.group(2)[-4:]}-{m.group(3)}", texto)


def _tapar_valor(coincidencia: re.Match[str]) -> str:
    """Reemplaza solo el grupo 'valor', conservando el resto de la coincidencia."""
    completo = coincidencia.group(0)
    desplazamiento = coincidencia.start()
    inicio = coincidencia.start("valor") - desplazamiento
    fin = coincidencia.end("valor") - desplazamiento
    return completo[:inicio] + OCULTO + completo[fin:]


def redactar(texto: object, incluir_cuil: bool = True) -> str:
    """Devuelve el texto con claves y (opcionalmente) CUIL enmascarados."""
    salida = str(texto)

    for secreto in sorted(_SECRETOS, key=len, reverse=True):
        salida = salida.replace(secreto, OCULTO)

    for patron in _PATRONES:
        salida = patron.sub(_tapar_valor, salida)

    if incluir_cuil:
        salida = enmascarar_cuil(salida)
    return salida
