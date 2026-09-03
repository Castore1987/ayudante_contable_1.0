"""Exportación del informe a archivos: CSV para planilla, JSON para integrar."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from ..analisis.validador import Informe
from ..modelo.dominio import formatear_cuil

__all__ = ["exportar_linea_servicios", "exportar_hallazgos", "exportar_detalle", "exportar_json"]


def _escribir(ruta: Path, encabezados: list[str], filas: list[list[str]]) -> Path:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("w", encoding="utf-8-sig", newline="") as archivo:
        escritor = csv.writer(archivo, delimiter=";")
        escritor.writerow(encabezados)
        escritor.writerows(filas)
    return ruta


def exportar_linea_servicios(informe: Informe, ruta: str | Path) -> Path:
    """Tramos con fecha de inicio y fin, listos para volcar al formulario."""
    filas = [
        [
            tramo.empleador,
            tramo.cuit_empleador or "",
            tramo.tipo.etiqueta,
            str(tramo.inicio),
            str(tramo.fin),
            tramo.meses_declarados,
            tramo.meses_computables,
            tramo.antiguedad_texto,
            tramo.meses_calendario,
            tramo.meses_con_remuneracion,
            tramo.meses_bajo_minimo,
            tramo.meses_sin_aporte_ingresado,
            f"{tramo.remuneracion_total:.2f}",
        ]
        for tramo in informe.linea.tramos
    ]
    return _escribir(
        Path(ruta),
        [
            "empleador",
            "cuit",
            "regimen",
            "inicio",
            "fin",
            "meses_declarados",
            "meses_validos",
            "antiguedad_tramo",
            "meses_calendario",
            "meses_con_remuneracion",
            "meses_bajo_minimo",
            "meses_sin_aporte_ingresado",
            "remuneracion_total",
        ],
        filas,
    )


def exportar_hallazgos(informe: Informe, ruta: str | Path) -> Path:
    filas = [
        [
            hallazgo.severidad.value,
            hallazgo.codigo,
            str(hallazgo.periodo) if hallazgo.periodo else "",
            str(hallazgo.periodo_fin) if hallazgo.periodo_fin else "",
            hallazgo.empleador or "",
            hallazgo.mensaje,
        ]
        for hallazgo in informe.hallazgos
    ]
    return _escribir(
        Path(ruta), ["severidad", "codigo", "desde", "hasta", "empleador", "mensaje"], filas
    )


def exportar_detalle(informe: Informe, ruta: str | Path) -> Path:
    """Detalle mes a mes con el juicio aplicado a cada período."""
    filas = []
    for evaluacion in informe.evaluaciones:
        registro = evaluacion.registro
        filas.append(
            [
                str(registro.periodo),
                registro.cuit_empleador or "",
                registro.nombre_visible,
                registro.tipo.etiqueta,
                f"{registro.remuneracion_imponible:.2f}",
                f"{evaluacion.base_minima.valor:.2f}" if evaluacion.base_minima else "",
                "si" if evaluacion.bajo_minimo else "no",
                f"{evaluacion.faltante_base:.2f}" if evaluacion.bajo_minimo else "",
                f"{registro.aporte_declarado:.2f}" if registro.aporte_declarado is not None else "",
                f"{evaluacion.aporte_esperado:.2f}" if evaluacion.aporte_esperado else "",
                f"{registro.aporte_ingresado:.2f}" if registro.aporte_ingresado is not None else "",
                evaluacion.estado_ingreso.value,
                "si" if evaluacion.computa_servicio else "no",
            ]
        )
    return _escribir(
        Path(ruta),
        [
            "periodo",
            "cuit",
            "empleador",
            "regimen",
            "remuneracion_imponible",
            "base_minima",
            "bajo_minimo",
            "faltante",
            "aporte_declarado",
            "aporte_esperado",
            "aporte_ingresado",
            "estado_ingreso",
            "computa_servicio",
        ],
        filas,
    )


def exportar_json(informe: Informe, ruta: str | Path) -> Path:
    """Informe completo en JSON, para integrarlo con el sistema del estudio."""
    linea = informe.linea
    datos = {
        "cuil": formatear_cuil(informe.historia.cuil),
        "afiliado": informe.historia.nombre,
        "fuente": informe.historia.fuente,
        "parametros": informe.parametros_origen,
        "resumen": informe.resumen,
        "antiguedad": {
            "meses_computables": linea.meses_computables,
            "anios_computables": str(linea.anios_computables),
            "texto": linea.antiguedad_texto,
            "primer_periodo": str(linea.primer_periodo) if linea.primer_periodo else None,
            "ultimo_periodo": str(linea.ultimo_periodo) if linea.ultimo_periodo else None,
        },
        "linea_servicios": [
            {
                "empleador": t.empleador,
                "cuit": t.cuit_empleador,
                "regimen": t.tipo.value,
                "inicio": str(t.inicio),
                "fin": str(t.fin),
                "meses_declarados": t.meses_declarados,
                "meses_validos": t.meses_computables,
                "antiguedad_tramo": t.antiguedad_texto,
                "meses_calendario": t.meses_calendario,
                "meses_bajo_minimo": t.meses_bajo_minimo,
                "meses_sin_aporte_ingresado": t.meses_sin_aporte_ingresado,
                "remuneracion_total": str(t.remuneracion_total),
            }
            for t in linea.tramos
        ],
        "consolidado": [
            {"desde": str(i.inicio), "hasta": str(i.fin), "meses": i.meses}
            for i in linea.consolidado
        ],
        "lagunas": [
            {"desde": str(l.inicio), "hasta": str(l.fin), "meses": l.meses}
            for l in linea.lagunas
        ],
        "hallazgos": [
            {
                "severidad": h.severidad.value,
                "codigo": h.codigo,
                "desde": str(h.periodo) if h.periodo else None,
                "hasta": str(h.periodo_fin) if h.periodo_fin else None,
                "empleador": h.empleador,
                "mensaje": h.mensaje,
            }
            for h in informe.hallazgos
        ],
    }
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(datos, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return ruta
