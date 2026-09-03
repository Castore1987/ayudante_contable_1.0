"""Informe en consola: lo que el contador lee antes de tocar un papel."""

from __future__ import annotations

from ..analisis.validador import Informe
from ..modelo.dominio import Severidad, formatear_cuil
from .formato import ICONOS, tabla, titulo

__all__ = ["renderizar", "imprimir"]


def _encabezado(informe: Informe) -> list[str]:
    historia = informe.historia
    lineas = [
        titulo("INFORME PREVISIONAL — HISTORIA LABORAL", caracter="═"),
        f"  CUIL           {formatear_cuil(historia.cuil)}",
    ]
    if historia.nombre:
        lineas.append(f"  Afiliado       {historia.nombre}")
    lineas += [
        f"  Fuente         {historia.fuente}",
        f"  Parámetros     {informe.parametros_origen or '(no informado)'}",
        f"  Períodos       {len(historia.registros)} registros",
    ]
    return lineas


def _resumen(informe: Informe) -> list[str]:
    linea = informe.linea
    filas = [
        ["Meses computables", str(linea.meses_computables), linea.antiguedad_texto],
        ["Años computables", str(linea.anios_computables), ""],
        [
            "Meses con reservas",
            str(linea.meses_con_reservas),
            "computados, pero con ingreso parcial o sin dato",
        ],
        [
            "Meses descartados",
            str(linea.meses_descartados),
            "declarados sin aporte ingresado",
        ],
        ["Meses de laguna", str(linea.meses_laguna), f"{len(linea.lagunas)} tramo(s)"],
        ["Tramos de servicio", str(len(linea.tramos)), ""],
    ]
    return [
        titulo("RESUMEN", caracter="─"),
        tabla(["Concepto", "Valor", "Detalle"], filas, ["<", ">", "<"], ancho_maximo=48),
    ]


def _linea_servicios(informe: Informe) -> list[str]:
    """La línea de servicios: fechas, meses declarados y meses que valen.

    La columna que importa es «Válidos»: los declarados incluyen meses que no
    computan (bajo el mínimo, sin aporte ingresado, prescriptos). Al pie va el
    total consolidado, que no es la suma de la columna porque los meses
    simultáneos se cuentan una sola vez.
    """
    linea = informe.linea
    filas = []
    for tramo in linea.tramos:
        observaciones = []
        if tramo.meses_bajo_minimo:
            observaciones.append(f"{tramo.meses_bajo_minimo} bajo mínimo")
        if tramo.meses_sin_aporte_ingresado:
            observaciones.append(f"{tramo.meses_sin_aporte_ingresado} sin ingresar")
        if tramo.meses_faltantes:
            observaciones.append(f"{tramo.meses_faltantes} sin declarar")
        no_computables = tramo.meses_no_computables
        if no_computables and not observaciones:
            observaciones.append(f"{no_computables} no computan")
        filas.append(
            [
                str(tramo.inicio),
                str(tramo.fin),
                tramo.empleador,
                tramo.cuit_empleador or "—",
                tramo.tipo.etiqueta,
                str(tramo.meses_declarados),
                str(tramo.meses_computables),
                tramo.antiguedad_texto,
                ", ".join(observaciones) or "—",
            ]
        )

    suma_declarados = sum(t.meses_declarados for t in linea.tramos)
    suma_validos = sum(t.meses_computables for t in linea.tramos)
    filas.append(
        [
            "", "", "SUMA DE TRAMOS", "", "",
            str(suma_declarados), str(suma_validos), "", "",
        ]
    )

    salida = [
        titulo("LÍNEA DE SERVICIOS", caracter="─"),
        tabla(
            [
                "Desde", "Hasta", "Empleador / Régimen", "CUIT", "Modalidad",
                "Declar.", "Válidos", "Antigüedad", "Observaciones",
            ],
            filas,
            ["<", "<", "<", "<", "<", ">", ">", ">", "<"],
            ancho_maximo=30,
        ),
    ]

    duplicados = suma_validos - linea.meses_computables
    salida.append("")
    salida.append("  " + "═" * 66)
    salida.append(
        f"  APORTES VÁLIDOS   {linea.meses_computables} meses   "
        f"=   {linea.antiguedad_texto}"
    )
    salida.append("  " + "═" * 66)
    if duplicados > 0:
        salida.append(
            f"  (la suma de tramos da {suma_validos}; {duplicados} mes(es) se "
            "superponen entre regímenes y cuentan una sola vez)"
        )
    return salida


def _consolidado(informe: Informe) -> list[str]:
    filas = [
        [str(i.inicio), str(i.fin), str(i.meses), ", ".join(i.empleadores) or "—"]
        for i in informe.linea.consolidado
    ]
    salida = [
        titulo("SERVICIOS CONSOLIDADOS (meses de calendario, sin duplicar)", caracter="─"),
        tabla(["Desde", "Hasta", "Meses", "Empleadores"], filas, [">", ">", ">", "<"], 44),
    ]

    if informe.linea.lagunas:
        salida += [
            titulo("LAGUNAS", caracter="─"),
            tabla(
                ["Desde", "Hasta", "Meses"],
                [[str(l.inicio), str(l.fin), str(l.meses)] for l in informe.linea.lagunas],
                [">", ">", ">"],
            ),
        ]
    return salida


def _hallazgos(informe: Informe) -> list[str]:
    if not informe.hallazgos:
        return [titulo("HALLAZGOS", caracter="─"), "  Sin observaciones."]

    salida = [titulo("HALLAZGOS", caracter="─")]
    for severidad in (Severidad.ERROR, Severidad.ADVERTENCIA, Severidad.INFORMACION):
        grupo = informe.por_severidad(severidad)
        if not grupo:
            continue
        salida.append(f"\n  {severidad.value.upper()} ({len(grupo)})")
        for hallazgo in grupo:
            salida.append(
                f"  {ICONOS[severidad.value]} [{hallazgo.codigo}] "
                f"{hallazgo.rango_texto}  {hallazgo.mensaje}"
            )
    return salida


def _cierre(informe: Informe) -> list[str]:
    if informe.errores:
        veredicto = (
            f"{len(informe.errores)} hallazgo(s) de nivel ERROR: la historia laboral "
            "tiene inconsistencias que hay que reclamar antes de presentar."
        )
    elif informe.advertencias:
        veredicto = (
            f"Sin errores. {len(informe.advertencias)} advertencia(s) para revisar "
            "con el cliente."
        )
    else:
        veredicto = "Sin errores ni advertencias sobre los datos analizados."

    return [
        titulo("CONCLUSIÓN", caracter="═"),
        f"  {veredicto}",
        "",
        "  Este informe es una ayuda de control sobre los datos que entregó la",
        "  fuente. No reemplaza la certificación de servicios ni el criterio",
        "  profesional: verificá los hallazgos contra la documentación respaldatoria.",
    ]


def renderizar(informe: Informe) -> str:
    partes: list[str] = []
    partes += _encabezado(informe)
    partes += _resumen(informe)
    partes += _linea_servicios(informe)
    partes += _consolidado(informe)
    partes += _hallazgos(informe)
    partes += _cierre(informe)
    return "\n".join(partes) + "\n"


def imprimir(informe: Informe) -> None:
    print(renderizar(informe))
