"""Ayudante contable previsional para historias laborales de ANSES.

Automatiza el control mecánico y repetitivo de una historia laboral:

* verifica que la remuneración imponible alcance la base mínima de cada período;
* verifica que los aportes declarados hayan ingresado efectivamente;
* arma la línea de servicios con fecha de inicio y fin por empleador;
* consolida la antigüedad sin computar dos veces los empleos simultáneos.

El criterio profesional sigue siendo del contador: esto ordena los datos y
señala lo que no cierra.
"""

from __future__ import annotations

__version__ = "1.0.0"

from .analisis.parametros import ParametrosPrevisionales
from .analisis.validador import Informe, analizar
from .modelo.dominio import HistoriaLaboral, Periodo, RegistroMensual

__all__ = [
    "__version__",
    "ParametrosPrevisionales",
    "Informe",
    "analizar",
    "HistoriaLaboral",
    "Periodo",
    "RegistroMensual",
]
