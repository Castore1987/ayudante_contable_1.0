"""Interfaz de línea de comandos del ayudante contable.

Códigos de salida, pensados para encadenar en scripts del estudio:

* ``0`` — el análisis corrió y no encontró hallazgos de nivel error.
* ``1`` — el análisis corrió y encontró errores en la historia laboral.
* ``2`` — el comando no se pudo ejecutar (archivo faltante, credenciales, etc.).
"""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

from .analisis.parametros import ErrorParametros, ParametrosPrevisionales
from .analisis.validador import Informe, analizar
from .config import VARIABLES_ENTORNO, Configuracion
from .fuentes.base import CredencialesANSES, ErrorFuente
from .lote import ErrorLote
from .modelo.dominio import formatear_cuil, normalizar_cuil
from .reportes import calculadora, consola, exportar, html
from .seguridad.auditoria import RegistroAuditoria
from .seguridad.boveda import Boveda, ErrorBoveda
from .seguridad.redaccion import redactar, registrar_secreto

OK, HALLAZGOS, FALLA = 0, 1, 2


# ------------------------------------------------------------------ auxiliares


def _cargar_parametros(ruta: Path | None, config: Configuracion) -> ParametrosPrevisionales:
    return ParametrosPrevisionales.desde_archivo(ruta or config.parametros)


def _emitir(informe: Informe, args, config: Configuracion) -> int:
    consola.imprimir(informe)

    destino = Path(args.salida).expanduser() if args.salida else config.informes
    marca = f"{informe.historia.cuil}"
    generados: list[Path] = []

    if args.csv or args.todo:
        generados.append(
            exportar.exportar_linea_servicios(informe, destino / f"{marca}-linea-servicios.csv")
        )
        generados.append(
            exportar.exportar_tramos_detalle(informe, destino / f"{marca}-tramos-detalle.csv")
        )
        generados.append(exportar.exportar_hallazgos(informe, destino / f"{marca}-hallazgos.csv"))
        generados.append(exportar.exportar_detalle(informe, destino / f"{marca}-detalle.csv"))
    if args.html or args.todo:
        generados.append(html.exportar_html(informe, destino / f"{marca}-informe.html"))
    if args.json or args.todo:
        generados.append(exportar.exportar_json(informe, destino / f"{marca}-informe.json"))
    if args.calculadora or args.todo:
        generados.append(
            calculadora.exportar_calculadora(informe, destino / f"{marca}-calculadora.json")
        )

    if any(r.name.endswith("-calculadora.json") for r in generados):
        print(
            "\nEl archivo para la Calculadora de Aportes trae solo servicios de caja\n"
            "NACIONAL, que es lo que registran ANSES, ARCA y SICAM. Si el afiliado\n"
            "tiene servicios de una caja provincial no transferida, cargalos aparte\n"
            "en la calculadora con su certificación.\n"
        )

    if generados:
        print("Archivos generados:")
        for ruta in generados:
            print(f"  · {ruta}")

    return HALLAZGOS if informe.errores else OK


def _pedir_clave(cuil: str) -> str:
    clave = getpass.getpass(
        f"Clave de la Seguridad Social de {formatear_cuil(cuil)} (no se muestra): "
    )
    if not clave:
        raise ErrorFuente("No ingresaste la clave.")
    registrar_secreto(clave)
    return clave


# -------------------------------------------------------------------- comandos


def _leer_pdf(ruta: Path, cuil: str, nombre: str | None, forzar_generico: bool):
    """Usa el lector del HLAB de ANSES cuando el PDF tiene esa estructura."""
    from .fuentes.hlab_anses import es_hlab, leer_hlab
    from .fuentes.pdf_anses import leer_pdf_historia_laboral

    if not forzar_generico and es_hlab(ruta):
        return leer_hlab(ruta, cuil, nombre)
    return leer_pdf_historia_laboral(ruta, cuil, nombre)


def _reunir_fuentes(args, cuil: str) -> list:
    """Lee todas las fuentes indicadas en la línea de comandos."""
    from .fuentes.arca_aportes import leer_aportes_arca
    from .fuentes.planilla import leer_planilla
    from .fuentes.sicam import PoliticaDeuda, leer_sicam

    historias = []

    if args.planilla:
        historias.append(leer_planilla(args.planilla, cuil, args.nombre))
    if args.pdf:
        historias.append(_leer_pdf(args.pdf, cuil, args.nombre, args.pdf_generico))
    if args.hlab:
        from .fuentes.hlab_anses import leer_hlab

        historias.append(leer_hlab(args.hlab, cuil, args.nombre))
    if args.arca:
        historias.append(leer_aportes_arca(args.arca, cuil, args.nombre))
    if args.sicam_revista:
        politica = PoliticaDeuda(
            deuda_es_regularizada=not args.sicam_deuda_sin_regularizar,
            aplicar_prescripcion_art1=not args.sin_prescripcion_art1,
        )
        historias.append(
            leer_sicam(
                args.sicam_revista,
                args.sicam_deuda,
                cuil,
                args.nombre,
                politica,
            )
        )
    elif args.sicam_deuda:
        raise ErrorFuente(
            "--sicam-deuda necesita también --sicam-revista: el detalle de deuda "
            "solo se interpreta contra los períodos de actividad."
        )

    if not historias:
        raise ErrorFuente(
            "No indicaste ninguna fuente. Usá --hlab, --arca, --sicam-revista, "
            "--planilla o --pdf (se pueden combinar)."
        )
    return historias


def comando_analizar(args) -> int:
    from .analisis.consolidacion import consolidar

    config = Configuracion.cargar(args.dir).preparar()
    cuil = normalizar_cuil(args.cuil)
    parametros = _cargar_parametros(args.parametros, config)

    historias = _reunir_fuentes(args, cuil)

    if len(historias) == 1:
        historia = historias[0]
        conflictos = []
    else:
        resultado = consolidar(historias, args.nombre)
        historia, conflictos = resultado.historia, resultado.conflictos
        print(f"Fuentes consolidadas ({len(historias)}):")
        for fuente in resultado.fuentes:
            print(f"  · {fuente}")
        if conflictos:
            print(f"\n{len(conflictos)} discrepancia(s) entre fuentes:")
            for conflicto in conflictos[:15]:
                print(f"  ! {conflicto.mensaje}")
            if len(conflictos) > 15:
                print(f"  … y {len(conflictos) - 15} más (ver el informe exportado).")

    informe = analizar(historia, parametros)

    RegistroAuditoria(config.auditoria).registrar(
        "analisis.local",
        cuil,
        fuente=historia.fuente,
        periodos=str(len(historia)),
        errores=str(len(informe.errores)),
    )
    return _emitir(informe, args, config)


def comando_anses(args) -> int:
    from .fuentes.mianses_web import (
        ClienteMiANSES,
        ConfiguracionPortal,
        inspeccionar_selectores,
    )

    config = Configuracion.cargar(args.dir).preparar()
    portal = ConfiguracionPortal.cargar(args.selectores)

    if args.inspeccionar:
        informe_selectores = inspeccionar_selectores(portal)
        print(f"Selectores en uso ({informe_selectores['origen']}):")
        print(f"  URL de ingreso: {informe_selectores['url_login']}")
        for paso, selectores in informe_selectores["pasos"].items():
            print(f"  {paso}:")
            for selector in selectores:
                print(f"      {selector}")
        print(
            "\nAjustá este archivo con los selectores reales del portal antes de "
            "usar el acceso automatizado."
        )
        return OK

    cuil = normalizar_cuil(args.cuil)
    auditoria = RegistroAuditoria(config.auditoria)

    if args.desde_boveda:
        entrada = Boveda(config.boveda).obtener_cliente(cuil)
        clave = entrada.clave
    else:
        clave = _pedir_clave(cuil)

    if not args.sin_confirmar:
        print(
            "\nVas a acceder a la cuenta de ANSES de "
            f"{formatear_cuil(cuil)} con las credenciales que aportó el cliente.\n"
            "Confirmá que tenés autorización expresa para hacerlo."
        )
        if input("¿Continuamos? [s/N]: ").strip().lower() not in {"s", "si", "sí", "y"}:
            print("Cancelado.")
            return FALLA

    parametros = _cargar_parametros(args.parametros, config)

    with CredencialesANSES(cuil, clave) as credenciales:
        cliente = ClienteMiANSES(
            credenciales=credenciales,
            carpeta_trabajo=config.descargas / cuil,
            configuracion=portal,
            visible=not args.headless,
            auditoria=auditoria,
        )
        historia = cliente.obtener(cuil)

    if args.nombre:
        historia.nombre = args.nombre

    informe = analizar(historia, parametros)
    auditoria.registrar(
        "analisis.portal", cuil, periodos=str(len(historia)), errores=str(len(informe.errores))
    )
    return _emitir(informe, args, config)


def comando_lote(args) -> int:
    from .lote import leer_padron, procesar_lote
    from .reportes import lote as reporte_lote

    config = Configuracion.cargar(args.dir).preparar()
    parametros = _cargar_parametros(args.parametros, config)
    clientes = leer_padron(args.padron)
    auditoria = RegistroAuditoria(config.auditoria)
    destino = Path(args.salida).expanduser() if args.salida else config.informes

    print(f"Procesando {len(clientes)} expediente(s)…\n")

    def obtener(cliente):
        if cliente.archivo is None:
            raise ErrorFuente(
                "El padrón no indica archivo para este cliente. Agregá la "
                "columna 'archivo' con la ruta a su historia laboral."
            )
        if cliente.archivo.suffix.lower() == ".pdf":
            return _leer_pdf(cliente.archivo, cliente.cuil, cliente.nombre, False)
        from .fuentes.planilla import leer_planilla

        return leer_planilla(cliente.archivo, cliente.cuil, cliente.nombre)

    def exportar_uno(informe, cliente):
        if not (args.csv or args.html or args.json or args.todo):
            return []
        generados = []
        marca = cliente.cuil
        if args.csv or args.todo:
            generados.append(
                exportar.exportar_linea_servicios(informe, destino / f"{marca}-linea-servicios.csv")
            )
        if args.html or args.todo:
            generados.append(html.exportar_html(informe, destino / f"{marca}-informe.html"))
        if args.json or args.todo:
            generados.append(exportar.exportar_json(informe, destino / f"{marca}-informe.json"))
        return generados

    def avisar(resultado):
        icono = {"en orden": "·", "con errores": "✗", "no procesado": "!"}[resultado.estado]
        print(f"  {icono} {resultado.cliente.etiqueta}  →  {resultado.estado}")

    resumen = procesar_lote(
        clientes,
        parametros,
        obtener_historia=obtener,
        exportar=exportar_uno,
        al_terminar_cliente=avisar,
        auditoria=auditoria,
        pausa_segundos=args.pausa,
    )

    reporte_lote.imprimir_lote(resumen)

    indice_csv = reporte_lote.exportar_indice_csv(resumen, destino / "lote-indice.csv")
    indice_html = reporte_lote.exportar_indice_html(resumen, destino / "lote-indice.html")
    print(f"Índice del lote:\n  · {indice_csv}\n  · {indice_html}")

    return HALLAZGOS if resumen.requiere_atencion else OK


def comando_boveda(args) -> int:
    config = Configuracion.cargar(args.dir).preparar()
    boveda = Boveda(config.boveda)
    auditoria = RegistroAuditoria(config.auditoria)

    if args.accion == "guardar":
        cuil = normalizar_cuil(args.cuil)
        clave = _pedir_clave(cuil)
        boveda.guardar_cliente(cuil, clave, alias=args.alias or "", nota=args.nota or "")
        auditoria.registrar("boveda.guardar", cuil)
        print(f"Credenciales de {formatear_cuil(cuil)} guardadas cifradas en {config.boveda}")
        return OK

    if args.accion == "listar":
        clientes = boveda.listar()
        if not clientes:
            print("La bóveda está vacía.")
            return OK
        print(f"{len(clientes)} cliente(s) en {config.boveda}:")
        for cliente in clientes:
            alias = f"  ({cliente['alias']})" if cliente["alias"] else ""
            print(f"  · {cliente['cuil']}{alias}")
        return OK

    if args.accion == "eliminar":
        cuil = normalizar_cuil(args.cuil)
        if boveda.eliminar_cliente(cuil):
            auditoria.registrar("boveda.eliminar", cuil)
            print(f"Eliminadas las credenciales de {formatear_cuil(cuil)}.")
            return OK
        print(f"No había credenciales guardadas para {formatear_cuil(cuil)}.")
        return FALLA

    return FALLA


def comando_parametros(args) -> int:
    config = Configuracion.cargar(args.dir).preparar()

    if args.accion == "plantilla":
        destino = Path(args.destino or config.base / "parametros_previsionales.json")
        if destino.exists() and not args.forzar:
            print(f"Ya existe {destino}. Usá --forzar para sobrescribirlo.")
            return FALLA
        ParametrosPrevisionales().guardar(destino)
        print(f"Plantilla vacía escrita en {destino}")
        print("Cargá ahí las bases imponibles mínimas oficiales antes de analizar.")
        return OK

    parametros = _cargar_parametros(args.parametros, config)
    cobertura = parametros.cobertura_bases
    print(f"Archivo: {parametros.origen}")
    print(f"Tramos de base mínima: {len(parametros.bases_minimas)}")
    if cobertura:
        desde, hasta = cobertura
        print(f"Cobertura: {desde} a {hasta or 'vigente (tramo abierto)'}")
    print(f"Tramos de alícuotas: {len(parametros.alicuotas)}")

    sin_verificar = parametros.bases_no_verificadas()
    if sin_verificar:
        print(f"\n⚠ {len(sin_verificar)} tramo(s) sin verificar contra la norma:")
        for tramo in sin_verificar[:20]:
            print(f"    {tramo.desde} → {tramo.hasta or 'vigente'}   {tramo.valor}   {tramo.norma}")
        return HALLAZGOS
    if not parametros.tiene_bases:
        print("\n⚠ No hay bases mínimas cargadas: el control de mínimo imponible no corre.")
        return HALLAZGOS
    print("\nTodos los tramos figuran verificados.")
    return OK


def comando_auditoria(args) -> int:
    config = Configuracion.cargar(args.dir)
    eventos = RegistroAuditoria(config.auditoria).leer(limite=args.limite)
    if not eventos:
        print(f"Sin eventos registrados en {config.auditoria}")
        return OK
    for evento in eventos:
        print(
            f"{evento['momento']}  {evento['accion']:<24} "
            f"{evento.get('cuil', ''):<18} {evento['resultado']}"
        )
    return OK


def comando_entorno(args) -> int:
    config = Configuracion.cargar(args.dir)
    print("Carpetas")
    print(f"  base        {config.base}")
    print(f"  bóveda      {config.boveda}  {'(existe)' if config.boveda.exists() else '(vacía)'}")
    print(f"  auditoría   {config.auditoria}")
    print(f"  descargas   {config.descargas}")
    print(f"  informes    {config.informes}")
    print(f"  parámetros  {config.parametros}")
    print("\nVariables de entorno")
    for nombre, descripcion in VARIABLES_ENTORNO.items():
        print(f"  {nombre:<26} {descripcion}")
    return OK


# ------------------------------------------------------------------- parser


def _agregar_opciones_salida(sub: argparse.ArgumentParser) -> None:
    sub.add_argument("--salida", help="Carpeta donde dejar los archivos generados.")
    sub.add_argument("--csv", action="store_true", help="Exportar CSV (línea, hallazgos, detalle).")
    sub.add_argument("--html", action="store_true", help="Exportar el informe en HTML.")
    sub.add_argument("--json", action="store_true", help="Exportar el informe en JSON.")
    sub.add_argument(
        "--calculadora",
        action="store_true",
        help="Exportar el historial para abrir con la Calculadora de Aportes.",
    )
    sub.add_argument("--todo", action="store_true", help="Exportar en todos los formatos.")
    sub.add_argument("--parametros", type=Path, help="Tabla de parámetros previsionales.")
    sub.add_argument("--nombre", help="Nombre del afiliado, para el encabezado del informe.")


def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ayudante-contable",
        description=(
            "Ayudante contable previsional: analiza la historia laboral de ANSES, "
            "controla el mínimo imponible y el ingreso efectivo de los aportes, "
            "y arma la línea de servicios con fechas de inicio y fin."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Ejemplos:\n"
            "  ayudante-contable analizar --cuil 20-12345678-6 "
            "--planilla historia.csv --todo\n"
            "  ayudante-contable anses --cuil 20-12345678-6 --todo\n"
            "  ayudante-contable parametros verificar\n"
        ),
    )
    parser.add_argument("--dir", type=Path, help="Carpeta de trabajo del estudio.")
    subparsers = parser.add_subparsers(dest="comando", required=True)

    # analizar ---------------------------------------------------------------
    analizar_sub = subparsers.add_parser(
        "analizar", help="Analiza una historia laboral ya descargada (CSV, XLSX o PDF)."
    )
    analizar_sub.add_argument("--cuil", required=True)
    analizar_sub.add_argument(
        "--hlab", type=Path, help="PDF de Historia Laboral de ANSES (remuneración imponible)."
    )
    analizar_sub.add_argument(
        "--arca",
        type=Path,
        help="Export «Aportes en Línea» de ARCA: declarado vs depositado en "
        "relación de dependencia.",
    )
    analizar_sub.add_argument(
        "--sicam-revista", type=Path, help="PDF de Situación de Revista de SICAM."
    )
    analizar_sub.add_argument(
        "--sicam-deuda", type=Path, help="PDF de Detalle de la Deuda de SICAM."
    )
    analizar_sub.add_argument(
        "--sicam-deuda-sin-regularizar",
        action="store_true",
        help="Tratar la deuda de SICAM como aporte NO ingresado. Por defecto se "
        "considera regularizada (plan de pagos o moratoria).",
    )
    analizar_sub.add_argument(
        "--sin-prescripcion-art1",
        action="store_true",
        help="No excluir los períodos con Art. 1 Ley 25.321. Por defecto se "
        "excluyen por prescripción.",
    )
    analizar_sub.add_argument("--planilla", type=Path, help="Archivo CSV/XLSX exportado de ANSES.")
    analizar_sub.add_argument(
        "--pdf", type=Path, help="PDF de historia laboral (reconoce el HLAB de ANSES)."
    )
    analizar_sub.add_argument(
        "--pdf-generico",
        action="store_true",
        help="Forzar el lector de PDF genérico en vez del específico del HLAB.",
    )
    _agregar_opciones_salida(analizar_sub)
    analizar_sub.set_defaults(func=comando_analizar)

    # anses ------------------------------------------------------------------
    anses_sub = subparsers.add_parser(
        "anses", help="Entra al portal Mi ANSES y descarga la historia laboral."
    )
    anses_sub.add_argument("--cuil", required=True)
    anses_sub.add_argument(
        "--desde-boveda",
        action="store_true",
        help="Tomar la clave de la bóveda en lugar de pedirla por consola.",
    )
    anses_sub.add_argument(
        "--headless",
        action="store_true",
        help="Navegador sin ventana. No sirve si el portal pide CAPTCHA o código.",
    )
    anses_sub.add_argument(
        "--sin-confirmar", action="store_true", help="Omitir la confirmación de autorización."
    )
    anses_sub.add_argument(
        "--inspeccionar",
        action="store_true",
        help="Mostrar los selectores configurados y salir, sin abrir el navegador.",
    )
    anses_sub.add_argument("--selectores", type=Path, help="Archivo de selectores del portal.")
    _agregar_opciones_salida(anses_sub)
    anses_sub.set_defaults(func=comando_anses)

    # lote -------------------------------------------------------------------
    lote_sub = subparsers.add_parser(
        "lote", help="Procesa muchos clientes de una pasada desde un padrón CSV."
    )
    lote_sub.add_argument(
        "--padron",
        type=Path,
        required=True,
        help="CSV con una columna 'cuil' y, opcionalmente, 'nombre' y 'archivo'.",
    )
    lote_sub.add_argument(
        "--pausa",
        type=float,
        default=0.0,
        help="Segundos de espera entre expedientes (para no saturar un servicio externo).",
    )
    _agregar_opciones_salida(lote_sub)
    lote_sub.set_defaults(func=comando_lote)

    # boveda -----------------------------------------------------------------
    boveda_sub = subparsers.add_parser("boveda", help="Administra credenciales cifradas.")
    boveda_sub.add_argument("accion", choices=["guardar", "listar", "eliminar"])
    boveda_sub.add_argument("--cuil")
    boveda_sub.add_argument("--alias")
    boveda_sub.add_argument("--nota")
    boveda_sub.set_defaults(func=comando_boveda)

    # parametros -------------------------------------------------------------
    parametros_sub = subparsers.add_parser(
        "parametros", help="Revisa o genera la tabla de parámetros previsionales."
    )
    parametros_sub.add_argument("accion", choices=["verificar", "plantilla"])
    parametros_sub.add_argument("--parametros", type=Path)
    parametros_sub.add_argument("--destino", type=Path)
    parametros_sub.add_argument("--forzar", action="store_true")
    parametros_sub.set_defaults(func=comando_parametros)

    # auditoria --------------------------------------------------------------
    auditoria_sub = subparsers.add_parser("auditoria", help="Muestra el registro de auditoría.")
    auditoria_sub.add_argument("--limite", type=int, default=50)
    auditoria_sub.set_defaults(func=comando_auditoria)

    # entorno ----------------------------------------------------------------
    entorno_sub = subparsers.add_parser("entorno", help="Muestra rutas y variables en uso.")
    entorno_sub.set_defaults(func=comando_entorno)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = construir_parser()
    args = parser.parse_args(argv)

    if args.comando == "boveda" and args.accion in {"guardar", "eliminar"} and not args.cuil:
        parser.error(f"'boveda {args.accion}' necesita --cuil")

    try:
        return args.func(args)
    except (ErrorFuente, ErrorBoveda, ErrorParametros, ErrorLote, ValueError) as exc:
        print(f"\n✗ {redactar(exc)}", file=sys.stderr)
        return FALLA
    except KeyboardInterrupt:  # pragma: no cover
        print("\nInterrumpido.", file=sys.stderr)
        return FALLA


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
