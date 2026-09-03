"""Informe HTML autocontenido, pensado para imprimir o mandar al cliente."""

from __future__ import annotations

from html import escape
from pathlib import Path

from ..analisis.validador import Informe
from ..modelo.dominio import Severidad, formatear_cuil
from .formato import moneda

__all__ = ["renderizar_html", "exportar_html"]

_ESTILOS = """
:root { color-scheme: light; }
* { box-sizing: border-box; }
body { margin: 0; padding: 2rem 1.25rem 4rem; background: #f4f5f7; color: #1c1e21;
       font: 15px/1.55 -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }
main { max-width: 1080px; margin: 0 auto; background: #fff; padding: 2.5rem;
       border-radius: 10px; box-shadow: 0 1px 3px rgba(0,0,0,.09); }
h1 { font-size: 1.5rem; margin: 0 0 .35rem; letter-spacing: -.01em; }
h2 { font-size: 1.05rem; margin: 2.4rem 0 .75rem; padding-bottom: .4rem;
     border-bottom: 2px solid #e6e8eb; text-transform: uppercase;
     letter-spacing: .06em; color: #444a52; }
.sub { color: #6b7280; margin: 0 0 1.5rem; font-size: .9rem; }
dl.ficha { display: grid; grid-template-columns: max-content 1fr; gap: .35rem 1.25rem;
           margin: 0 0 1rem; font-size: .92rem; }
dl.ficha dt { color: #6b7280; }
dl.ficha dd { margin: 0; font-variant-numeric: tabular-nums; }
.tarjetas { display: grid; gap: .75rem; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); }
.tarjeta { border: 1px solid #e6e8eb; border-radius: 8px; padding: .85rem 1rem; }
.tarjeta .valor { font-size: 1.5rem; font-weight: 600; font-variant-numeric: tabular-nums; }
.tarjeta .rotulo { font-size: .78rem; color: #6b7280; text-transform: uppercase;
                   letter-spacing: .05em; }
.tabla-envoltorio { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; font-size: .88rem; }
th, td { padding: .5rem .65rem; text-align: left; border-bottom: 1px solid #eceef1; }
th { background: #f7f8fa; font-weight: 600; white-space: nowrap; }
td.num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
tr:last-child td { border-bottom: none; }
.pill { display: inline-block; padding: .1rem .5rem; border-radius: 999px;
        font-size: .75rem; font-weight: 600; }
.error { background: #fdecea; color: #9b1c1c; }
.advertencia { background: #fef3c7; color: #8a5a00; }
.informacion { background: #e8f0fe; color: #1a4b8c; }
.aviso { border-left: 4px solid #d9a300; background: #fffbeb; padding: .9rem 1.1rem;
         border-radius: 0 6px 6px 0; margin: 1.25rem 0; font-size: .9rem; }
.pie { margin-top: 2.5rem; padding-top: 1.25rem; border-top: 1px solid #e6e8eb;
       color: #6b7280; font-size: .82rem; }
@media print { body { background: #fff; padding: 0; }
                main { box-shadow: none; padding: 0; } }
"""


def _tarjeta(valor: object, rotulo: str) -> str:
    return (
        f'<div class="tarjeta"><div class="valor">{escape(str(valor))}</div>'
        f'<div class="rotulo">{escape(rotulo)}</div></div>'
    )


def _tabla(encabezados: list[str], filas: list[list[str]], numericas: set[int]) -> str:
    if not filas:
        return "<p><em>Sin datos.</em></p>"
    cabecera = "".join(f"<th>{escape(h)}</th>" for h in encabezados)
    cuerpo = "".join(
        "<tr>"
        + "".join(
            f'<td class="num">{celda}</td>' if i in numericas else f"<td>{celda}</td>"
            for i, celda in enumerate(fila)
        )
        + "</tr>"
        for fila in filas
    )
    return (
        f'<div class="tabla-envoltorio"><table><thead><tr>{cabecera}</tr></thead>'
        f"<tbody>{cuerpo}</tbody></table></div>"
    )


def renderizar_html(informe: Informe) -> str:
    historia, linea = informe.historia, informe.linea

    ficha = [("CUIL", formatear_cuil(historia.cuil))]
    if historia.nombre:
        ficha.append(("Afiliado", historia.nombre))
    ficha += [
        ("Fuente de datos", historia.fuente),
        ("Tabla de parámetros", informe.parametros_origen or "(no informada)"),
        ("Períodos analizados", str(len(historia.registros))),
    ]
    ficha_html = "".join(
        f"<dt>{escape(k)}</dt><dd>{escape(v)}</dd>" for k, v in ficha
    )

    tarjetas = "".join(
        [
            _tarjeta(linea.meses_computables, "Meses computables"),
            _tarjeta(linea.antiguedad_texto, "Antigüedad"),
            _tarjeta(linea.meses_descartados, "Meses descartados"),
            _tarjeta(linea.meses_laguna, "Meses de laguna"),
            _tarjeta(len(informe.errores), "Errores"),
            _tarjeta(len(informe.advertencias), "Advertencias"),
        ]
    )

    filas_tramos = [
        [
            escape(t.empleador),
            escape(t.cuit_empleador or "—"),
            escape(t.tipo.etiqueta),
            escape(str(t.inicio)),
            escape(str(t.fin)),
            str(t.meses_declarados),
            f"<strong>{t.meses_computables}</strong>",
            escape(t.antiguedad_texto),
            str(t.meses_bajo_minimo),
            str(t.meses_sin_aporte_ingresado),
            escape(moneda(t.remuneracion_total)),
        ]
        for t in linea.tramos
    ]
    tabla_tramos = _tabla(
        [
            "Empleador",
            "CUIT",
            "Régimen",
            "Inicio",
            "Fin",
            "Declarados",
            "Válidos",
            "Antigüedad",
            "Bajo mínimo",
            "Sin ingresar",
            "Remuneración total",
        ],
        filas_tramos,
        {3, 4, 5, 6, 7, 8, 9, 10},
    )

    tabla_consolidado = _tabla(
        ["Desde", "Hasta", "Meses", "Empleadores"],
        [
            [
                escape(str(i.inicio)),
                escape(str(i.fin)),
                str(i.meses),
                escape(", ".join(i.empleadores) or "—"),
            ]
            for i in linea.consolidado
        ],
        {0, 1, 2},
    )

    tabla_lagunas = _tabla(
        ["Desde", "Hasta", "Meses"],
        [[escape(str(l.inicio)), escape(str(l.fin)), str(l.meses)] for l in linea.lagunas],
        {0, 1, 2},
    )

    tabla_hallazgos = _tabla(
        ["Severidad", "Código", "Período", "Empleador", "Observación"],
        [
            [
                f'<span class="pill {h.severidad.value}">{escape(h.severidad.value)}</span>',
                escape(h.codigo),
                escape(h.rango_texto),
                escape(h.empleador or "—"),
                escape(h.mensaje),
            ]
            for h in informe.hallazgos
        ],
        {2},
    )

    avisos = []
    if informe.errores:
        avisos.append(
            f"Se detectaron {len(informe.errores)} hallazgo(s) de nivel ERROR. "
            "Revisalos antes de presentar cualquier trámite."
        )
    if any(h.codigo.startswith("PARAMETROS") for h in informe.hallazgos):
        avisos.append(
            "La tabla de base imponible mínima está incompleta o sin verificar: "
            "los controles de mínimo pueden no cubrir todo el período analizado."
        )
    avisos_html = "".join(f'<div class="aviso">{escape(a)}</div>' for a in avisos)

    veredicto = (
        "Historia laboral con inconsistencias a reclamar."
        if informe.errores
        else "Sin inconsistencias de nivel error sobre los datos analizados."
    )

    return f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Informe previsional — {escape(formatear_cuil(historia.cuil))}</title>
<style>{_ESTILOS}</style>
</head>
<body>
<main>
  <h1>Informe previsional — Historia laboral</h1>
  <p class="sub">{escape(veredicto)}</p>
  <dl class="ficha">{ficha_html}</dl>
  {avisos_html}

  <h2>Resumen</h2>
  <div class="tarjetas">{tarjetas}</div>

  <h2>Línea de servicios por empleador</h2>
  {tabla_tramos}

  <h2>Servicios consolidados</h2>
  {tabla_consolidado}

  <h2>Lagunas</h2>
  {tabla_lagunas}

  <h2>Hallazgos</h2>
  {tabla_hallazgos}

  <p class="pie">
    Informe generado automáticamente sobre los datos entregados por la fuente
    indicada. Es una ayuda de control: no reemplaza la certificación de servicios
    ni el criterio profesional. Verificá cada hallazgo contra la documentación
    respaldatoria antes de usarlo en un trámite.
  </p>
</main>
</body>
</html>
"""


def exportar_html(informe: Informe, ruta: str | Path) -> Path:
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(renderizar_html(informe), encoding="utf-8")
    return ruta
