"""Pruebas de la evaluación mes a mes: mínimo imponible e ingreso efectivo."""

import unittest
from decimal import Decimal

from ayudante_contable.analisis.evaluacion import evaluar_registro
from ayudante_contable.modelo.dominio import EstadoIngreso, Periodo, RegistroMensual
from tests.ayuda import parametros


def registro(**extra):
    base = dict(periodo=Periodo(2024, 1), remuneracion_imponible=Decimal("5000"))
    base.update(extra)
    return RegistroMensual(**base)


class PruebasMinimoImponible(unittest.TestCase):
    def test_marca_la_remuneracion_por_debajo_del_minimo(self):
        evaluacion = evaluar_registro(
            registro(remuneracion_imponible=Decimal("800")), parametros(base=Decimal("1000"))
        )
        self.assertTrue(evaluacion.bajo_minimo)
        self.assertEqual(evaluacion.faltante_base, Decimal("200"))

    def test_no_marca_la_remuneracion_igual_al_minimo(self):
        evaluacion = evaluar_registro(
            registro(remuneracion_imponible=Decimal("1000")), parametros(base=Decimal("1000"))
        )
        self.assertFalse(evaluacion.bajo_minimo)

    def test_tolera_un_desvio_menor_por_redondeo_de_liquidacion(self):
        # 995 está 0,5 % abajo de 1000: dentro de la tolerancia del 1 %.
        evaluacion = evaluar_registro(
            registro(remuneracion_imponible=Decimal("995")), parametros(base=Decimal("1000"))
        )
        self.assertFalse(evaluacion.bajo_minimo)

    def test_un_mes_sin_remuneracion_no_se_juzga_por_el_minimo(self):
        evaluacion = evaluar_registro(
            registro(remuneracion_imponible=Decimal("0")), parametros(base=Decimal("1000"))
        )
        self.assertFalse(evaluacion.bajo_minimo)

    def test_sin_parametro_no_emite_juicio(self):
        evaluacion = evaluar_registro(
            registro(periodo=Periodo(2015, 6)), parametros(desde=(2020, 1))
        )
        self.assertTrue(evaluacion.sin_parametro)
        self.assertFalse(evaluacion.bajo_minimo)


class PruebasIngresoEfectivo(unittest.TestCase):
    def test_el_estado_declarado_manda_cuando_dice_que_no_ingreso(self):
        evaluacion = evaluar_registro(
            registro(estado_ingreso=EstadoIngreso.NO_INGRESADO), parametros()
        )
        self.assertTrue(evaluacion.no_ingresado)
        self.assertFalse(evaluacion.computa_servicio)

    def test_monto_ingresado_en_cero_con_remuneracion_es_deuda(self):
        evaluacion = evaluar_registro(
            registro(aporte_declarado=Decimal("550"), aporte_ingresado=Decimal("0")), parametros()
        )
        self.assertTrue(evaluacion.no_ingresado)

    def test_monto_ingresado_menor_al_declarado_es_ingreso_parcial(self):
        evaluacion = evaluar_registro(
            registro(aporte_declarado=Decimal("550"), aporte_ingresado=Decimal("200")), parametros()
        )
        self.assertTrue(evaluacion.ingreso_parcial)
        self.assertTrue(evaluacion.computa_servicio)
        self.assertTrue(evaluacion.computa_con_reservas)

    def test_monto_ingresado_completo_es_ingreso_correcto(self):
        evaluacion = evaluar_registro(
            registro(aporte_declarado=Decimal("550"), aporte_ingresado=Decimal("550")), parametros()
        )
        self.assertEqual(evaluacion.estado_ingreso, EstadoIngreso.INGRESADO)
        self.assertFalse(evaluacion.computa_con_reservas)

    def test_sin_dato_de_ingreso_computa_pero_queda_señalado(self):
        evaluacion = evaluar_registro(registro(), parametros())
        self.assertTrue(evaluacion.ingreso_incierto)
        self.assertTrue(evaluacion.computa_servicio)
        self.assertTrue(evaluacion.computa_con_reservas)

    def test_un_mes_sin_remuneracion_no_computa_como_servicio(self):
        evaluacion = evaluar_registro(
            registro(remuneracion_imponible=Decimal("0")), parametros()
        )
        self.assertFalse(evaluacion.computa_servicio)


class PruebasCoherenciaDelAporte(unittest.TestCase):
    def test_acepta_el_aporte_que_sigue_la_alicuota(self):
        evaluacion = evaluar_registro(
            registro(remuneracion_imponible=Decimal("10000"), aporte_declarado=Decimal("1100")),
            parametros(),
        )
        self.assertEqual(evaluacion.aporte_esperado, Decimal("1100.00"))
        self.assertFalse(evaluacion.aporte_incoherente)

    def test_marca_el_aporte_que_no_guarda_relacion(self):
        evaluacion = evaluar_registro(
            registro(remuneracion_imponible=Decimal("10000"), aporte_declarado=Decimal("50")),
            parametros(),
        )
        self.assertTrue(evaluacion.aporte_incoherente)

    def test_sin_aporte_declarado_no_hay_juicio_de_coherencia(self):
        evaluacion = evaluar_registro(
            registro(remuneracion_imponible=Decimal("10000"), aporte_declarado=None), parametros()
        )
        self.assertFalse(evaluacion.aporte_incoherente)
        self.assertIsNone(evaluacion.desvio_relativo)


if __name__ == "__main__":
    unittest.main()
