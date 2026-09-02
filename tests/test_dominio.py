"""Pruebas del modelo de dominio."""

import unittest
from decimal import Decimal

from ayudante_contable.modelo.dominio import (
    EstadoIngreso,
    HistoriaLaboral,
    Periodo,
    RegistroMensual,
    TipoAporte,
    cuil_valido,
    formatear_cuil,
    normalizar_cuil,
)


class PruebasPeriodo(unittest.TestCase):
    def test_parsea_formatos_habituales(self):
        esperado = Periodo(2023, 3)
        for texto in ("03/2023", "3/2023", "2023-03", "202303", "3-2023"):
            self.assertEqual(Periodo.desde_texto(texto), esperado, texto)

    def test_rechaza_texto_ilegible(self):
        for texto in ("marzo 2023", "13/2023", "", "2023"):
            with self.assertRaises((ValueError, TypeError), msg=texto):
                Periodo.desde_texto(texto)

    def test_aritmetica_cruza_el_fin_de_ano(self):
        self.assertEqual(Periodo(2023, 12) + 1, Periodo(2024, 1))
        self.assertEqual(Periodo(2024, 1) - 1, Periodo(2023, 12))
        self.assertEqual(Periodo(2024, 3) - Periodo(2023, 3), 12)

    def test_ordena_cronologicamente(self):
        self.assertLess(Periodo(2023, 12), Periodo(2024, 1))
        self.assertEqual(
            sorted([Periodo(2024, 1), Periodo(2023, 5)]), [Periodo(2023, 5), Periodo(2024, 1)]
        )

    def test_rango_es_inclusivo_y_vacio_si_esta_invertido(self):
        self.assertEqual(len(list(Periodo.rango(Periodo(2023, 1), Periodo(2023, 3)))), 3)
        self.assertEqual(list(Periodo.rango(Periodo(2023, 3), Periodo(2023, 1))), [])

    def test_formato_de_salida(self):
        self.assertEqual(str(Periodo(2023, 3)), "03/2023")
        self.assertEqual(Periodo(2023, 3).compacto, "202303")


class PruebasCUIL(unittest.TestCase):
    def test_normaliza_y_formatea(self):
        self.assertEqual(normalizar_cuil("20-12345678-6"), "20123456786")
        self.assertEqual(formatear_cuil("20123456786"), "20-12345678-6")

    def test_rechaza_longitud_incorrecta(self):
        with self.assertRaises(ValueError):
            normalizar_cuil("2012345678")

    def test_verifica_digito_verificador(self):
        self.assertTrue(cuil_valido("20-12345678-6"))
        self.assertFalse(cuil_valido("20-12345678-5"))
        self.assertFalse(cuil_valido("no es un cuil"))


class PruebasRegistro(unittest.TestCase):
    def _registro(self, **extra):
        base = dict(periodo=Periodo(2024, 1), remuneracion_imponible=Decimal("100"))
        base.update(extra)
        return RegistroMensual(**base)

    def test_el_cuit_manda_como_clave(self):
        registro = self._registro(cuit_empleador="30111111112", empleador="ACME")
        self.assertEqual(registro.clave_empleador, "30111111112")

    def test_sin_cuit_el_regimen_separa_los_tramos(self):
        mono = self._registro(empleador="Actividad independiente", tipo=TipoAporte.MONOTRIBUTO)
        autonomo = self._registro(empleador="Actividad independiente", tipo=TipoAporte.AUTONOMO)
        self.assertNotEqual(mono.clave_empleador, autonomo.clave_empleador)

    def test_nombre_visible_cae_en_cascada(self):
        self.assertEqual(self._registro(empleador="ACME").nombre_visible, "ACME")
        self.assertEqual(self._registro(cuit_empleador="30111111112").nombre_visible, "30111111112")
        self.assertEqual(
            self._registro(tipo=TipoAporte.AUTONOMO).nombre_visible, "Autónomo"
        )


class PruebasEnumeraciones(unittest.TestCase):
    def test_tipo_aporte_tolera_tildes_y_variantes(self):
        self.assertEqual(
            TipoAporte.desde_texto("Relación de Dependencia"), TipoAporte.RELACION_DEPENDENCIA
        )
        self.assertEqual(TipoAporte.desde_texto("AUTONOMOS"), TipoAporte.AUTONOMO)
        self.assertEqual(TipoAporte.desde_texto("cualquier cosa"), TipoAporte.DESCONOCIDO)
        self.assertEqual(TipoAporte.desde_texto(None), TipoAporte.DESCONOCIDO)

    def test_estado_ingreso_interpreta_marcas_frecuentes(self):
        self.assertEqual(EstadoIngreso.desde_texto("SI"), EstadoIngreso.INGRESADO)
        self.assertEqual(EstadoIngreso.desde_texto("no ingresado"), EstadoIngreso.NO_INGRESADO)
        self.assertEqual(EstadoIngreso.desde_texto("sin dato"), EstadoIngreso.DESCONOCIDO)


class PruebasHistoriaLaboral(unittest.TestCase):
    def test_ordena_los_registros_al_construirse(self):
        historia = HistoriaLaboral(
            cuil="20-12345678-6",
            registros=[
                RegistroMensual(periodo=Periodo(2024, 5)),
                RegistroMensual(periodo=Periodo(2023, 1)),
            ],
        )
        self.assertEqual(historia.periodo_inicial, Periodo(2023, 1))
        self.assertEqual(historia.periodo_final, Periodo(2024, 5))
        self.assertEqual(historia.cuil, "20123456786")


if __name__ == "__main__":
    unittest.main()
