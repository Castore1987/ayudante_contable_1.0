"""Pruebas de la bóveda, la redacción de secretos y la auditoría."""

import json
import unittest.mock
import os
import tempfile
import unittest
from pathlib import Path

from ayudante_contable.seguridad.auditoria import RegistroAuditoria
from ayudante_contable.seguridad.boveda import Boveda, ErrorBoveda
from ayudante_contable.seguridad.redaccion import (
    enmascarar_cuil,
    limpiar_secretos,
    redactar,
    registrar_secreto,
)

CUIL = "20-12345678-6"
CLAVE = "ClaveDelClienteAAA1"
MAESTRA = "contrasena-maestra-larga"


class PruebasBoveda(unittest.TestCase):
    def setUp(self):
        self.carpeta = Path(tempfile.mkdtemp())
        self.ruta = self.carpeta / "boveda.json"

    def _boveda(self, maestra=MAESTRA):
        return Boveda(self.ruta, clave_maestra=maestra)

    def test_guarda_y_recupera_una_credencial(self):
        self._boveda().guardar_cliente(CUIL, CLAVE, alias="Cliente Uno")
        entrada = self._boveda().obtener_cliente(CUIL)
        self.assertEqual(entrada.clave, CLAVE)
        self.assertEqual(entrada.alias, "Cliente Uno")

    def test_el_archivo_en_disco_no_contiene_la_clave_en_claro(self):
        self._boveda().guardar_cliente(CUIL, CLAVE)
        crudo = self.ruta.read_text(encoding="utf-8")
        self.assertNotIn(CLAVE, crudo)
        self.assertNotIn("12345678", crudo)
        self.assertEqual(json.loads(crudo)["version"], 1)

    def test_el_archivo_queda_solo_para_el_dueno(self):
        self._boveda().guardar_cliente(CUIL, CLAVE)
        self.assertEqual(oct(self.ruta.stat().st_mode & 0o777), "0o600")

    def test_una_contrasena_maestra_equivocada_no_abre_la_boveda(self):
        self._boveda().guardar_cliente(CUIL, CLAVE)
        with self.assertRaises(ErrorBoveda):
            self._boveda(maestra="otra-contrasena-larga").obtener_cliente(CUIL)

    def test_un_archivo_alterado_no_pasa_desapercibido(self):
        self._boveda().guardar_cliente(CUIL, CLAVE)
        envoltorio = json.loads(self.ruta.read_text(encoding="utf-8"))
        envoltorio["contenido"] = envoltorio["contenido"][:-8] + "AAAAAAAA"
        self.ruta.write_text(json.dumps(envoltorio), encoding="utf-8")
        with self.assertRaises(ErrorBoveda):
            self._boveda().obtener_cliente(CUIL)

    def test_listar_no_expone_ninguna_clave(self):
        self._boveda().guardar_cliente(CUIL, CLAVE, alias="Cliente Uno")
        listado = self._boveda().listar()
        self.assertEqual(listado, [{"cuil": CUIL, "alias": "Cliente Uno", "nota": ""}])
        self.assertNotIn(CLAVE, json.dumps(listado))

    def test_eliminar_borra_la_entrada(self):
        boveda = self._boveda()
        boveda.guardar_cliente(CUIL, CLAVE)
        self.assertTrue(boveda.eliminar_cliente(CUIL))
        self.assertFalse(boveda.eliminar_cliente(CUIL))
        with self.assertRaises(ErrorBoveda):
            self._boveda().obtener_cliente(CUIL)

    def test_pedir_un_cuil_inexistente_da_un_error_claro(self):
        self._boveda().guardar_cliente(CUIL, CLAVE)
        with self.assertRaises(ErrorBoveda):
            self._boveda().obtener_cliente("27-11111111-4")

    def test_guardar_varios_clientes_no_pisa_los_anteriores(self):
        boveda = self._boveda()
        boveda.guardar_cliente(CUIL, CLAVE)
        boveda.guardar_cliente("27-22222222-3", "OtraClave123")
        self.assertEqual(len(self._boveda().listar()), 2)

    def test_rechaza_una_contrasena_maestra_corta_al_crearla(self):
        os.environ.pop("AYUDANTE_CLAVE_MAESTRA", None)
        boveda = Boveda(self.carpeta / "otra.json", clave_maestra=None)
        with unittest.mock.patch("getpass.getpass", return_value="corta"):
            with self.assertRaises(ErrorBoveda):
                boveda.guardar_cliente(CUIL, CLAVE)


class PruebasRedaccion(unittest.TestCase):
    def setUp(self):
        limpiar_secretos()

    def tearDown(self):
        limpiar_secretos()

    def test_tapa_la_clave_en_pares_clave_valor(self):
        self.assertNotIn("secreta123", redactar("clave=secreta123 y sigue"))
        self.assertNotIn("secreta123", redactar('{"password": "secreta123"}'))
        self.assertNotIn("secreta123", redactar("Clave de la Seguridad Social: secreta123"))
        self.assertNotIn("secreta123", redactar("contraseña = secreta123;"))

    def test_conserva_el_resto_del_mensaje(self):
        self.assertIn("y sigue", redactar("clave=secreta123 y sigue"))

    def test_tapa_los_secretos_registrados_aunque_esten_sueltos(self):
        registrar_secreto("ValorLiteralSecreto")
        self.assertNotIn("ValorLiteralSecreto", redactar("apareció ValorLiteralSecreto acá"))

    def test_no_registra_valores_demasiado_cortos(self):
        registrar_secreto("ab")
        self.assertIn("ab", redactar("texto con ab adentro"))

    def test_enmascara_el_cuil_dejando_el_verificador(self):
        self.assertEqual(enmascarar_cuil("20-12345678-6"), "20-****5678-6")
        self.assertEqual(enmascarar_cuil("20123456786"), "20-****5678-6")

    def test_permite_no_enmascarar_el_cuil_cuando_hace_falta(self):
        self.assertIn("20-12345678-6", redactar("cuil 20-12345678-6", incluir_cuil=False))


class PruebasAuditoria(unittest.TestCase):
    def setUp(self):
        self.ruta = Path(tempfile.mkdtemp()) / "auditoria.jsonl"

    def test_registra_eventos_en_orden(self):
        registro = RegistroAuditoria(self.ruta)
        registro.registrar("portal.login", CUIL)
        registro.registrar("analisis.local", CUIL, resultado="ok", periodos="12")
        eventos = registro.leer()
        self.assertEqual([e["accion"] for e in eventos], ["portal.login", "analisis.local"])
        self.assertEqual(eventos[1]["detalle"]["periodos"], "12")

    def test_nunca_escribe_el_cuil_completo(self):
        RegistroAuditoria(self.ruta).registrar("portal.login", CUIL)
        crudo = self.ruta.read_text(encoding="utf-8")
        self.assertNotIn("20-12345678-6", crudo)
        self.assertIn("20-****5678-6", crudo)

    def test_redacta_las_claves_que_lleguen_en_el_detalle(self):
        RegistroAuditoria(self.ruta).registrar("prueba", CUIL, mensaje="clave=Secreta12345")
        self.assertNotIn("Secreta12345", self.ruta.read_text(encoding="utf-8"))

    def test_el_archivo_queda_solo_para_el_dueno(self):
        RegistroAuditoria(self.ruta).registrar("prueba", CUIL)
        self.assertEqual(oct(self.ruta.stat().st_mode & 0o777), "0o600")

    def test_leer_un_registro_inexistente_devuelve_vacio(self):
        self.assertEqual(RegistroAuditoria(self.ruta).leer(), [])

    def test_el_limite_devuelve_los_ultimos_eventos(self):
        registro = RegistroAuditoria(self.ruta)
        for i in range(5):
            registro.registrar(f"evento.{i}", CUIL)
        self.assertEqual([e["accion"] for e in registro.leer(limite=2)], ["evento.3", "evento.4"])


if __name__ == "__main__":
    unittest.main()
