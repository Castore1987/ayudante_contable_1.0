"""Pruebas de los reportes: consola, HTML y exportaciones."""

import csv
import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from ayudante_contable.analisis.validador import analizar
from ayudante_contable.reportes import consola, exportar, html
from ayudante_contable.reportes.formato import moneda, tabla
from ayudante_contable.modelo.dominio import EstadoIngreso
from tests.ayuda import historia, meses, parametros


def informe_de_ejemplo():
    hl = historia(
        meses((2020, 1), (2020, 6), remuneracion="100", empleador="ACME SA"),
        meses((2021, 1), (2021, 6), estado=EstadoIngreso.NO_INGRESADO, empleador="ACME SA"),
    )
    hl.nombre = "PEREZ, JUAN"
    return analizar(hl, parametros(base=Decimal("1000")))


class PruebasFormato(unittest.TestCase):
    def test_moneda_en_formato_argentino(self):
        self.assertEqual(moneda(Decimal("1234567.89")), "$ 1.234.567,89")
        self.assertEqual(moneda(Decimal("0")), "$ 0,00")
        self.assertEqual(moneda(None), "—")

    def test_la_tabla_vacia_lo_dice(self):
        self.assertIn("sin datos", tabla(["a"], []))

    def test_la_tabla_trunca_las_celdas_largas(self):
        salida = tabla(["x"], [["a" * 80]], ancho_maximo=10)
        self.assertIn("…", salida)


class PruebasConsola(unittest.TestCase):
    def setUp(self):
        self.texto = consola.renderizar(informe_de_ejemplo())

    def test_incluye_las_secciones_principales(self):
        for seccion in ("RESUMEN", "LÍNEA DE SERVICIOS", "HALLAZGOS", "CONCLUSIÓN"):
            self.assertIn(seccion, self.texto)

    def test_muestra_las_fechas_de_inicio_y_fin(self):
        self.assertIn("01/2020", self.texto)
        self.assertIn("06/2020", self.texto)

    def test_enuncia_la_limitacion_del_informe(self):
        self.assertIn("no reemplaza", self.texto.lower())

    def test_no_falla_con_una_historia_vacia(self):
        texto = consola.renderizar(analizar(historia(), parametros()))
        self.assertIn("SIN_REGISTROS", texto)


class PruebasHTML(unittest.TestCase):
    def setUp(self):
        self.html = html.renderizar_html(informe_de_ejemplo())

    def test_es_un_documento_completo(self):
        self.assertTrue(self.html.startswith("<!doctype html>"))
        self.assertIn("</html>", self.html)

    def test_escapa_el_contenido_de_la_fuente(self):
        hl = historia(meses((2020, 1), (2020, 3), empleador="<script>alert(1)</script>"))
        salida = html.renderizar_html(analizar(hl, parametros()))
        self.assertNotIn("<script>alert(1)</script>", salida)
        self.assertIn("&lt;script&gt;", salida)

    def test_incluye_el_resumen_y_los_hallazgos(self):
        self.assertIn("Meses computables", self.html)
        self.assertIn("APORTE_NO_INGRESADO", self.html)


class PruebasExportacion(unittest.TestCase):
    def setUp(self):
        self.informe = informe_de_ejemplo()
        self.carpeta = Path(tempfile.mkdtemp())

    def _leer_csv(self, ruta):
        with ruta.open(encoding="utf-8-sig", newline="") as archivo:
            return list(csv.DictReader(archivo, delimiter=";"))

    def test_la_linea_de_servicios_trae_inicio_y_fin(self):
        filas = self._leer_csv(
            exportar.exportar_linea_servicios(self.informe, self.carpeta / "l.csv")
        )
        self.assertEqual(len(filas), 2)
        self.assertEqual(filas[0]["inicio"], "01/2020")
        self.assertEqual(filas[0]["fin"], "06/2020")
        self.assertEqual(filas[0]["meses_bajo_minimo"], "6")

    def test_el_detalle_trae_una_fila_por_periodo(self):
        filas = self._leer_csv(exportar.exportar_detalle(self.informe, self.carpeta / "d.csv"))
        self.assertEqual(len(filas), len(self.informe.historia.registros))
        self.assertIn(filas[0]["computa_servicio"], {"si", "no"})

    def test_los_hallazgos_salen_con_severidad_y_codigo(self):
        filas = self._leer_csv(exportar.exportar_hallazgos(self.informe, self.carpeta / "h.csv"))
        self.assertTrue(any(f["codigo"] == "APORTE_BAJO_MINIMO" for f in filas))
        self.assertTrue(all(f["severidad"] in {"error", "advertencia", "informacion"} for f in filas))

    def test_el_json_es_valido_y_trae_la_antiguedad(self):
        ruta = exportar.exportar_json(self.informe, self.carpeta / "i.json")
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        self.assertEqual(datos["cuil"], "20-12345678-6")
        # Los 6 meses del informe de ejemplo declaran 100 contra una base
        # mínima de 1000: quedan bajo el mínimo y ninguno computa.
        self.assertEqual(datos["antiguedad"]["meses_computables"], 0)
        self.assertEqual(len(datos["linea_servicios"]), 2)

    def test_crea_la_carpeta_destino_si_no_existe(self):
        destino = self.carpeta / "nueva" / "sub" / "l.csv"
        self.assertTrue(exportar.exportar_linea_servicios(self.informe, destino).exists())


if __name__ == "__main__":
    unittest.main()
