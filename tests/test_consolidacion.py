"""Pruebas de la consolidación de varias fuentes."""

import unittest
from decimal import Decimal

from ayudante_contable.analisis.consolidacion import clase_de_fuente, consolidar
from ayudante_contable.modelo.dominio import (
    EstadoIngreso,
    HistoriaLaboral,
    Periodo,
    RegistroMensual,
    TipoAporte,
)

CUIL = "20-12345678-6"
CUIT = "30111111112"


def historia(fuente: str, *registros, cuil: str = CUIL) -> HistoriaLaboral:
    return HistoriaLaboral(cuil=cuil, registros=list(registros), fuente=fuente)


def registro(periodo, **extra):
    base = dict(
        periodo=periodo,
        cuit_empleador=CUIT,
        empleador="ACME SA",
        tipo=TipoAporte.RELACION_DEPENDENCIA,
    )
    base.update(extra)
    return RegistroMensual(**base)


ENERO = Periodo(2020, 1)


class PruebasClaseDeFuente(unittest.TestCase):
    def test_reduce_la_fuente_a_su_clase(self):
        self.assertEqual(clase_de_fuente("hlab-anses:archivo.pdf"), "hlab")
        self.assertEqual(clase_de_fuente("arca-aportes:x.xls"), "arca")
        self.assertEqual(clase_de_fuente("sicam:a.pdf+b.pdf"), "sicam")
        self.assertEqual(clase_de_fuente("planilla:x.csv"), "planilla")


class PruebasFusion(unittest.TestCase):
    def test_una_sola_fuente_pasa_sin_cambios(self):
        resultado = consolidar([historia("hlab:x", registro(ENERO))])
        self.assertEqual(len(resultado.historia), 1)
        self.assertEqual(resultado.conflictos, [])

    def test_la_remuneracion_imponible_la_manda_el_hlab(self):
        """ARCA informa la bruta; el mínimo se controla contra la imponible."""
        resultado = consolidar(
            [
                historia("hlab:x", registro(ENERO, remuneracion_imponible=Decimal("9750"))),
                historia("arca:y", registro(ENERO, remuneracion_imponible=Decimal("12350"))),
            ]
        )
        self.assertEqual(
            resultado.historia.registros[0].remuneracion_imponible, Decimal("9750")
        )

    def test_el_ingreso_efectivo_lo_manda_arca(self):
        resultado = consolidar(
            [
                historia(
                    "hlab:x",
                    registro(
                        ENERO,
                        remuneracion_imponible=Decimal("9750"),
                        estado_ingreso=EstadoIngreso.DESCONOCIDO,
                    ),
                ),
                historia(
                    "arca:y",
                    registro(
                        ENERO,
                        aporte_declarado=Decimal("1000"),
                        aporte_ingresado=Decimal("1000"),
                        estado_ingreso=EstadoIngreso.INGRESADO,
                    ),
                ),
            ]
        )
        fusionado = resultado.historia.registros[0]
        self.assertEqual(fusionado.estado_ingreso, EstadoIngreso.INGRESADO)
        self.assertEqual(fusionado.remuneracion_imponible, Decimal("9750"))
        self.assertEqual(fusionado.aporte_ingresado, Decimal("1000"))

    def test_no_marca_conflicto_entre_imponible_y_bruta(self):
        """Son conceptos distintos: la diferencia es esperada, no una contradicción."""
        resultado = consolidar(
            [
                historia("hlab:x", registro(ENERO, remuneracion_imponible=Decimal("9750"))),
                historia("arca:y", registro(ENERO, remuneracion_imponible=Decimal("12350"))),
            ]
        )
        self.assertEqual(resultado.conflictos, [])

    def test_marca_conflicto_cuando_dos_fuentes_del_mismo_tipo_difieren(self):
        resultado = consolidar(
            [
                historia("hlab:x", registro(ENERO, remuneracion_imponible=Decimal("9750"))),
                historia("planilla:y", registro(ENERO, remuneracion_imponible=Decimal("5000"))),
            ]
        )
        self.assertEqual(len(resultado.conflictos), 1)
        self.assertIn("remuneración imponible", resultado.conflictos[0].mensaje)

    def test_marca_conflicto_cuando_el_estado_del_aporte_difiere(self):
        resultado = consolidar(
            [
                historia("arca:x", registro(ENERO, estado_ingreso=EstadoIngreso.INGRESADO)),
                historia("sicam:y", registro(ENERO, estado_ingreso=EstadoIngreso.NO_INGRESADO)),
            ]
        )
        self.assertEqual(len(resultado.conflictos), 1)
        self.assertIn("estado del aporte", resultado.conflictos[0].mensaje)

    def test_desconocido_no_desplaza_a_una_fuente_que_sabe(self):
        resultado = consolidar(
            [
                historia("arca:x", registro(ENERO, estado_ingreso=EstadoIngreso.INGRESADO)),
                historia("hlab:y", registro(ENERO, estado_ingreso=EstadoIngreso.DESCONOCIDO)),
            ]
        )
        self.assertEqual(
            resultado.historia.registros[0].estado_ingreso, EstadoIngreso.INGRESADO
        )
        self.assertEqual(resultado.conflictos, [])

    def test_conserva_la_razon_social_mas_completa(self):
        """El HLAB trunca el nombre del empleador; ARCA lo trae entero."""
        resultado = consolidar(
            [
                historia("hlab:x", registro(ENERO, empleador="INDUSTRIAS DEL SUR SOC")),
                historia("arca:y", registro(ENERO, empleador="INDUSTRIAS DEL SUR SOCIEDAD ANONIMA")),
            ]
        )
        self.assertEqual(resultado.historia.registros[0].empleador, "INDUSTRIAS DEL SUR SOCIEDAD ANONIMA")

    def test_los_regimenes_distintos_no_se_fusionan(self):
        resultado = consolidar(
            [
                historia("hlab:x", registro(ENERO)),
                historia(
                    "sicam:y",
                    RegistroMensual(
                        periodo=ENERO,
                        empleador="Autónomo",
                        tipo=TipoAporte.AUTONOMO,
                        servicio_reconocido=True,
                    ),
                ),
            ]
        )
        self.assertEqual(len(resultado.historia), 2)

    def test_arrastra_las_advertencias_etiquetadas_por_fuente(self):
        una = historia("hlab:x", registro(ENERO))
        una.advertencias_origen.append("ojo con esto")
        resultado = consolidar([una, historia("arca:y", registro(ENERO))])
        self.assertTrue(
            any("[hlab] ojo con esto" == a for a in resultado.historia.advertencias_origen)
        )

    def test_rechaza_fuentes_de_clientes_distintos(self):
        with self.assertRaises(ValueError) as contexto:
            consolidar(
                [
                    historia("hlab:x", registro(ENERO)),
                    historia("arca:y", registro(ENERO), cuil="27-11111111-4"),
                ]
            )
        self.assertIn("CUIL distintos", str(contexto.exception))

    def test_rechaza_una_lista_vacia(self):
        with self.assertRaises(ValueError):
            consolidar([])


if __name__ == "__main__":
    unittest.main()
