"""Pruebas de la línea de comandos, incluido el flujo completo de punta a punta."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from ayudante_contable.cli import FALLA, HALLAZGOS, OK, main

RAIZ = Path(__file__).resolve().parents[1]
EJEMPLO = RAIZ / "ejemplos" / "historia_laboral_ejemplo.csv"
PARAMETROS_EJEMPLO = RAIZ / "datos" / "parametros_previsionales.ejemplo.json"
PARAMETROS_REPO = RAIZ / "datos" / "parametros_previsionales.json"
CUIL = "20-12345678-6"


def correr(*argumentos):
    """Ejecuta el CLI y devuelve ``(código de salida, salida estándar)``."""
    salida = io.StringIO()
    error = io.StringIO()
    with contextlib.redirect_stdout(salida), contextlib.redirect_stderr(error):
        codigo = main(list(argumentos))
    return codigo, salida.getvalue() + error.getvalue()


class PruebasAnalizar(unittest.TestCase):
    def setUp(self):
        self.trabajo = Path(tempfile.mkdtemp())

    def _analizar(self, *extra):
        return correr(
            "--dir", str(self.trabajo),
            "analizar",
            "--cuil", CUIL,
            "--planilla", str(EJEMPLO),
            "--parametros", str(PARAMETROS_EJEMPLO),
            *extra,
        )

    def test_devuelve_codigo_1_cuando_encuentra_errores(self):
        codigo, salida = self._analizar()
        self.assertEqual(codigo, HALLAZGOS)
        self.assertIn("APORTE_BAJO_MINIMO", salida)
        self.assertIn("APORTE_NO_INGRESADO", salida)

    def test_arma_la_linea_de_servicios_con_fechas(self):
        _, salida = self._analizar()
        self.assertIn("LÍNEA DE SERVICIOS", salida)
        self.assertIn("SUPERMERCADO DEL SOL SA", salida)
        self.assertIn("01/2022", salida)

    def test_exporta_todos_los_formatos_pedidos(self):
        codigo, _ = self._analizar("--todo")
        self.assertEqual(codigo, HALLAZGOS)
        informes = self.trabajo / "informes"
        generados = sorted(p.name for p in informes.iterdir())
        self.assertEqual(
            generados,
            [
                "20123456786-calculadora.json",
                "20123456786-detalle.csv",
                "20123456786-hallazgos.csv",
                "20123456786-informe.html",
                "20123456786-informe.json",
                "20123456786-linea-servicios.csv",
                "20123456786-tramos-detalle.csv",
            ],
        )

    def test_el_json_exportado_refleja_lo_analizado(self):
        self._analizar("--json")
        datos = json.loads(
            (self.trabajo / "informes" / "20123456786-informe.json").read_text(encoding="utf-8")
        )
        # 36 meses declarados menos los 9 que quedaron bajo la base mínima
        # (3 de SUPERMERCADO en 2023 y 6 de autónomo en 2025): no computan.
        self.assertEqual(datos["resumen"]["meses_computables"], 27)
        # 3 meses declarados sin ingresar + los 9 que quedaron bajo el mínimo.
        self.assertEqual(datos["resumen"]["meses_descartados"], 12)
        # Los meses bajo el mínimo abren lagunas donde antes había servicio.
        self.assertEqual([l["meses"] for l in datos["lagunas"]], [9, 6])
        self.assertEqual(len(datos["linea_servicios"]), 4)

    def test_respeta_la_carpeta_de_salida_indicada(self):
        destino = self.trabajo / "expediente"
        self._analizar("--csv", "--salida", str(destino))
        self.assertTrue((destino / "20123456786-linea-servicios.csv").exists())

    def test_deja_constancia_en_la_auditoria(self):
        self._analizar()
        registro = (self.trabajo / "auditoria.jsonl").read_text(encoding="utf-8")
        self.assertIn("analisis.local", registro)
        self.assertNotIn("20-12345678-6", registro)

    def test_sin_parametros_cargados_avisa_en_lugar_de_callarse(self):
        vacios = self.trabajo / "vacios.json"
        correr("--dir", str(self.trabajo), "parametros", "plantilla", "--destino", str(vacios))
        codigo, salida = correr(
            "--dir", str(self.trabajo),
            "analizar", "--cuil", CUIL,
            "--planilla", str(EJEMPLO),
            "--parametros", str(vacios),
        )
        self.assertIn("PARAMETROS_SIN_CARGAR", salida)
        # Sin bases cargadas no se juzga el mínimo, pero el control de ingreso
        # efectivo no depende de la tabla y sigue detectando los meses impagos.
        self.assertNotIn("APORTE_BAJO_MINIMO", salida)
        self.assertIn("APORTE_NO_INGRESADO", salida)
        self.assertEqual(codigo, HALLAZGOS)

    def test_archivo_inexistente_devuelve_codigo_2(self):
        codigo, salida = correr(
            "--dir", str(self.trabajo),
            "analizar", "--cuil", CUIL, "--planilla", "/no/existe.csv",
        )
        self.assertEqual(codigo, FALLA)
        self.assertIn("No encontré el archivo", salida)

    def test_cuil_malformado_devuelve_codigo_2(self):
        codigo, salida = correr(
            "--dir", str(self.trabajo),
            "analizar", "--cuil", "123", "--planilla", str(EJEMPLO),
        )
        self.assertEqual(codigo, FALLA)
        self.assertIn("11 dígitos", salida)


class PruebasParametros(unittest.TestCase):
    def setUp(self):
        self.trabajo = Path(tempfile.mkdtemp())

    def test_verificar_avisa_por_los_tramos_sin_auditar(self):
        codigo, salida = correr(
            "--dir", str(self.trabajo),
            "parametros", "verificar", "--parametros", str(PARAMETROS_EJEMPLO),
        )
        self.assertEqual(codigo, HALLAZGOS)
        self.assertIn("sin verificar", salida)

    def test_verificar_avisa_cuando_la_tabla_esta_vacia(self):
        vacios = self.trabajo / "vacios.json"
        correr("--dir", str(self.trabajo), "parametros", "plantilla", "--destino", str(vacios))
        codigo, salida = correr(
            "--dir", str(self.trabajo),
            "parametros", "verificar", "--parametros", str(vacios),
        )
        self.assertEqual(codigo, HALLAZGOS)
        self.assertIn("no corre", salida)

    def test_verificar_informa_la_cobertura_de_la_tabla_del_repo(self):
        codigo, salida = correr(
            "--dir", str(self.trabajo),
            "parametros", "verificar", "--parametros", str(PARAMETROS_REPO),
        )
        self.assertEqual(codigo, HALLAZGOS)   # cargada pero sin verificar
        self.assertIn("04/1994", salida)
        self.assertIn("03/2026", salida)
        self.assertIn("82", salida)

    def test_plantilla_crea_un_archivo_editable(self):
        destino = self.trabajo / "p.json"
        codigo, _ = correr(
            "--dir", str(self.trabajo), "parametros", "plantilla", "--destino", str(destino)
        )
        self.assertEqual(codigo, OK)
        self.assertEqual(json.loads(destino.read_text(encoding="utf-8"))["bases_minimas"], [])

    def test_plantilla_no_pisa_un_archivo_existente_sin_forzar(self):
        destino = self.trabajo / "p.json"
        correr("--dir", str(self.trabajo), "parametros", "plantilla", "--destino", str(destino))
        codigo, salida = correr(
            "--dir", str(self.trabajo), "parametros", "plantilla", "--destino", str(destino)
        )
        self.assertEqual(codigo, FALLA)
        self.assertIn("--forzar", salida)


class PruebasBovedaCLI(unittest.TestCase):
    def setUp(self):
        self.trabajo = Path(tempfile.mkdtemp())

    def test_listar_una_boveda_vacia_no_es_un_error(self):
        codigo, salida = correr("--dir", str(self.trabajo), "boveda", "listar")
        self.assertEqual(codigo, OK)
        self.assertIn("vacía", salida)

    def test_guardar_sin_cuil_es_un_error_de_uso(self):
        with self.assertRaises(SystemExit):
            correr("--dir", str(self.trabajo), "boveda", "guardar")


class PruebasComandosAuxiliares(unittest.TestCase):
    def setUp(self):
        self.trabajo = Path(tempfile.mkdtemp())

    def test_entorno_muestra_las_rutas_en_uso(self):
        codigo, salida = correr("--dir", str(self.trabajo), "entorno")
        self.assertEqual(codigo, OK)
        self.assertIn("bóveda", salida)
        self.assertIn("AYUDANTE_CLAVE_MAESTRA", salida)

    def test_auditoria_sin_eventos_lo_dice(self):
        codigo, salida = correr("--dir", str(self.trabajo), "auditoria")
        self.assertEqual(codigo, OK)
        self.assertIn("Sin eventos", salida)

    def test_inspeccionar_selectores_no_abre_el_navegador(self):
        codigo, salida = correr(
            "--dir", str(self.trabajo), "anses", "--cuil", CUIL, "--inspeccionar"
        )
        self.assertEqual(codigo, OK)
        self.assertIn("campo_cuil", salida)
        self.assertIn("Selectores en uso", salida)


if __name__ == "__main__":
    unittest.main()
