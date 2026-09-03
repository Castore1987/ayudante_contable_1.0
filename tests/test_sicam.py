"""Pruebas de SICAM: reglas de negocio y limpieza del OCR.

No se ejercita el OCR en sí (necesita tesseract y un PDF): se prueban las
piezas que deciden el resultado —limpieza de celdas, detección del Art. 1
Ley 25.321 y el cruce alta/deuda— con lecturas armadas a mano.
"""

import unittest
from decimal import Decimal

from ayudante_contable.fuentes import sicam
from ayudante_contable.fuentes.sicam import (
    FilaDeuda,
    LecturaDeuda,
    LecturaRevista,
    PeriodoRevista,
    PoliticaDeuda,
    historia_desde_sicam,
)
from ayudante_contable.modelo.dominio import EstadoIngreso, Periodo, TipoAporte

CUIL = "20-12345678-6"


def periodo(texto: str) -> Periodo:
    mes, anio = texto.split("/")
    return Periodo(int(anio), int(mes))


class PruebasLimpiezaOCR(unittest.TestCase):
    def test_quita_los_bordes_de_tabla(self):
        self.assertEqual(sicam._limpiar("[02/1994|"), "02/1994")
        self.assertEqual(sicam._limpiar("—_— B* _—_—"), "B*")

    def test_cierra_el_ano_partido_por_el_ocr(self):
        self.assertEqual(sicam._periodo("09/1 992"), Periodo(1992, 9))

    def test_lee_periodos_con_ruido_alrededor(self):
        self.assertEqual(sicam._periodo("| 05/2026 ||"), Periodo(2026, 5))

    def test_rechaza_lo_que_no_es_periodo(self):
        for texto in ("", "13/2020", "0.00", "B*"):
            self.assertIsNone(sicam._periodo(texto), texto)

    def test_reconoce_el_art1_pese_al_ruido(self):
        for texto in ("Art. 1 Ley 25321", "Art. 25321 Ley 111", "art 1 ley 25.321"):
            self.assertTrue(sicam._tiene_art1(texto), texto)

    def test_no_inventa_art1_donde_no_hay(self):
        for texto in ("", "B*", "0.00", "Ley 24.241"):
            self.assertFalse(sicam._tiene_art1(texto), texto)


class PruebasCoherenciaDeDeuda(unittest.TestCase):
    def _fila(self, capital, intereses, total):
        return FilaDeuda(
            desde=periodo("01/2000"),
            hasta=periodo("01/2000"),
            capital_subtotal=Decimal(capital),
            intereses_subtotal=Decimal(intereses),
            total=Decimal(total),
        )

    def test_un_renglon_que_cierra_es_coherente(self):
        self.assertTrue(self._fila("100.00", "50.00", "150.00").coherente)

    def test_todo_en_cero_es_coherente(self):
        self.assertTrue(self._fila("0", "0", "0").coherente)

    def test_un_total_que_no_cierra_queda_dudoso(self):
        """Es el control de calidad del OCR sobre los importes."""
        self.assertFalse(self._fila("100.00", "50.00", "1150.00").coherente)

    def test_la_deuda_se_define_por_el_total(self):
        self.assertTrue(self._fila("100", "50", "150").adeuda)
        self.assertFalse(self._fila("0", "0", "0").adeuda)
        self.assertTrue(self._fila("0", "0", "0").cancelado)


class PruebasCruceAltaContraDeuda(unittest.TestCase):
    def setUp(self):
        self.revista = LecturaRevista(
            periodos=[
                PeriodoRevista(
                    inicio=periodo("01/2020"),
                    cese=periodo("06/2020"),
                    codigo_actividad="11",
                ),
                PeriodoRevista(
                    inicio=periodo("01/2021"),
                    cese=periodo("03/2021"),
                    codigo_actividad="11",
                    beneficio_desde=periodo("01/2021"),
                    beneficio_hasta=periodo("02/2021"),
                    tipo_beneficio="Art. 1 Ley 25321",
                ),
            ]
        )
        self.deuda = LecturaDeuda(
            filas=[
                # 01-02/2020 cancelado
                FilaDeuda(periodo("01/2020"), periodo("02/2020"), total=Decimal("0")),
                # 03-04/2020 con deuda
                FilaDeuda(
                    periodo("03/2020"),
                    periodo("04/2020"),
                    capital_subtotal=Decimal("1000"),
                    intereses_subtotal=Decimal("500"),
                    total=Decimal("1500"),
                ),
                # 01-02/2021 prescripto
                FilaDeuda(
                    periodo("01/2021"),
                    periodo("02/2021"),
                    beneficio_aplicado="Art. 1 Ley 25321",
                    total=Decimal("0"),
                ),
            ]
        )

    def _historia(self, politica=None):
        return historia_desde_sicam(self.revista, self.deuda, CUIL, politica=politica)

    def test_sin_deuda_el_mes_figura_ingresado(self):
        registros = {r.periodo: r for r in self._historia().registros}
        self.assertEqual(registros[periodo("01/2020")].estado_ingreso, EstadoIngreso.INGRESADO)

    def test_la_deuda_se_considera_regularizada_por_defecto(self):
        """Criterio del estudio: la deuda que figura está en plan o moratoria."""
        registros = {r.periodo: r for r in self._historia().registros}
        registro = registros[periodo("03/2020")]
        self.assertEqual(registro.estado_ingreso, EstadoIngreso.REGULARIZADO)
        self.assertIn("regularizada", registro.observaciones)

    def test_la_deuda_regularizada_computa_como_servicio(self):
        from ayudante_contable.analisis.evaluacion import evaluar_registro
        from tests.ayuda import parametros

        registros = {r.periodo: r for r in self._historia().registros}
        evaluacion = evaluar_registro(registros[periodo("03/2020")], parametros())
        self.assertTrue(evaluacion.computa_servicio)
        self.assertTrue(evaluacion.computa_con_reservas)

    def test_con_la_politica_inversa_la_deuda_no_computa(self):
        from ayudante_contable.analisis.evaluacion import evaluar_registro
        from tests.ayuda import parametros

        historia = self._historia(PoliticaDeuda(deuda_es_regularizada=False))
        registros = {r.periodo: r for r in historia.registros}
        registro = registros[periodo("03/2020")]
        self.assertEqual(registro.estado_ingreso, EstadoIngreso.NO_INGRESADO)
        self.assertFalse(evaluar_registro(registro, parametros()).computa_servicio)

    def test_el_art1_marca_el_periodo_como_prescripto(self):
        registros = {r.periodo: r for r in self._historia().registros}
        registro = registros[periodo("01/2021")]
        self.assertEqual(registro.estado_ingreso, EstadoIngreso.PRESCRIPTO)
        self.assertIn("25.321", registro.observaciones)

    def test_un_periodo_prescripto_no_computa_ni_se_reclama(self):
        from ayudante_contable.analisis.evaluacion import evaluar_registro
        from tests.ayuda import parametros

        registros = {r.periodo: r for r in self._historia().registros}
        evaluacion = evaluar_registro(registros[periodo("01/2021")], parametros())
        self.assertTrue(evaluacion.prescripto)
        self.assertFalse(evaluacion.computa_servicio)
        self.assertFalse(evaluacion.no_ingresado)

    def test_se_puede_desactivar_la_prescripcion(self):
        historia = self._historia(PoliticaDeuda(aplicar_prescripcion_art1=False))
        registros = {r.periodo: r for r in historia.registros}
        self.assertNotEqual(
            registros[periodo("01/2021")].estado_ingreso, EstadoIngreso.PRESCRIPTO
        )

    def test_un_mes_de_alta_sin_renglon_de_deuda_queda_sin_dato(self):
        registros = {r.periodo: r for r in self._historia().registros}
        self.assertEqual(registros[periodo("05/2020")].estado_ingreso, EstadoIngreso.DESCONOCIDO)

    def test_los_meses_son_de_autonomo_y_cuentan_como_servicio(self):
        for registro in self._historia().registros:
            self.assertEqual(registro.tipo, TipoAporte.AUTONOMO)
            self.assertTrue(registro.servicio_reconocido)

    def test_la_politica_queda_asentada_en_el_informe(self):
        historia = self._historia()
        self.assertTrue(
            any("Política aplicada" in a for a in historia.advertencias_origen)
        )

    def test_sin_detalle_de_deuda_no_se_afirma_nada_del_ingreso(self):
        """Sin tabla de deuda no se puede decir si un mes está pagado.

        La prescripción, en cambio, sigue valiendo: viene de la situación de
        revista y no depende del detalle de deuda.
        """
        historia = historia_desde_sicam(self.revista, None, CUIL)
        estados = {r.estado_ingreso for r in historia.registros}
        self.assertEqual(estados, {EstadoIngreso.DESCONOCIDO, EstadoIngreso.PRESCRIPTO})
        sin_prescribir = [
            r for r in historia.registros if r.estado_ingreso != EstadoIngreso.PRESCRIPTO
        ]
        self.assertTrue(sin_prescribir)
        for registro in sin_prescribir:
            self.assertEqual(registro.estado_ingreso, EstadoIngreso.DESCONOCIDO)
        self.assertTrue(any("sin detalle de deuda" in a for a in historia.advertencias_origen))


if __name__ == "__main__":
    unittest.main()
