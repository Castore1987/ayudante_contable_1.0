"""Pruebas del export al formato de la «Calculadora de Aportes»."""

import calendar
import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from ayudante_contable.analisis.validador import analizar
from ayudante_contable.modelo.dominio import EstadoIngreso, TipoAporte
from ayudante_contable.reportes.calculadora import (
    exportar_calculadora,
    historial_calculadora,
)
from tests.ayuda import historia, meses, parametros


def _informe(*grupos, nombre="PEREZ, JUAN"):
    hl = historia(*grupos)
    hl.nombre = nombre
    return analizar(hl, parametros())


class PruebasEstructura(unittest.TestCase):
    def test_trae_las_tres_listas_y_la_metadata(self):
        datos = historial_calculadora(_informe(meses((2020, 1), (2020, 6))))
        self.assertEqual(
            set(datos),
            {"metadata", "relacion_dependencia", "autonomos", "monotributo"},
        )
        self.assertEqual(datos["metadata"]["nombre"], "PEREZ, JUAN")

    def test_deja_en_blanco_lo_que_no_sale_de_la_historia_laboral(self):
        """La fecha de nacimiento y la edad requerida las carga el estudio."""
        metadata = historial_calculadora(_informe(meses((2020, 1), (2020, 6))))["metadata"]
        for campo in ("fecha_nacimiento", "edad_req_anios", "edad_req_meses", "edad_req_dias"):
            self.assertEqual(metadata[campo], "")

    def test_sin_cuil_legible_usa_el_cuil_como_nombre(self):
        datos = historial_calculadora(_informe(meses((2020, 1), (2020, 6)), nombre=None))
        self.assertEqual(datos["metadata"]["nombre"], "20-12345678-6")


class PruebasFechas(unittest.TestCase):
    def test_abre_el_dia_1_y_cierra_el_ultimo_dia_del_mes(self):
        datos = historial_calculadora(_informe(meses((2020, 1), (2020, 6))))
        tramo = datos["relacion_dependencia"][0]
        self.assertEqual(tramo["ingreso"], "01/01/2020")
        self.assertEqual(tramo["egreso"], "30/06/2020")

    def test_respeta_los_febreros_bisiestos(self):
        datos = historial_calculadora(_informe(meses((2020, 1), (2020, 2))))
        self.assertEqual(datos["relacion_dependencia"][0]["egreso"], "29/02/2020")
        self.assertEqual(calendar.monthrange(2020, 2)[1], 29)

    def test_usa_el_formato_de_fecha_de_la_calculadora(self):
        tramo = historial_calculadora(_informe(meses((2020, 1), (2020, 6))))[
            "relacion_dependencia"
        ][0]
        for fecha in (tramo["ingreso"], tramo["egreso"]):
            self.assertRegex(fecha, r"^\d{2}/\d{2}/\d{4}$")


class PruebasClasificacion(unittest.TestCase):
    def test_la_dependencia_va_a_su_lista_con_el_empleador(self):
        datos = historial_calculadora(
            _informe(meses((2020, 1), (2020, 6), empleador="ACME SA"))
        )
        self.assertEqual(len(datos["relacion_dependencia"]), 1)
        self.assertEqual(datos["relacion_dependencia"][0]["empleador"], "ACME SA")
        self.assertEqual(datos["autonomos"], [])

    def test_autonomo_y_monotributo_van_juntos_a_la_lista_de_autonomos(self):
        datos = historial_calculadora(
            _informe(
                meses((2020, 1), (2020, 6), cuit=None, empleador="Independiente",
                      tipo=TipoAporte.AUTONOMO),
                meses((2020, 7), (2020, 12), cuit=None, empleador="Independiente",
                      tipo=TipoAporte.MONOTRIBUTO),
            )
        )
        self.assertEqual(datos["relacion_dependencia"], [])
        self.assertEqual(datos["monotributo"], [])
        # Contiguos y del mismo régimen a estos efectos: un solo período.
        self.assertEqual(len(datos["autonomos"]), 1)
        self.assertEqual(datos["autonomos"][0]["inicio"], "01/01/2020")
        self.assertEqual(datos["autonomos"][0]["fin"], "31/12/2020")

    def test_todo_sale_como_caja_nacional(self):
        datos = historial_calculadora(_informe(meses((2020, 1), (2020, 6))))
        self.assertFalse(datos["relacion_dependencia"][0]["es_provincial"])


class PruebasPeriodosValidos(unittest.TestCase):
    def test_los_meses_que_no_computan_quedan_afuera_y_parten_el_tramo(self):
        datos = historial_calculadora(
            _informe(
                meses((2020, 1), (2020, 3)),
                meses((2020, 4), (2020, 5), estado=EstadoIngreso.NO_INGRESADO),
                meses((2020, 6), (2020, 8)),
            )
        )
        tramos = datos["relacion_dependencia"]
        self.assertEqual(len(tramos), 2)
        self.assertEqual((tramos[0]["ingreso"], tramos[0]["egreso"]),
                         ("01/01/2020", "31/03/2020"))
        self.assertEqual((tramos[1]["ingreso"], tramos[1]["egreso"]),
                         ("01/06/2020", "31/08/2020"))

    def test_la_lista_de_deudas_va_vacia_para_no_restar_dos_veces(self):
        """Los tramos ya vienen netos: la calculadora no debe restar de nuevo."""
        datos = historial_calculadora(
            _informe(
                meses((2020, 1), (2020, 6), cuit=None, empleador="Independiente",
                      tipo=TipoAporte.AUTONOMO)
            )
        )
        self.assertEqual(datos["autonomos"][0]["deudas"], [])


class PruebasArchivo(unittest.TestCase):
    def test_escribe_un_json_que_la_calculadora_puede_abrir(self):
        ruta = Path(tempfile.mkdtemp()) / "sesion.json"
        exportar_calculadora(_informe(meses((2020, 1), (2020, 6))), ruta)
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        self.assertEqual(len(datos["relacion_dependencia"]), 1)

    def test_crea_la_carpeta_destino(self):
        destino = Path(tempfile.mkdtemp()) / "nueva" / "sesion.json"
        self.assertTrue(
            exportar_calculadora(_informe(meses((2020, 1), (2020, 6))), destino).exists()
        )


if __name__ == "__main__":
    unittest.main()
