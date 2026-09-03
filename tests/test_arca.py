"""Pruebas del lector del export «Aportes en Línea» de ARCA."""

import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from ayudante_contable.fuentes.arca_aportes import (
    es_aportes_arca,
    leer_aportes_arca,
)
from ayudante_contable.fuentes.base import ErrorFuente
from ayudante_contable.modelo.dominio import EstadoIngreso, Periodo, TipoAporte

CUIL = "20-12345678-6"

# Reproduce el export real: llega con extensión .xls pero es HTML, con
# cabecera de dos niveles (seguridad social y obra social).
EXPORT = """<html><head><title>Aportes en Linea</title></head><body><table>
<tr><td>CUIL</td><td>20123456786</td><td>Apellido y nombre</td><td>GOMEZ MARIA LAURA</td></tr>
<tr><td>Nota</td><td>Esta planilla muestra sus datos en relaci&oacute;n de dependencia.</td></tr>
<tr><td></td><td></td><td></td><td></td><td>Aportes de seguridad social</td><td>Aportes de obra social</td><td></td></tr>
<tr><td>Periodo</td><td>CUIT</td><td>Razon Social</td><td>Remun. total bruta</td>
    <td>Declarado</td><td>Depositado</td><td>Declarado</td><td>Depositado</td>
    <td>Obra social de destino</td><td>Contribuci&oacute;n patronal de obra social</td></tr>
<tr><td>202001</td><td>30-11111111-2</td><td>INDUSTRIAS ACME SA</td><td>60.000,00</td>
    <td>8.400,00</td><td>8.400,00</td><td>1.800,00</td><td>1.800,00</td><td>101 - OSDE</td><td>Pago</td></tr>
<tr><td>202002</td><td>30-11111111-2</td><td>INDUSTRIAS ACME SA</td><td>60.000,00</td>
    <td>8.400,00</td><td>0,00</td><td>1.800,00</td><td>0,00</td><td>101 - OSDE</td><td>Impago</td></tr>
<tr><td>202003</td><td>30-11111111-2</td><td>INDUSTRIAS ACME SA</td><td>60.000,00</td>
    <td>8.400,00</td><td>4.000,00</td><td>1.800,00</td><td>900,00</td><td>101 - OSDE</td><td>Pago</td></tr>
<tr><td>202004</td><td>30-11111111-2</td><td>INDUSTRIAS ACME SA</td><td>60.000,00</td>
    <td>0,00</td><td>0,00</td><td>0,00</td><td>0,00</td><td>-</td><td>Pago</td></tr>
</table></body></html>"""


def escribir(contenido: str, nombre: str = "Historico.xls") -> Path:
    ruta = Path(tempfile.mkdtemp()) / nombre
    ruta.write_text(contenido, encoding="utf-8")
    return ruta


class PruebasDeteccion(unittest.TestCase):
    def test_reconoce_el_export_por_su_titulo(self):
        self.assertTrue(es_aportes_arca(escribir(EXPORT)))

    def test_no_confunde_otro_html(self):
        self.assertFalse(es_aportes_arca(escribir("<html><body>otra cosa</body></html>")))


class PruebasLectura(unittest.TestCase):
    def setUp(self):
        self.historia = leer_aportes_arca(escribir(EXPORT))
        self.registros = {r.periodo: r for r in self.historia.registros}

    def test_lee_cuil_y_nombre_de_la_cabecera(self):
        self.assertEqual(self.historia.cuil, "20123456786")
        self.assertEqual(self.historia.nombre, "GOMEZ MARIA LAURA")

    def test_lee_todos_los_periodos(self):
        self.assertEqual(len(self.historia), 4)
        self.assertEqual(self.historia.periodo_inicial, Periodo(2020, 1))

    def test_depositado_igual_al_declarado_es_ingresado(self):
        registro = self.registros[Periodo(2020, 1)]
        self.assertEqual(registro.estado_ingreso, EstadoIngreso.INGRESADO)
        self.assertEqual(registro.aporte_declarado, Decimal("8400.00"))
        self.assertEqual(registro.aporte_ingresado, Decimal("8400.00"))

    def test_depositado_en_cero_con_declaracion_es_deuda(self):
        self.assertEqual(
            self.registros[Periodo(2020, 2)].estado_ingreso, EstadoIngreso.NO_INGRESADO
        )

    def test_depositado_menor_al_declarado_es_parcial(self):
        registro = self.registros[Periodo(2020, 3)]
        self.assertEqual(registro.estado_ingreso, EstadoIngreso.PARCIAL)
        self.assertIn("falta depositar", registro.observaciones)

    def test_sin_declaracion_ni_deposito_queda_sin_dato(self):
        """Cero declarado y cero depositado no es deuda: es ausencia de dato."""
        self.assertEqual(
            self.registros[Periodo(2020, 4)].estado_ingreso, EstadoIngreso.DESCONOCIDO
        )

    def test_toma_las_columnas_de_seguridad_social_no_las_de_obra_social(self):
        """El primer par Declarado/Depositado es el de seguridad social."""
        self.assertEqual(self.registros[Periodo(2020, 1)].aporte_declarado, Decimal("8400.00"))

    def test_conserva_cuit_razon_social_y_regimen(self):
        registro = self.registros[Periodo(2020, 1)]
        self.assertEqual(registro.cuit_empleador, "30111111112")
        self.assertEqual(registro.empleador, "INDUSTRIAS ACME SA")
        self.assertEqual(registro.tipo, TipoAporte.RELACION_DEPENDENCIA)

    def test_avisa_que_solo_cubre_relacion_de_dependencia(self):
        self.assertTrue(
            any("relación de dependencia" in a for a in self.historia.advertencias_origen)
        )


class PruebasErrores(unittest.TestCase):
    def test_rechaza_un_cuil_que_no_corresponde(self):
        with self.assertRaises(ErrorFuente):
            leer_aportes_arca(escribir(EXPORT), cuil="27-99999999-4")

    def test_error_claro_sin_encabezados(self):
        with self.assertRaises(ErrorFuente):
            leer_aportes_arca(escribir("<html><table><tr><td>a</td></tr></table></html>"), CUIL)

    def test_error_claro_si_no_existe(self):
        with self.assertRaises(ErrorFuente):
            leer_aportes_arca("/no/existe.xls", CUIL)


if __name__ == "__main__":
    unittest.main()
