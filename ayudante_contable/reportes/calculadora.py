"""Exportación al formato de la «Calculadora de Aportes».

La calculadora guarda un JSON por cliente y lo abre con «Abrir Historial».
Este módulo escribe ese JSON con los períodos válidos ya cargados, para no
tipearlos de a uno en la interfaz.

Dos detalles del formato que definen la conversión:

* La calculadora trabaja **con precisión de día** (``DD/MM/AAAA``) y cuenta
  ``(fin - inicio).days + 1``. Los períodos previsionales son mensuales, así
  que cada tramo se abre el día 1 del mes inicial y se cierra el último día
  del mes final.
* Sus períodos de autónomo y monotributo admiten **deudas**, que la
  calculadora resta del bruto. Acá los tramos ya vienen netos —solo los meses
  que computan— así que la lista de deudas va vacía a propósito: restar dos
  veces lo mismo bajaría el cómputo sin motivo.
"""

from __future__ import annotations

import calendar
import json
from pathlib import Path

from ..analisis.validador import Informe
from ..modelo.dominio import Periodo, TipoAporte, formatear_cuil

__all__ = ["exportar_calculadora", "historial_calculadora"]

# La calculadora separa caja nacional de provincial. Todo lo que sale de ANSES,
# ARCA y SICAM es nacional; lo provincial se carga aparte en la propia app.
ES_PROVINCIAL = False


def _primer_dia(periodo: Periodo) -> str:
    return f"01/{periodo.mes:02d}/{periodo.anio}"


def _ultimo_dia(periodo: Periodo) -> str:
    dia = calendar.monthrange(periodo.anio, periodo.mes)[1]
    return f"{dia:02d}/{periodo.mes:02d}/{periodo.anio}"


def _es_dependencia(etiqueta: str, informe: Informe) -> bool:
    """¿El tramo es relación de dependencia o trabajo independiente?"""
    for evaluacion in informe.evaluaciones:
        registro = evaluacion.registro
        if registro.nombre_visible == etiqueta:
            return registro.tipo not in (TipoAporte.AUTONOMO, TipoAporte.MONOTRIBUTO)
    return False


def historial_calculadora(informe: Informe) -> dict:
    """Arma el diccionario que la calculadora espera en su archivo de sesión."""
    dependencia: list[dict] = []
    autonomos: list[dict] = []

    for tramo in informe.linea.tramos_validos:
        entrada = {
            "inicio": _primer_dia(tramo.inicio),
            "fin": _ultimo_dia(tramo.fin),
            "es_provincial": ES_PROVINCIAL,
        }
        if _es_dependencia(tramo.etiqueta, informe):
            dependencia.append(
                {
                    "empleador": tramo.etiqueta,
                    "ingreso": entrada["inicio"],
                    "egreso": entrada["fin"],
                    "es_provincial": ES_PROVINCIAL,
                }
            )
        else:
            autonomos.append(
                {
                    "descripcion": tramo.etiqueta,
                    "inicio": entrada["inicio"],
                    "fin": entrada["fin"],
                    "deudas": [],
                    "es_provincial": ES_PROVINCIAL,
                }
            )

    nombre = informe.historia.nombre or formatear_cuil(informe.historia.cuil)
    return {
        "metadata": {
            "nombre": nombre,
            # La calculadora necesita estos datos para el cómputo del exceso de
            # edad (2x1). No salen de la historia laboral: los carga el estudio.
            "fecha_nacimiento": "",
            "edad_req_anios": "",
            "edad_req_meses": "",
            "edad_req_dias": "",
            "fecha_corte": "",
        },
        "relacion_dependencia": dependencia,
        "autonomos": autonomos,
        "monotributo": [],
    }


def exportar_calculadora(informe: Informe, ruta: str | Path) -> Path:
    """Escribe el JSON de sesión de la calculadora con los períodos válidos."""
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(
        json.dumps(historial_calculadora(informe), indent=4, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return ruta
