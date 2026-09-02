"""Pruebas de los importadores: planilla, PDF y contrato de credenciales."""

import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from ayudante_contable.fuentes.base import CredencialesANSES, ErrorFuente
from ayudante_contable.fuentes.pdf_anses import _registros_desde_lineas
from ayudante_contable.fuentes.planilla import leer_planilla, parsear_decimal
from ayudante_contable.modelo.dominio import EstadoIngreso, Periodo, TipoAporte

CUIL = "20-12345678-6"

PLANILLA_BASE = """Período;CUIT Empleador;Razón Social;Régimen;Remuneración Imponible;Aporte Declarado;Aporte Ingresado;Estado
01/2023;30-11111111-2;ACME SA;Relación de dependencia;150.000,00;16.500,00;16.500,00;ingresado
02/2023;30-11111111-2;ACME SA;Relación de dependencia;150.000,00;16.500,00;0,00;no ingresado
"""


def escribir(contenido: str, nombre: str = "hl.csv", codificacion: str = "utf-8") -> Path:
    carpeta = Path(tempfile.mkdtemp())
    ruta = carpeta / nombre
    ruta.write_text(contenido, encoding=codificacion)
    return ruta


class PruebasNumeros(unittest.TestCase):
    def test_formato_argentino(self):
        self.assertEqual(parsear_decimal("1.234,56"), Decimal("1234.56"))
        self.assertEqual(parsear_decimal("$ 1.234.567,89"), Decimal("1234567.89"))
        self.assertEqual(parsear_decimal("980,00"), Decimal("980.00"))

    def test_formato_anglosajon(self):
        self.assertEqual(parsear_decimal("1,234.56"), Decimal("1234.56"))
        self.assertEqual(parsear_decimal("1234.56"), Decimal("1234.56"))

    def test_separador_de_miles_sin_decimales(self):
        self.assertEqual(parsear_decimal("1.234"), Decimal("1234"))
        self.assertEqual(parsear_decimal("1,234"), Decimal("1234"))

    def test_valores_ausentes_e_ilegibles(self):
        for valor in (None, "", "  ", "-", "n/d"):
            self.assertIsNone(parsear_decimal(valor), valor)

    def test_negativos_y_tipos_nativos(self):
        self.assertEqual(parsear_decimal("-500,25"), Decimal("-500.25"))
        self.assertEqual(parsear_decimal(1500), Decimal("1500"))


class PruebasPlanilla(unittest.TestCase):
    def test_lee_una_planilla_completa(self):
        historia = leer_planilla(escribir(PLANILLA_BASE), CUIL, nombre="PEREZ, JUAN")
        self.assertEqual(len(historia), 2)
        primero = historia.registros[0]
        self.assertEqual(primero.periodo, Periodo(2023, 1))
        self.assertEqual(primero.cuit_empleador, "30111111112")
        self.assertEqual(primero.empleador, "ACME SA")
        self.assertEqual(primero.tipo, TipoAporte.RELACION_DEPENDENCIA)
        self.assertEqual(primero.remuneracion_imponible, Decimal("150000.00"))
        self.assertEqual(primero.estado_ingreso, EstadoIngreso.INGRESADO)
        self.assertEqual(historia.registros[1].estado_ingreso, EstadoIngreso.NO_INGRESADO)

    def test_acepta_coma_como_separador_de_columnas(self):
        contenido = "Periodo,Remuneracion\n01/2023,1000.00\n02/2023,1000.00\n"
        historia = leer_planilla(escribir(contenido), CUIL)
        self.assertEqual(len(historia), 2)

    def test_acepta_encabezados_sin_tildes_y_en_otro_orden(self):
        contenido = "Razon Social;Remuneracion imponible;Periodo\nACME;1000,00;05/2021\n"
        historia = leer_planilla(escribir(contenido), CUIL)
        self.assertEqual(historia.registros[0].periodo, Periodo(2021, 5))
        self.assertEqual(historia.registros[0].empleador, "ACME")

    def test_saltea_las_filas_de_titulo_previas_al_encabezado(self):
        contenido = (
            "ANSES - Historia Laboral\n"
            "Consulta del 01/03/2024\n"
            "\n"
            "Período;Remuneración Imponible\n"
            "01/2023;1000,00\n"
        )
        historia = leer_planilla(escribir(contenido), CUIL)
        self.assertEqual(len(historia), 1)

    def test_lee_archivos_en_latin_1(self):
        ruta = escribir(
            "Período;Razón Social;Remuneración\n01/2023;ÑANDÚ SA;1000,00\n",
            codificacion="latin-1",
        )
        historia = leer_planilla(ruta, CUIL)
        self.assertEqual(historia.registros[0].empleador, "ÑANDÚ SA")

    def test_omite_las_filas_con_periodo_ilegible_y_avisa(self):
        contenido = "Período;Remuneración\n01/2023;1000,00\nsubtotal;9999,00\n02/2023;1000,00\n"
        historia = leer_planilla(escribir(contenido), CUIL)
        self.assertEqual(len(historia), 2)
        self.assertTrue(any("ilegible" in a for a in historia.advertencias_origen))

    def test_avisa_si_no_hay_datos_de_ingreso_efectivo(self):
        contenido = "Período;Remuneración\n01/2023;1000,00\n"
        historia = leer_planilla(escribir(contenido), CUIL)
        self.assertTrue(any("ingreso efectivo" in a for a in historia.advertencias_origen))

    def test_error_claro_si_falta_la_columna_de_periodo(self):
        with self.assertRaises(ErrorFuente):
            leer_planilla(escribir("Empleador;Sueldo\nACME;1000\n"), CUIL)

    def test_error_claro_si_no_existe_el_archivo(self):
        with self.assertRaises(ErrorFuente):
            leer_planilla("/no/existe.csv", CUIL)

    def test_error_claro_si_el_archivo_esta_vacio(self):
        with self.assertRaises(ErrorFuente):
            leer_planilla(escribir(""), CUIL)

    def test_el_ejemplo_del_repo_se_lee_completo(self):
        ruta = Path(__file__).resolve().parents[1] / "ejemplos" / "historia_laboral_ejemplo.csv"
        historia = leer_planilla(ruta, CUIL)
        self.assertEqual(len(historia), 43)
        self.assertEqual(historia.periodo_inicial, Periodo(2022, 1))
        self.assertEqual(historia.periodo_final, Periodo(2025, 6))


class PruebasPDF(unittest.TestCase):
    TEXTO = (
        "ANSES — Historia laboral del CUIL 20-12345678-6\n"
        "03/2023 30-11111111-2 SUPERMERCADO DEL SOL SA 250.000,00 27.500,00 ingresado\n"
        "04/2023 30-11111111-2 SUPERMERCADO DEL SOL SA 250.000,00 27.500,00 sin ingreso\n"
        "Página 1 de 3\n"
    )

    def test_extrae_los_periodos_de_un_volcado_de_texto(self):
        registros = list(_registros_desde_lineas(self.TEXTO, "20123456786"))
        self.assertEqual(len(registros), 2)
        self.assertEqual(registros[0].periodo, Periodo(2023, 3))
        self.assertEqual(registros[0].cuit_empleador, "30111111112")
        self.assertEqual(registros[0].remuneracion_imponible, Decimal("250000.00"))
        self.assertEqual(registros[0].estado_ingreso, EstadoIngreso.INGRESADO)
        self.assertEqual(registros[1].estado_ingreso, EstadoIngreso.NO_INGRESADO)

    def test_no_confunde_el_cuil_del_titular_con_un_empleador(self):
        texto = "05/2023 20-12345678-6 100.000,00 11.000,00\n"
        registros = list(_registros_desde_lineas(texto, "20123456786"))
        self.assertEqual(len(registros), 1)
        self.assertIsNone(registros[0].cuit_empleador)


class PruebasCredenciales(unittest.TestCase):
    def test_nunca_expone_la_clave_al_imprimirse(self):
        credenciales = CredencialesANSES(CUIL, "ClaveSuperSecreta")
        for texto in (repr(credenciales), str(credenciales), f"{credenciales}"):
            self.assertNotIn("ClaveSuperSecreta", texto)

    def test_el_contexto_descarta_la_clave_al_salir(self):
        with CredencialesANSES(CUIL, "ClaveSuperSecreta") as credenciales:
            self.assertEqual(credenciales.clave, "ClaveSuperSecreta")
        with self.assertRaises(ErrorFuente):
            credenciales.clave

    def test_normaliza_el_cuil(self):
        self.assertEqual(CredencialesANSES(CUIL, "x").cuil, "20123456786")


if __name__ == "__main__":
    unittest.main()
