"""Pruebas del procesamiento por lote."""

import tempfile
import unittest
from pathlib import Path

from ayudante_contable.fuentes.base import ErrorFuente
from ayudante_contable.lote import ClienteLote, ErrorLote, leer_padron, procesar_lote
from ayudante_contable.modelo.dominio import EstadoIngreso
from ayudante_contable.reportes import lote as reporte_lote
from tests.ayuda import historia, meses, parametros

RAIZ = Path(__file__).resolve().parents[1]


def escribir(contenido: str, nombre: str = "padron.csv") -> Path:
    ruta = Path(tempfile.mkdtemp()) / nombre
    ruta.write_text(contenido, encoding="utf-8")
    return ruta


class PruebasPadron(unittest.TestCase):
    def test_lee_cuil_nombre_y_archivo(self):
        ruta = escribir(
            "cuil;nombre;archivo\n"
            "20-12345678-6;PEREZ JUAN;hl1.csv\n"
            "27-11111111-4;GOMEZ ANA;hl2.pdf\n"
        )
        clientes = leer_padron(ruta)
        self.assertEqual(len(clientes), 2)
        self.assertEqual(clientes[0].cuil, "20123456786")
        self.assertEqual(clientes[0].nombre, "PEREZ JUAN")
        self.assertEqual(clientes[0].archivo, (ruta.parent / "hl1.csv").resolve())

    def test_alcanza_con_la_columna_de_cuil(self):
        clientes = leer_padron(escribir("cuil\n20-12345678-6\n"))
        self.assertEqual(len(clientes), 1)
        self.assertIsNone(clientes[0].archivo)

    def test_acepta_coma_y_encabezados_sin_tildes(self):
        clientes = leer_padron(escribir("CUIL,Apellido y Nombre\n20123456786,PEREZ\n"))
        self.assertEqual(clientes[0].nombre, "PEREZ")

    def test_rechaza_un_cuil_repetido(self):
        ruta = escribir("cuil\n20-12345678-6\n20123456786\n")
        with self.assertRaises(ErrorLote) as contexto:
            leer_padron(ruta)
        self.assertIn("más de una vez", str(contexto.exception))

    def test_rechaza_un_cuil_malformado_indicando_la_fila(self):
        with self.assertRaises(ErrorLote) as contexto:
            leer_padron(escribir("cuil\n20-12345678-6\n123\n"))
        self.assertIn("fila 3", str(contexto.exception))

    def test_error_claro_si_no_hay_columna_de_cuil(self):
        with self.assertRaises(ErrorLote):
            leer_padron(escribir("nombre;archivo\nPEREZ;x.csv\n"))

    def test_error_claro_si_el_padron_esta_vacio(self):
        with self.assertRaises(ErrorLote):
            leer_padron(escribir("cuil\n"))

    def test_error_claro_si_no_existe(self):
        with self.assertRaises(ErrorLote):
            leer_padron("/no/existe/padron.csv")


class PruebasProcesamiento(unittest.TestCase):
    def setUp(self):
        self.clientes = [
            ClienteLote(cuil="20123456786", nombre="LIMPIO"),
            ClienteLote(cuil="27111111114", nombre="CON ERRORES"),
            ClienteLote(cuil="20333333339", nombre="ROTO"),
        ]

    def _obtener(self, cliente):
        if cliente.nombre == "ROTO":
            raise ErrorFuente("no encontré el archivo de este cliente")
        if cliente.nombre == "CON ERRORES":
            return historia(
                meses((2020, 1), (2020, 6), estado=EstadoIngreso.NO_INGRESADO),
                cuil=cliente.cuil,
            )
        return historia(meses((2020, 1), (2020, 12)), cuil=cliente.cuil)

    def _resumen(self):
        return procesar_lote(self.clientes, parametros(), obtener_historia=self._obtener)

    def test_un_expediente_que_falla_no_corta_el_lote(self):
        resumen = self._resumen()
        self.assertEqual(len(resumen), 3)
        self.assertEqual(resumen.conteo["no_procesados"], 1)
        self.assertEqual(resumen.conteo["en_orden"], 1)
        self.assertEqual(resumen.conteo["con_errores"], 1)

    def test_el_expediente_fallido_nunca_cuenta_como_en_orden(self):
        fallido = self._resumen().fallidos[0]
        self.assertEqual(fallido.cliente.nombre, "ROTO")
        self.assertFalse(fallido.limpio)
        self.assertEqual(fallido.estado, "no procesado")
        self.assertIn("no encontré el archivo", fallido.error)

    def test_el_lote_pide_atencion_si_algo_falla_o_tiene_errores(self):
        self.assertTrue(self._resumen().requiere_atencion)

    def test_un_lote_enteramente_limpio_no_pide_atencion(self):
        resumen = procesar_lote(
            [self.clientes[0]], parametros(), obtener_historia=self._obtener
        )
        self.assertFalse(resumen.requiere_atencion)

    def test_avisa_por_cada_expediente_terminado(self):
        vistos = []
        procesar_lote(
            self.clientes,
            parametros(),
            obtener_historia=self._obtener,
            al_terminar_cliente=lambda r: vistos.append(r.cliente.nombre),
        )
        self.assertEqual(vistos, ["LIMPIO", "CON ERRORES", "ROTO"])

    def test_resume_los_hallazgos_mas_frecuentes(self):
        frecuentes = dict(self._resumen().hallazgos_frecuentes())
        self.assertEqual(frecuentes.get("APORTE_NO_INGRESADO"), 1)

    def test_redacta_los_secretos_que_aparezcan_en_un_error(self):
        def revienta(cliente):
            raise ErrorFuente("falló el login con clave=SuperSecreta123")

        resumen = procesar_lote(
            [self.clientes[0]], parametros(), obtener_historia=revienta
        )
        self.assertNotIn("SuperSecreta123", resumen.fallidos[0].error)


class PruebasReporteLote(unittest.TestCase):
    def setUp(self):
        clientes = [ClienteLote(cuil="20123456786", nombre="PEREZ")]
        self.resumen = procesar_lote(
            clientes,
            parametros(),
            obtener_historia=lambda c: historia(meses((2020, 1), (2020, 12)), cuil=c.cuil),
        )
        self.carpeta = Path(tempfile.mkdtemp())

    def test_la_consola_muestra_el_conteo_y_los_expedientes(self):
        texto = reporte_lote.renderizar_lote(self.resumen)
        self.assertIn("RESUMEN DEL LOTE", texto)
        self.assertIn("20-12345678-6", texto)

    def test_el_indice_csv_trae_una_fila_por_expediente(self):
        import csv

        ruta = reporte_lote.exportar_indice_csv(self.resumen, self.carpeta / "i.csv")
        with ruta.open(encoding="utf-8-sig", newline="") as archivo:
            filas = list(csv.DictReader(archivo, delimiter=";"))
        self.assertEqual(len(filas), 1)
        self.assertEqual(filas[0]["estado"], "en orden")
        self.assertEqual(filas[0]["meses_computables"], "12")

    def test_el_indice_html_es_un_documento_completo(self):
        ruta = reporte_lote.exportar_indice_html(self.resumen, self.carpeta / "i.html")
        contenido = ruta.read_text(encoding="utf-8")
        self.assertTrue(contenido.startswith("<!doctype html>"))
        self.assertIn("PEREZ", contenido)


if __name__ == "__main__":
    unittest.main()
