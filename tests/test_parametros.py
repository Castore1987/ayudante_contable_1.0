"""Pruebas de la tabla de parámetros previsionales."""

import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from ayudante_contable.analisis.parametros import (
    ErrorParametros,
    ParametrosPrevisionales,
    TramoParametro,
)
from ayudante_contable.modelo.dominio import Periodo


class PruebasResolucion(unittest.TestCase):
    def setUp(self):
        self.parametros = ParametrosPrevisionales(
            bases_minimas=[
                TramoParametro(Periodo(2022, 1), Periodo(2022, 12), Decimal("100")),
                TramoParametro(Periodo(2023, 1), None, Decimal("200")),
            ]
        )

    def test_resuelve_el_tramo_correcto(self):
        self.assertEqual(self.parametros.base_minima(Periodo(2022, 6)).valor, Decimal("100"))
        self.assertEqual(self.parametros.base_minima(Periodo(2023, 1)).valor, Decimal("200"))
        self.assertEqual(self.parametros.base_minima(Periodo(2030, 8)).valor, Decimal("200"))

    def test_devuelve_none_antes_del_primer_tramo(self):
        self.assertIsNone(self.parametros.base_minima(Periodo(2021, 12)))

    def test_informa_los_periodos_sin_cobertura(self):
        sin_base = self.parametros.periodos_sin_base(
            [Periodo(2021, 11), Periodo(2021, 12), Periodo(2022, 5)]
        )
        self.assertEqual(sin_base, [Periodo(2021, 11), Periodo(2021, 12)])


class PruebasIntegridad(unittest.TestCase):
    def test_rechaza_tramos_solapados(self):
        with self.assertRaises(ErrorParametros):
            ParametrosPrevisionales(
                bases_minimas=[
                    TramoParametro(Periodo(2022, 1), Periodo(2022, 12), Decimal("100")),
                    TramoParametro(Periodo(2022, 6), None, Decimal("200")),
                ]
            )

    def test_rechaza_un_tramo_abierto_en_el_medio(self):
        with self.assertRaises(ErrorParametros):
            ParametrosPrevisionales(
                bases_minimas=[
                    TramoParametro(Periodo(2022, 1), None, Decimal("100")),
                    TramoParametro(Periodo(2023, 1), None, Decimal("200")),
                ]
            )

    def test_marca_los_tramos_sin_verificar(self):
        parametros = ParametrosPrevisionales(
            bases_minimas=[
                TramoParametro(Periodo(2022, 1), Periodo(2022, 12), Decimal("100"), verificado=True),
                TramoParametro(Periodo(2023, 1), None, Decimal("200"), verificado=False),
            ]
        )
        self.assertEqual(len(parametros.bases_no_verificadas()), 1)


def _tabla_del_repo() -> ParametrosPrevisionales:
    return ParametrosPrevisionales.desde_archivo(
        Path(__file__).resolve().parents[1] / "datos" / "parametros_previsionales.json"
    )


class PruebasPersistencia(unittest.TestCase):
    def test_ida_y_vuelta_por_disco(self):
        original = ParametrosPrevisionales(
            bases_minimas=[
                TramoParametro(
                    desde=Periodo(2024, 1),
                    hasta=None,
                    valor=Decimal("1234.56"),
                    maximo=Decimal("99999.99"),
                    norma="Res. X",
                    verificado=True,
                )
            ]
        )
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = Path(carpeta) / "p.json"
            original.guardar(ruta)
            recuperado = ParametrosPrevisionales.desde_archivo(ruta)
        tramo = recuperado.base_minima(Periodo(2024, 5))
        self.assertEqual(tramo.valor, Decimal("1234.56"))
        self.assertEqual(tramo.maximo, Decimal("99999.99"))
        self.assertEqual(tramo.norma, "Res. X")
        self.assertTrue(tramo.verificado)

    def test_la_tabla_del_repo_cubre_de_1994_a_2026_sin_huecos(self):
        """La tabla oficial cargada no debe tener saltos entre tramos."""
        parametros = _tabla_del_repo()
        self.assertEqual(len(parametros.bases_minimas), 82)
        for anterior, siguiente in zip(parametros.bases_minimas, parametros.bases_minimas[1:]):
            self.assertEqual(
                anterior.hasta.ordinal + 1,
                siguiente.desde.ordinal,
                f"hueco entre {anterior.hasta} y {siguiente.desde}",
            )
        desde, hasta = parametros.cobertura_bases
        self.assertEqual((str(desde), str(hasta)), ("04/1994", "03/2026"))

    def test_cada_tramo_tiene_minimo_menor_que_el_maximo(self):
        for tramo in _tabla_del_repo().bases_minimas:
            self.assertIsNotNone(tramo.maximo, f"tramo {tramo.desde} sin tope")
            self.assertLess(tramo.valor, tramo.maximo, f"tramo {tramo.desde}")

    def test_cada_tramo_cita_la_norma_que_lo_fija(self):
        for tramo in _tabla_del_repo().bases_minimas:
            self.assertTrue(tramo.norma.strip(), f"tramo {tramo.desde} sin norma")

    def test_la_tabla_del_repo_viaja_sin_verificar(self):
        """Extraída automáticamente: nadie del estudio la cotejó todavía."""
        parametros = _tabla_del_repo()
        self.assertEqual(len(parametros.bases_no_verificadas()), len(parametros.bases_minimas))

    def test_error_claro_si_falta_el_archivo(self):
        with self.assertRaises(ErrorParametros):
            ParametrosPrevisionales.desde_archivo("/no/existe/parametros.json")

    def test_error_claro_si_el_json_esta_roto(self):
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = Path(carpeta) / "roto.json"
            ruta.write_text("{ esto no es json", encoding="utf-8")
            with self.assertRaises(ErrorParametros):
                ParametrosPrevisionales.desde_archivo(ruta)

    def test_rechaza_una_version_de_esquema_desconocida(self):
        with self.assertRaises(ErrorParametros):
            ParametrosPrevisionales.desde_dict({"version": 99})


if __name__ == "__main__":
    unittest.main()
