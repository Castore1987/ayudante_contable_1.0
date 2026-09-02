"""Utilidades de formato compartidas por los reportes."""

from __future__ import annotations

from decimal import Decimal
from typing import Sequence

__all__ = ["moneda", "tabla", "titulo", "ICONOS", "truncar"]

ICONOS = {"error": "✗", "advertencia": "!", "informacion": "·"}


def moneda(valor: Decimal | None) -> str:
    """Formato argentino: separador de miles con punto, decimales con coma."""
    if valor is None:
        return "—"
    texto = f"{valor:,.2f}"
    return "$ " + texto.replace(",", "@").replace(".", ",").replace("@", ".")


def truncar(texto: str, ancho: int) -> str:
    texto = str(texto)
    return texto if len(texto) <= ancho else texto[: ancho - 1] + "…"


def titulo(texto: str, ancho: int = 78, caracter: str = "═") -> str:
    return f"\n{texto}\n{caracter * min(ancho, max(len(texto), 12))}"


def tabla(
    encabezados: Sequence[str],
    filas: Sequence[Sequence[str]],
    alineacion: Sequence[str] | None = None,
    ancho_maximo: int = 34,
) -> str:
    """Tabla de texto plano, sin dependencias externas."""
    if not filas:
        return "  (sin datos)"

    columnas = len(encabezados)
    alineacion = list(alineacion or ["<"] * columnas)
    normalizadas = [
        [truncar(str(celda), ancho_maximo) for celda in fila] for fila in filas
    ]
    anchos = [
        max(len(str(encabezados[i])), *(len(fila[i]) for fila in normalizadas))
        for i in range(columnas)
    ]

    def linea(celdas: Sequence[str]) -> str:
        return "  " + "  ".join(
            f"{celda:{alineacion[i]}{anchos[i]}}" for i, celda in enumerate(celdas)
        )

    separador = "  " + "  ".join("─" * ancho for ancho in anchos)
    return "\n".join([linea(encabezados), separador, *(linea(fila) for fila in normalizadas)])
