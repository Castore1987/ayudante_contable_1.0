"""Pruebas de los controles previsionales y el agrupamiento de hallazgos."""

import unittest
from decimal import Decimal

from ayudante_contable.analisis.parametros import ParametrosPrevisionales, TramoParametro
from ayudante_contable.analisis.validador import analizar
from ayudante_contable.modelo.dominio import EstadoIngreso, Periodo, Severidad
from tests.ayuda import historia, meses, parametros


def codigos(informe):
    return [h.codigo for h in informe.hallazgos]


class PruebasControlDeMinimo(unittest.TestCase):
    def test_agrupa_meses_consecutivos_en_un_solo_hallazgo(self):
        informe = analizar(
            historia(meses((2020, 1), (2020, 12), remuneracion="100")),
            parametros(base=Decimal("1000")),
        )
        bajos = [h for h in informe.hallazgos if h.codigo == "APORTE_BAJO_MINIMO"]
        self.assertEqual(len(bajos), 1)
        self.assertEqual(bajos[0].periodo, Periodo(2020, 1))
        self.assertEqual(bajos[0].periodo_fin, Periodo(2020, 12))
        self.assertEqual(bajos[0].severidad, Severidad.ERROR)

    def test_separa_los_rangos_discontinuos(self):
        informe = analizar(
            historia(
                meses((2020, 1), (2020, 3), remuneracion="100"),
                meses((2020, 4), (2020, 8), remuneracion="5000"),
                meses((2020, 9), (2020, 12), remuneracion="100"),
            ),
            parametros(base=Decimal("1000")),
        )
        bajos = [h for h in informe.hallazgos if h.codigo == "APORTE_BAJO_MINIMO"]
        self.assertEqual(len(bajos), 2)
        self.assertEqual([h.rango_texto for h in bajos], ["01/2020 a 03/2020", "09/2020 a 12/2020"])

    def test_separa_por_empleador(self):
        informe = analizar(
            historia(
                meses((2020, 1), (2020, 6), cuit="30111111112", empleador="A", remuneracion="100"),
                meses((2020, 1), (2020, 6), cuit="30222222224", empleador="B", remuneracion="100"),
            ),
            parametros(base=Decimal("1000")),
        )
        bajos = [h for h in informe.hallazgos if h.codigo == "APORTE_BAJO_MINIMO"]
        self.assertEqual({h.empleador for h in bajos}, {"A", "B"})

    def test_una_historia_correcta_no_arroja_errores(self):
        informe = analizar(historia(meses((2020, 1), (2020, 12))), parametros())
        self.assertEqual(informe.errores, [])
        self.assertTrue(informe.apto_para_certificar)


class PruebasControlDeIngreso(unittest.TestCase):
    def test_los_meses_impagos_son_error(self):
        informe = analizar(
            historia(meses((2020, 1), (2020, 6), estado=EstadoIngreso.NO_INGRESADO)), parametros()
        )
        impagos = [h for h in informe.hallazgos if h.codigo == "APORTE_NO_INGRESADO"]
        self.assertEqual(len(impagos), 1)
        self.assertEqual(impagos[0].severidad, Severidad.ERROR)
        self.assertFalse(informe.apto_para_certificar)

    def test_el_ingreso_parcial_es_advertencia(self):
        informe = analizar(
            historia(
                meses((2020, 1), (2020, 3), aporte_declarado="550", aporte_ingresado="100")
            ),
            parametros(),
        )
        self.assertIn("APORTE_INGRESO_PARCIAL", codigos(informe))
        self.assertEqual(informe.errores, [])

    def test_la_falta_de_dato_de_ingreso_es_advertencia(self):
        informe = analizar(
            historia(meses((2020, 1), (2020, 3), estado=EstadoIngreso.DESCONOCIDO)), parametros()
        )
        self.assertIn("APORTE_INGRESO_INCIERTO", codigos(informe))


class PruebasControlDeParametros(unittest.TestCase):
    def test_avisa_cuando_no_hay_bases_cargadas(self):
        informe = analizar(
            historia(meses((2020, 1), (2020, 6))),
            ParametrosPrevisionales(origen="(vacío)"),
        )
        self.assertIn("PARAMETROS_SIN_CARGAR", codigos(informe))

    def test_avisa_por_los_periodos_fuera_de_cobertura(self):
        informe = analizar(
            historia(meses((2018, 1), (2018, 6))), parametros(desde=(2020, 1))
        )
        sin_parametro = [h for h in informe.hallazgos if h.codigo == "SIN_PARAMETRO_BASE_MINIMA"]
        self.assertEqual(len(sin_parametro), 1)
        self.assertEqual(sin_parametro[0].rango_texto, "01/2018 a 06/2018")

    def test_avisa_por_los_tramos_sin_verificar(self):
        params = ParametrosPrevisionales(
            bases_minimas=[
                TramoParametro(Periodo(2020, 1), None, Decimal("1000"), verificado=False)
            ],
            origen="(prueba)",
        )
        informe = analizar(historia(meses((2020, 1), (2020, 6))), params)
        self.assertIn("PARAMETROS_NO_VERIFICADOS", codigos(informe))


class PruebasControlesInformativos(unittest.TestCase):
    def test_informa_los_empleos_simultaneos(self):
        informe = analizar(
            historia(
                meses((2020, 1), (2020, 6), cuit="30111111112", empleador="A"),
                meses((2020, 1), (2020, 6), cuit="30222222224", empleador="B"),
            ),
            parametros(),
        )
        self.assertIn("EMPLEOS_SIMULTANEOS", codigos(informe))

    def test_informa_las_lagunas(self):
        informe = analizar(
            historia(meses((2020, 1), (2020, 6)), meses((2021, 1), (2021, 6))), parametros()
        )
        self.assertIn("LAGUNA_PREVISIONAL", codigos(informe))


class PruebasIntegridadDelInforme(unittest.TestCase):
    def test_una_historia_vacia_es_error_y_no_silencio(self):
        informe = analizar(historia(), parametros())
        self.assertIn("SIN_REGISTROS", codigos(informe))
        self.assertFalse(informe.apto_para_certificar)

    def test_un_cuil_con_digito_verificador_malo_es_error(self):
        informe = analizar(
            historia(meses((2020, 1), (2020, 6)), cuil="20-12345678-5"), parametros()
        )
        self.assertIn("CUIL_INVALIDO", codigos(informe))

    def test_los_hallazgos_salen_ordenados_por_severidad(self):
        informe = analizar(
            historia(
                meses((2020, 1), (2020, 6), remuneracion="100"),
                meses((2021, 1), (2021, 6), estado=EstadoIngreso.NO_INGRESADO),
            ),
            parametros(base=Decimal("1000")),
        )
        ordenes = [h.severidad.orden for h in informe.hallazgos]
        self.assertEqual(ordenes, sorted(ordenes))

    def test_las_advertencias_de_la_fuente_llegan_al_informe(self):
        hl = historia(meses((2020, 1), (2020, 6)))
        hl.advertencias_origen.append("El PDF venía sin tablas.")
        informe = analizar(hl, parametros())
        self.assertIn("ORIGEN_DATOS", codigos(informe))

    def test_el_resumen_cierra_con_la_linea_de_servicios(self):
        informe = analizar(historia(meses((2020, 1), (2020, 12))), parametros())
        self.assertEqual(informe.resumen["meses_computables"], 12)
        self.assertEqual(informe.resumen["registros"], 12)
        self.assertEqual(informe.resumen["tramos"], 1)


if __name__ == "__main__":
    unittest.main()
