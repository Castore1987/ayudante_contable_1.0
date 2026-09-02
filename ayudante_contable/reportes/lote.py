"""Reportes del procesamiento por lote: consola, CSV índice y HTML índice."""

from __future__ import annotations

import csv
from html import escape
from pathlib import Path

from ..lote import ResumenLote
from .formato import tabla, titulo

__all__ = ["renderizar_lote", "imprimir_lote", "exportar_indice_csv", "exportar_indice_html"]


def renderizar_lote(resumen: ResumenLote) -> str:
    conteo = resumen.conteo
    partes = [
        titulo("RESUMEN DEL LOTE", caracter="═"),
        f"  Expedientes procesados   {conteo['total']}",
        f"  En orden                 {conteo['en_orden']}",
        f"  Con errores              {conteo['con_errores']}",
        f"  No procesados            {conteo['no_procesados']}",
        f"  Parámetros               {resumen.parametros_origen}",
        f"  Duración                 {resumen.segundos:.1f} s",
    ]

    filas = []
    for resultado in resumen.resultados:
        informe = resultado.informe
        filas.append(
            [
                resultado.cliente.cuil_legible,
                resultado.cliente.nombre or "—",
                resultado.estado,
                str(informe.linea.meses_computables) if informe else "—",
                str(len(informe.errores)) if informe else "—",
                str(len(informe.advertencias)) if informe else "—",
                resultado.error or "",
            ]
        )

    partes += [
        titulo("EXPEDIENTES", caracter="─"),
        tabla(
            ["CUIL", "Afiliado", "Estado", "Meses", "Err.", "Adv.", "Detalle"],
            filas,
            ["<", "<", "<", ">", ">", ">", "<"],
            ancho_maximo=40,
        ),
    ]

    frecuentes = resumen.hallazgos_frecuentes()
    if frecuentes:
        partes += [
            titulo("HALLAZGOS MÁS FRECUENTES", caracter="─"),
            tabla(
                ["Código", "Expedientes"],
                [[codigo, str(cantidad)] for codigo, cantidad in frecuentes],
                ["<", ">"],
            ),
        ]

    if resumen.fallidos:
        partes.append(titulo("NO PROCESADOS", caracter="─"))
        for resultado in resumen.fallidos:
            partes.append(f"  ✗ {resultado.cliente.etiqueta}")
            partes.append(f"      {resultado.error}")
        partes.append(
            "\n  Estos expedientes NO fueron analizados: no cuentan como 'en orden'."
        )

    return "\n".join(partes) + "\n"


def imprimir_lote(resumen: ResumenLote) -> None:
    print(renderizar_lote(resumen))


def exportar_indice_csv(resumen: ResumenLote, ruta: str | Path) -> Path:
    """Índice del lote, para pegar en la planilla de seguimiento del estudio."""
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("w", encoding="utf-8-sig", newline="") as archivo:
        escritor = csv.writer(archivo, delimiter=";")
        escritor.writerow(
            [
                "cuil",
                "afiliado",
                "estado",
                "meses_computables",
                "antiguedad",
                "meses_descartados",
                "meses_laguna",
                "tramos",
                "errores",
                "advertencias",
                "codigos_error",
                "detalle",
            ]
        )
        for resultado in resumen.resultados:
            informe = resultado.informe
            if informe is None:
                escritor.writerow(
                    [
                        resultado.cliente.cuil_legible,
                        resultado.cliente.nombre or "",
                        resultado.estado,
                        "", "", "", "", "", "", "", "",
                        resultado.error or "",
                    ]
                )
                continue
            escritor.writerow(
                [
                    resultado.cliente.cuil_legible,
                    resultado.cliente.nombre or "",
                    resultado.estado,
                    informe.linea.meses_computables,
                    informe.linea.antiguedad_texto,
                    informe.linea.meses_descartados,
                    informe.linea.meses_laguna,
                    len(informe.linea.tramos),
                    len(informe.errores),
                    len(informe.advertencias),
                    " ".join(sorted({h.codigo for h in informe.errores})),
                    "",
                ]
            )
    return ruta


_ESTILOS_INDICE = """
:root { color-scheme: light; }
body { margin: 0; padding: 2rem 1.25rem 4rem; background: #f4f5f7; color: #1c1e21;
       font: 15px/1.55 -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }
main { max-width: 1080px; margin: 0 auto; background: #fff; padding: 2.5rem;
       border-radius: 10px; box-shadow: 0 1px 3px rgba(0,0,0,.09); }
h1 { font-size: 1.5rem; margin: 0 0 1.5rem; }
.tarjetas { display: grid; gap: .75rem; margin-bottom: 2rem;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); }
.tarjeta { border: 1px solid #e6e8eb; border-radius: 8px; padding: .85rem 1rem; }
.tarjeta .valor { font-size: 1.6rem; font-weight: 600; }
.tarjeta .rotulo { font-size: .78rem; color: #6b7280; text-transform: uppercase;
                   letter-spacing: .05em; }
table { border-collapse: collapse; width: 100%; font-size: .88rem; }
th, td { padding: .5rem .65rem; text-align: left; border-bottom: 1px solid #eceef1; }
th { background: #f7f8fa; font-weight: 600; }
td.num { text-align: right; font-variant-numeric: tabular-nums; }
a { color: #1a4b8c; }
.pill { display: inline-block; padding: .1rem .5rem; border-radius: 999px;
        font-size: .75rem; font-weight: 600; white-space: nowrap; }
.orden { background: #e6f4ea; color: #1c6b34; }
.errores { background: #fdecea; color: #9b1c1c; }
.falla { background: #fef3c7; color: #8a5a00; }
.pie { margin-top: 2rem; padding-top: 1.25rem; border-top: 1px solid #e6e8eb;
       color: #6b7280; font-size: .82rem; }
"""

_CLASES = {"en orden": "orden", "con errores": "errores", "no procesado": "falla"}


def exportar_indice_html(resumen: ResumenLote, ruta: str | Path) -> Path:
    """Índice navegable del lote, con enlace al informe de cada expediente."""
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    conteo = resumen.conteo

    tarjetas = "".join(
        f'<div class="tarjeta"><div class="valor">{valor}</div>'
        f'<div class="rotulo">{escape(rotulo)}</div></div>'
        for valor, rotulo in (
            (conteo["total"], "Expedientes"),
            (conteo["en_orden"], "En orden"),
            (conteo["con_errores"], "Con errores"),
            (conteo["no_procesados"], "No procesados"),
        )
    )

    filas = []
    for resultado in resumen.resultados:
        informe = resultado.informe
        enlace = next(
            (a for a in resultado.archivos if a.suffix == ".html"), None
        )
        nombre = escape(resultado.cliente.nombre or "—")
        celda_nombre = (
            f'<a href="{escape(enlace.name)}">{nombre}</a>' if enlace else nombre
        )
        filas.append(
            "<tr>"
            f"<td>{escape(resultado.cliente.cuil_legible)}</td>"
            f"<td>{celda_nombre}</td>"
            f'<td><span class="pill {_CLASES[resultado.estado]}">'
            f"{escape(resultado.estado)}</span></td>"
            f'<td class="num">{informe.linea.meses_computables if informe else "—"}</td>'
            f'<td class="num">{len(informe.errores) if informe else "—"}</td>'
            f'<td class="num">{len(informe.advertencias) if informe else "—"}</td>'
            f"<td>{escape(resultado.error or '')}</td>"
            "</tr>"
        )

    return _escribir_html(
        ruta,
        f"""<!doctype html>
<html lang="es">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Lote previsional — {conteo['total']} expedientes</title>
<style>{_ESTILOS_INDICE}</style></head>
<body><main>
<h1>Procesamiento por lote</h1>
<div class="tarjetas">{tarjetas}</div>
<table><thead><tr><th>CUIL</th><th>Afiliado</th><th>Estado</th><th>Meses</th>
<th>Errores</th><th>Advertencias</th><th>Detalle</th></tr></thead>
<tbody>{''.join(filas)}</tbody></table>
<p class="pie">Parámetros: {escape(resumen.parametros_origen)} · Duración:
{resumen.segundos:.1f} s. Los expedientes marcados «no procesado» no fueron
analizados y no deben contarse como en orden.</p>
</main></body></html>
""",
    )


def _escribir_html(ruta: Path, contenido: str) -> Path:
    ruta.write_text(contenido, encoding="utf-8")
    return ruta
