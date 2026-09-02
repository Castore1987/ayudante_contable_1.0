"""Pruebas del armado de la línea de servicios."""

import unittest
from decimal import Decimal

from ayudante_contable.analisis.linea_servicios import construir_linea_servicios
from ayudante_contable.modelo.dominio import EstadoIngreso, Periodo, TipoAporte
from tests.ayuda import historia, meses, parametros


def linea(hl, params=None):
    return construir_linea_servicios(hl, params or parametros())


class PruebasTramos(unittest.TestCase):
    def test_un_empleo_continuo_da_un_solo_tramo(self):
        resultado = linea(historia(meses((2020, 3), (2022, 5))))
        self.assertEqual(len(resultado.tramos), 1)
        tramo = resultado.tramos[0]
        self.assertEqual(tramo.inicio, Periodo(2020, 3))
        self.assertEqual(tramo.fin, Periodo(2022, 5))
        self.assertEqual(tramo.meses_declarados, 27)
        self.assertTrue(tramo.continuo)

    def test_un_corte_parte_el_empleo_en_dos_tramos(self):
        resultado = linea(
            historia(meses((2020, 1), (2020, 6)), meses((2021, 1), (2021, 6)))
        )
        self.assertEqual(len(resultado.tramos), 2)
        self.assertEqual(resultado.tramos[0].fin, Periodo(2020, 6))
        self.assertEqual(resultado.tramos[1].inicio, Periodo(2021, 1))

    def test_la_tolerancia_configurada_no_corta_el_tramo(self):
        # Falta 07/2020; con tolerancia de 1 mes sigue siendo un solo empleo.
        hl = historia(meses((2020, 1), (2020, 6)), meses((2020, 8), (2020, 12)))
        resultado = linea(hl, parametros(meses_interrupcion_tolerada=1))
        self.assertEqual(len(resultado.tramos), 1)
        tramo = resultado.tramos[0]
        self.assertEqual(tramo.meses_declarados, 11)
        self.assertEqual(tramo.meses_calendario, 12)
        self.assertEqual(tramo.meses_faltantes, 1)
        self.assertFalse(tramo.continuo)

    def test_empleadores_distintos_dan_tramos_distintos(self):
        resultado = linea(
            historia(
                meses((2020, 1), (2020, 12), cuit="30111111112", empleador="A"),
                meses((2020, 1), (2020, 12), cuit="30222222224", empleador="B"),
            )
        )
        self.assertEqual(len(resultado.tramos), 2)
        self.assertEqual({t.empleador for t in resultado.tramos}, {"A", "B"})

    def test_los_tramos_salen_ordenados_por_fecha_de_inicio(self):
        resultado = linea(
            historia(
                meses((2022, 1), (2022, 6), cuit="30222222224", empleador="B"),
                meses((2020, 1), (2020, 6), cuit="30111111112", empleador="A"),
            )
        )
        self.assertEqual([t.empleador for t in resultado.tramos], ["A", "B"])

    def test_el_tramo_acumula_las_observaciones_del_periodo(self):
        hl = historia(
            meses((2020, 1), (2020, 3), remuneracion="100"),
            meses((2020, 4), (2020, 6), remuneracion="5000", estado=EstadoIngreso.NO_INGRESADO),
        )
        tramo = linea(hl, parametros(base=Decimal("1000"))).tramos[0]
        self.assertEqual(tramo.meses_bajo_minimo, 3)
        self.assertEqual(tramo.meses_sin_aporte_ingresado, 3)


class PruebasConsolidado(unittest.TestCase):
    def test_los_empleos_simultaneos_cuentan_una_sola_vez(self):
        resultado = linea(
            historia(
                meses((2020, 1), (2020, 12), cuit="30111111112", empleador="A"),
                meses((2020, 1), (2020, 12), cuit="30222222224", empleador="B"),
            )
        )
        self.assertEqual(resultado.meses_computables, 12)
        self.assertEqual(len(resultado.consolidado), 1)
        self.assertEqual(resultado.consolidado[0].empleadores, ("A", "B"))

    def test_empleos_encadenados_forman_un_intervalo_continuo(self):
        resultado = linea(
            historia(
                meses((2020, 1), (2020, 6), cuit="30111111112", empleador="A"),
                meses((2020, 7), (2020, 12), cuit="30222222224", empleador="B"),
            )
        )
        self.assertEqual(len(resultado.consolidado), 1)
        self.assertEqual(resultado.consolidado[0].inicio, Periodo(2020, 1))
        self.assertEqual(resultado.consolidado[0].fin, Periodo(2020, 12))
        self.assertEqual(resultado.meses_computables, 12)

    def test_la_antiguedad_se_expresa_en_anos_y_meses(self):
        resultado = linea(historia(meses((2020, 1), (2022, 3))))
        self.assertEqual(resultado.meses_computables, 27)
        self.assertEqual(resultado.antiguedad_texto, "2 año(s) y 3 mes(es)")
        self.assertEqual(resultado.anios_computables, Decimal("2.25"))


class PruebasMesesNoComputables(unittest.TestCase):
    def test_los_meses_sin_aporte_ingresado_no_suman_antiguedad(self):
        resultado = linea(
            historia(
                meses((2020, 1), (2020, 6)),
                meses((2020, 7), (2020, 12), estado=EstadoIngreso.NO_INGRESADO),
            )
        )
        self.assertEqual(resultado.meses_computables, 6)
        self.assertEqual(resultado.meses_descartados, 6)

    def test_otro_empleador_que_si_ingreso_rescata_el_mes(self):
        resultado = linea(
            historia(
                meses((2020, 1), (2020, 6), cuit="30111111112", estado=EstadoIngreso.NO_INGRESADO),
                meses((2020, 1), (2020, 6), cuit="30222222224"),
            )
        )
        self.assertEqual(resultado.meses_computables, 6)
        self.assertEqual(resultado.meses_descartados, 0)


class PruebasLagunas(unittest.TestCase):
    def test_detecta_el_hueco_entre_dos_empleos(self):
        resultado = linea(
            historia(meses((2020, 1), (2020, 6)), meses((2021, 1), (2021, 6)))
        )
        self.assertEqual(len(resultado.lagunas), 1)
        laguna = resultado.lagunas[0]
        self.assertEqual((laguna.inicio, laguna.fin, laguna.meses), (Periodo(2020, 7), Periodo(2020, 12), 6))

    def test_un_mes_impago_abre_una_laguna(self):
        resultado = linea(
            historia(
                meses((2020, 1), (2020, 5)),
                meses((2020, 6), (2020, 6), estado=EstadoIngreso.NO_INGRESADO),
                meses((2020, 7), (2020, 12)),
            )
        )
        self.assertEqual([l.meses for l in resultado.lagunas], [1])

    def test_no_inventa_lagunas_antes_del_primer_aporte_ni_despues_del_ultimo(self):
        resultado = linea(historia(meses((2020, 1), (2020, 12))))
        self.assertEqual(resultado.lagunas, [])

    def test_una_carrera_sin_interrupciones_no_tiene_lagunas(self):
        resultado = linea(historia(meses((1995, 4), (2025, 3))))
        self.assertEqual(resultado.lagunas, [])
        self.assertEqual(resultado.meses_computables, 360)


class PruebasHistoriaVacia(unittest.TestCase):
    def test_no_falla_con_una_historia_sin_registros(self):
        resultado = linea(historia())
        self.assertEqual(resultado.tramos, [])
        self.assertEqual(resultado.meses_computables, 0)
        self.assertIsNone(resultado.primer_periodo)


class PruebasRegimenes(unittest.TestCase):
    def test_el_paso_de_monotributo_a_autonomo_son_dos_tramos(self):
        resultado = linea(
            historia(
                meses(
                    (2020, 1), (2020, 6), cuit=None,
                    empleador="Actividad independiente", tipo=TipoAporte.MONOTRIBUTO,
                ),
                meses(
                    (2020, 7), (2020, 12), cuit=None,
                    empleador="Actividad independiente", tipo=TipoAporte.AUTONOMO,
                ),
            )
        )
        self.assertEqual(len(resultado.tramos), 2)
        self.assertEqual(
            [t.tipo for t in resultado.tramos], [TipoAporte.MONOTRIBUTO, TipoAporte.AUTONOMO]
        )
        self.assertEqual(resultado.meses_computables, 12)


if __name__ == "__main__":
    unittest.main()
