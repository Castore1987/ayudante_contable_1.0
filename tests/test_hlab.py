"""Pruebas del lector del HLAB de ANSES, sobre un documento sintético.

El fixture reproduce el formato real (secciones, columnas pegadas, renglones
vacíos) con datos inventados: ninguna historia laboral de un cliente entra al
repositorio.
"""

import unittest
from decimal import Decimal
from pathlib import Path

from ayudante_contable.analisis.parametros import ParametrosPrevisionales
from ayudante_contable.analisis.validador import analizar
from ayudante_contable.fuentes.hlab_anses import analizar_lineas, armar_historia
from ayudante_contable.modelo.dominio import EstadoIngreso, Periodo, TipoAporte

FIXTURE = Path(__file__).with_name("hlab_ejemplo.txt")
TABLA_REAL = Path(__file__).resolve().parents[1] / "datos" / "parametros_previsionales.json"


def lectura():
    return analizar_lineas(FIXTURE.read_text(encoding="utf-8").splitlines())


def historia():
    return armar_historia(lectura())


class PruebasCabecera(unittest.TestCase):
    def test_extrae_cuil_nombre_y_fecha_de_consulta(self):
        l = lectura()
        self.assertEqual(l.cuil, "20123456786")
        self.assertEqual(l.nombre, "GOMEZ MARIA LAURA")
        self.assertEqual(l.fecha_consulta, "15/03/2026 10:00:00")
        self.assertEqual(l.periodo_consulta, Periodo(2026, 3))

    def test_rechaza_un_cuil_que_no_corresponde_al_documento(self):
        from ayudante_contable.fuentes.base import ErrorFuente

        with self.assertRaises(ErrorFuente):
            armar_historia(lectura(), cuil="27-99999999-4")


class PruebasResumen(unittest.TestCase):
    def test_lee_la_linea_de_servicios_que_declara_anses(self):
        tramos = lectura().tramos_declarados
        self.assertEqual(len(tramos), 3)
        self.assertEqual((str(tramos[0].desde), str(tramos[0].hasta)), ("03/1990", "12/1991"))
        self.assertEqual(tramos[0].razon_social, "TEXTIL DEL PLATA")

    def test_saltea_el_renglon_del_resumen_sin_fechas(self):
        self.assertTrue(all(t.desde and t.hasta for t in lectura().tramos_declarados))


class PruebasServiciosAnterioresA94(unittest.TestCase):
    def test_expande_el_rango_anual_a_meses(self):
        pre94 = lectura().servicios_pre94
        self.assertEqual(len(pre94), 22)          # 10 meses de 1990 + 12 de 1991
        self.assertEqual(pre94[0].periodo, Periodo(1990, 3))
        self.assertEqual(pre94[-1].periodo, Periodo(1991, 12))

    def test_son_servicio_reconocido_sin_remuneracion(self):
        registro = lectura().servicios_pre94[0]
        self.assertTrue(registro.servicio_reconocido)
        self.assertTrue(registro.hay_servicio)
        self.assertFalse(registro.tiene_remuneracion)

    def test_el_renglon_00_00_no_inventa_antiguedad(self):
        anios = {r.periodo.anio for r in lectura().servicios_pre94}
        self.assertNotIn(1993, anios)


class PruebasDependenciaPosteriorA94(unittest.TestCase):
    def test_toma_la_remuneracion_imponible_no_la_total(self):
        registros = {r.periodo: r for r in lectura().registros_dependencia}
        # 04/2020: rem. total 900.000 pero imponible topeada en 173.945,70
        self.assertEqual(
            registros[Periodo(2020, 4)].remuneracion_imponible, Decimal("173945.70")
        )
        self.assertIn("900000.00", registros[Periodo(2020, 4)].observaciones)

    def test_separa_los_importes_que_el_pdf_pega(self):
        """'2.000.000,002.000.000,00' son dos columnas, no un número."""
        registros = {r.periodo: r for r in lectura().registros_dependencia}
        self.assertEqual(
            registros[Periodo(2020, 5)].remuneracion_imponible, Decimal("2000000.00")
        )

    def test_el_ingreso_queda_sin_dato_porque_el_hlab_no_lo_informa(self):
        for registro in lectura().registros_dependencia:
            self.assertEqual(registro.estado_ingreso, EstadoIngreso.DESCONOCIDO)

    def test_conserva_cuit_y_razon_social(self):
        registro = lectura().registros_dependencia[0]
        self.assertEqual(registro.cuit_empleador, "30111111112")
        self.assertEqual(registro.empleador, "INDUSTRIAS ACME SA")
        self.assertEqual(registro.tipo, TipoAporte.RELACION_DEPENDENCIA)


class PruebasAutonomosYMonotributo(unittest.TestCase):
    def setUp(self):
        self.registros = {
            (r.periodo, r.tipo): r
            for r in historia().registros
            if r.tipo in (TipoAporte.AUTONOMO, TipoAporte.MONOTRIBUTO)
        }

    def test_un_mes_con_pago_acreditado_figura_ingresado(self):
        registro = self.registros[(Periodo(2022, 1), TipoAporte.AUTONOMO)]
        self.assertEqual(registro.estado_ingreso, EstadoIngreso.INGRESADO)
        self.assertEqual(registro.aporte_ingresado, Decimal("5000.00"))

    def test_suma_los_pagos_del_mismo_periodo(self):
        # 04/2022 tiene dos conceptos: 3.000 + 2.000
        registro = self.registros[(Periodo(2022, 4), TipoAporte.AUTONOMO)]
        self.assertEqual(registro.aporte_ingresado, Decimal("5000.00"))

    def test_un_mes_de_alta_sin_pago_figura_no_ingresado(self):
        for mes in (3, 5, 6):
            registro = self.registros[(Periodo(2022, mes), TipoAporte.AUTONOMO)]
            self.assertEqual(registro.estado_ingreso, EstadoIngreso.NO_INGRESADO, mes)

    def test_un_pago_sin_alta_en_el_padron_igual_cuenta_como_servicio(self):
        registro = self.registros[(Periodo(2019, 11), TipoAporte.AUTONOMO)]
        self.assertEqual(registro.estado_ingreso, EstadoIngreso.INGRESADO)
        self.assertTrue(registro.servicio_reconocido)

    def test_un_padron_sin_detalle_de_pagos_no_prueba_deuda(self):
        """Sin tabla de pagos, la ausencia de pago es falta de dato, no deuda."""
        for mes in (1, 2, 3):
            registro = self.registros[(Periodo(2023, mes), TipoAporte.MONOTRIBUTO)]
            self.assertEqual(registro.estado_ingreso, EstadoIngreso.DESCONOCIDO, mes)

    def test_avisa_que_ese_padron_vino_sin_pagos(self):
        self.assertTrue(
            any("sin detalle" in a for a in historia().advertencias_origen),
            historia().advertencias_origen,
        )

    def test_reconoce_las_etiquetas_compuestas_del_padron(self):
        """'MONOTRIBUTO APORTANTE' es monotributo, no un régimen desconocido."""
        categoria = lectura().bloques_puc[1].categorias[0]
        self.assertEqual(categoria.tipo, TipoAporte.MONOTRIBUTO)

    def test_no_mezcla_los_pagos_entre_padrones(self):
        """Un pago de autónomo no puede dar por cancelado un mes de monotributo."""
        bloques = lectura().bloques_puc
        self.assertEqual(len(bloques), 2)
        self.assertEqual(len(bloques[0].pagos), 5)
        self.assertEqual(len(bloques[1].pagos), 0)


class PruebasAnalisisCompleto(unittest.TestCase):
    def setUp(self):
        self.informe = analizar(
            historia(), ParametrosPrevisionales.desde_archivo(TABLA_REAL)
        )

    def test_detecta_el_mes_por_debajo_del_minimo(self):
        bajos = [h for h in self.informe.hallazgos if h.codigo == "APORTE_BAJO_MINIMO"]
        self.assertEqual(len(bajos), 1)
        self.assertEqual(bajos[0].periodo, Periodo(2020, 3))

    def test_no_marca_como_baja_la_remuneracion_topeada(self):
        """04/2020 está en el tope máximo del período, no por debajo del mínimo."""
        evaluacion = next(
            e for e in self.informe.evaluaciones
            if e.periodo == Periodo(2020, 4) and e.registro.cuit_empleador
        )
        self.assertFalse(evaluacion.bajo_minimo)
        self.assertTrue(evaluacion.topeada)

    def test_reclama_solo_los_meses_de_autonomo_realmente_impagos(self):
        impagos = [h for h in self.informe.hallazgos if h.codigo == "APORTE_NO_INGRESADO"]
        self.assertTrue(impagos)
        for hallazgo in impagos:
            self.assertIn("Autónomo", hallazgo.empleador or "")

    def test_contrasta_el_computo_contra_el_resumen_de_anses(self):
        codigos = {h.codigo for h in self.informe.hallazgos}
        self.assertIn("MAS_QUE_ANSES", codigos)

    def test_arma_la_linea_de_servicios_con_fechas(self):
        tramos = self.informe.linea.tramos
        self.assertEqual(tramos[0].empleador, "TEXTIL DEL PLATA")
        self.assertEqual((str(tramos[0].inicio), str(tramos[0].fin)), ("03/1990", "12/1991"))


if __name__ == "__main__":
    unittest.main()
