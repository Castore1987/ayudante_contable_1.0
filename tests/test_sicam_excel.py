"""Pruebas de la lectura de SICAM exportado a planilla.

Las planillas de prueba se arman acá con datos inventados: ningún expediente
de cliente entra al repositorio. Reproducen las rarezas del export real —
períodos como fecha, importes en formato anglosajón y espacios duros pegados
a cada valor.
"""

import tempfile
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from ayudante_contable.fuentes.base import ErrorFuente
from ayudante_contable.fuentes.sicam import (
    es_excel,
    leer_deuda,
    leer_deuda_excel,
    leer_revista,
    leer_revista_excel,
)
from ayudante_contable.modelo.dominio import Periodo

DURO = "\xa0"


def _planilla(filas: list[list]) -> Path:
    import openpyxl

    libro = openpyxl.Workbook()
    hoja = libro.active
    for fila in filas:
        hoja.append(fila)
    ruta = Path(tempfile.mkdtemp()) / "sicam.xlsx"
    libro.save(ruta)
    libro.close()
    return ruta


def _planilla_deuda(filas_datos: list[list]) -> Path:
    encabezado = [
        ["", "", "Categoría", "", "Benef. Aplic.", "Meses Adeudados"],
        ["Período"],
        ["Desde", "Hasta", "Histórica", "Actual", "", "Aportes", "INSSJP", "Fonavi",
         "Aportes", "INSSJP", "Fonavi", "Subtotal", "Aportes", "INSSJP", "Fonavi",
         "Subtotal", ""],
    ]
    return _planilla(encabezado + filas_datos)


def _fila_deuda(desde, hasta, cat="A", beneficio="", meses="1",
                capital="100.00", intereses="50.00", total="150.00") -> list:
    """Un renglón con la forma exacta del export: fechas e importes con \\xa0."""
    return [
        datetime(desde[0], desde[1], 1), datetime(hasta[0], hasta[1], 1),
        cat, f"{cat}{DURO}", f"{beneficio}{DURO}" if beneficio else "",
        meses, meses, "0",
        f"{capital}{DURO}", "0.00" + DURO, "0.00" + DURO, capital,
        f"{intereses}{DURO}", "0.00" + DURO, "0.00" + DURO, f"{intereses}{DURO}",
        f"{total}{DURO}",
    ]


class PruebasDeteccion(unittest.TestCase):
    def test_reconoce_las_extensiones_de_planilla(self):
        self.assertTrue(es_excel("deuda.xlsx"))
        self.assertTrue(es_excel(Path("/tmp/DEUDA.XLSX")))
        self.assertFalse(es_excel("deuda.pdf"))

    def test_leer_deuda_deriva_a_la_planilla_sin_ocr(self):
        ruta = _planilla_deuda([_fila_deuda((2020, 1), (2020, 3))])
        self.assertEqual(len(leer_deuda(ruta).filas), 1)


class PruebasDeuda(unittest.TestCase):
    def test_lee_periodos_que_vienen_como_fecha(self):
        ruta = _planilla_deuda([_fila_deuda((1978, 11), (1979, 6))])
        fila = leer_deuda_excel(ruta).filas[0]
        self.assertEqual(fila.desde, Periodo(1978, 11))
        self.assertEqual(fila.hasta, Periodo(1979, 6))

    def test_interpreta_importes_anglosajones_con_espacio_duro(self):
        ruta = _planilla_deuda(
            [_fila_deuda((2020, 1), (2020, 1), capital="553,784.38",
                         intereses="5,093,435.52", total="5,647,219.90")]
        )
        fila = leer_deuda_excel(ruta).filas[0]
        self.assertEqual(fila.capital_subtotal, Decimal("553784.38"))
        self.assertEqual(fila.total, Decimal("5647219.90"))
        self.assertTrue(fila.coherente)

    def test_un_renglon_en_cero_esta_cancelado_y_no_adeuda(self):
        ruta = _planilla_deuda(
            [_fila_deuda((2020, 1), (2020, 1), meses="0",
                         capital="0.00", intereses="0.00", total="0.00")]
        )
        fila = leer_deuda_excel(ruta).filas[0]
        self.assertTrue(fila.cancelado)
        self.assertFalse(fila.adeuda)

    def test_reconoce_la_prescripcion_del_art_1(self):
        ruta = _planilla_deuda(
            [_fila_deuda((1994, 2), (1994, 2), beneficio="Art. 1 Ley 25321",
                         capital="0.00", intereses="0.00", total="0.00")]
        )
        lectura = leer_deuda_excel(ruta)
        self.assertTrue(lectura.filas[0].prescripto_art1)
        self.assertEqual(lectura.meses_prescriptos(), {Periodo(1994, 2)})

    def test_un_periodo_prescripto_no_cuenta_como_deuda(self):
        ruta = _planilla_deuda(
            [_fila_deuda((1994, 2), (1994, 2), beneficio="Art. 1 Ley 25321",
                         capital="0.00", intereses="0.00", total="0.00")]
        )
        self.assertEqual(leer_deuda_excel(ruta).meses_con_deuda(), set())

    def test_separa_cancelados_de_adeudados(self):
        ruta = _planilla_deuda([
            _fila_deuda((2020, 1), (2020, 2), meses="0",
                        capital="0.00", intereses="0.00", total="0.00"),
            _fila_deuda((2020, 3), (2020, 4), total="150.00"),
        ])
        lectura = leer_deuda_excel(ruta)
        self.assertEqual(len(lectura.meses_cancelados()), 2)
        self.assertEqual(len(lectura.meses_con_deuda()), 2)

    def test_saltea_los_renglones_de_encabezado(self):
        ruta = _planilla_deuda([_fila_deuda((2020, 1), (2020, 1))])
        self.assertEqual(len(leer_deuda_excel(ruta).filas), 1)

    def test_omite_y_avisa_los_periodos_invertidos(self):
        ruta = _planilla_deuda([
            _fila_deuda((2020, 5), (2019, 1)),
            _fila_deuda((2020, 1), (2020, 1)),
        ])
        lectura = leer_deuda_excel(ruta)
        self.assertEqual(len(lectura.filas), 1)
        self.assertTrue(any("invertido" in a for a in lectura.advertencias))

    def test_error_claro_si_la_planilla_no_tiene_renglones(self):
        ruta = _planilla_deuda([])
        with self.assertRaises(ErrorFuente):
            leer_deuda_excel(ruta)

    def test_error_claro_si_no_existe(self):
        with self.assertRaises(ErrorFuente):
            leer_deuda_excel("/no/existe.xlsx")


class PruebasRevista(unittest.TestCase):
    ENCABEZADO = [
        ["Situación de Revista", "", "", "", "", "", "", "", "", "Beneficios"],
        ["Período Inicio", "Periodo Cese.", "Código Actividad", "Tipo de Sociedad",
         "Categoría Optativa", "Fecha Matrícula", "Personal Ocupado",
         "Capacidad de Carga", "Hs. semanales trab.", "Período Desde",
         "Periodo Hasta", "Tipo de Beneficio"],
    ]

    def _ruta(self, filas):
        return _planilla(self.ENCABEZADO + filas)

    def test_lee_periodos_en_formato_mes_barra_anio(self):
        ruta = self._ruta([[f"11/1978{DURO}", f"04/1985{DURO}", f"746{DURO}"]])
        tramo = leer_revista_excel(ruta).periodos[0]
        self.assertEqual(tramo.inicio, Periodo(1978, 11))
        self.assertEqual(tramo.cese, Periodo(1985, 4))
        self.assertEqual(tramo.codigo_actividad, "746")

    def test_lee_el_rango_del_beneficio_y_su_norma(self):
        ruta = self._ruta([[
            f"10/1992{DURO}", f"12/1995{DURO}", f"902{DURO}", "", f"B*{DURO}",
            "", "", "", "", f"02/1994{DURO}", f"06/1994{DURO}",
            f"Art. 1 Ley 25321{DURO}",
        ]])
        tramo = leer_revista_excel(ruta).periodos[0]
        self.assertTrue(tramo.prescripto_art1)
        self.assertEqual(len(tramo.meses_beneficio()), 5)
        self.assertEqual(tramo.categoria_optativa, "B*")

    def test_un_tramo_sin_beneficio_no_tiene_meses_de_beneficio(self):
        ruta = self._ruta([[f"08/2001{DURO}", f"02/2002{DURO}", f"11{DURO}"]])
        tramo = leer_revista_excel(ruta).periodos[0]
        self.assertFalse(tramo.prescripto_art1)
        self.assertEqual(tramo.meses_beneficio(), set())

    def test_leer_revista_deriva_a_la_planilla(self):
        ruta = self._ruta([[f"11/1978{DURO}", f"04/1985{DURO}", f"746{DURO}"]])
        self.assertEqual(len(leer_revista(ruta).periodos), 1)

    def test_error_claro_si_no_hay_tramos(self):
        with self.assertRaises(ErrorFuente):
            leer_revista_excel(self._ruta([]))


if __name__ == "__main__":
    unittest.main()
