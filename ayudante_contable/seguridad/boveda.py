"""Bóveda cifrada de credenciales de clientes.

Las claves de la Seguridad Social se guardan cifradas con AES (Fernet) usando
una clave derivada por scrypt de una contraseña maestra que solo conoce el
estudio. La contraseña maestra nunca se persiste; se toma de la variable de
entorno ``AYUDANTE_CLAVE_MAESTRA`` o se pide por consola sin eco.

Guardar credenciales es opcional: el modo por defecto del CLI las pide en el
momento y las descarta al terminar. La bóveda existe para el estudio que
procesa muchos clientes por lote y decide asumir ese riesgo con los recaudos
correspondientes.
"""

from __future__ import annotations

import base64
import getpass
import json
import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..modelo.dominio import formatear_cuil, normalizar_cuil
from .redaccion import registrar_secreto

__all__ = ["Boveda", "ErrorBoveda", "EntradaCliente"]

VERSION_BOVEDA = 1
_SCRYPT_N = 2**15
_SCRYPT_R = 8
_SCRYPT_P = 1


class ErrorBoveda(Exception):
    """La bóveda no se pudo abrir, descifrar o escribir."""


def _dependencias():
    try:
        from cryptography.fernet import Fernet, InvalidToken
        from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
    except ImportError as exc:  # pragma: no cover - depende del entorno
        raise ErrorBoveda(
            "La bóveda necesita el paquete 'cryptography':  pip install cryptography"
        ) from exc
    return Fernet, InvalidToken, Scrypt


@dataclass(frozen=True)
class EntradaCliente:
    cuil: str
    clave: str
    alias: str = ""
    nota: str = ""

    def __repr__(self) -> str:
        return f"EntradaCliente(cuil={formatear_cuil(self.cuil)}, clave=<oculta>)"

    __str__ = __repr__


class Boveda:
    """Almacén cifrado ``CUIL -> credenciales``."""

    def __init__(self, ruta: str | Path, clave_maestra: str | None = None) -> None:
        self.ruta = Path(ruta)
        self._clave_maestra = clave_maestra
        self._datos: dict[str, dict[str, str]] | None = None

    # ------------------------------------------------------------- maestra
    def _obtener_clave_maestra(self, confirmar: bool = False) -> str:
        if self._clave_maestra:
            return self._clave_maestra

        desde_entorno = os.environ.get("AYUDANTE_CLAVE_MAESTRA")
        if desde_entorno:
            self._clave_maestra = desde_entorno
            return desde_entorno

        clave = getpass.getpass("Contraseña maestra de la bóveda: ")
        if confirmar:
            if clave != getpass.getpass("Repetila: "):
                raise ErrorBoveda("Las contraseñas no coinciden.")
        if len(clave) < 12:
            raise ErrorBoveda(
                "La contraseña maestra debe tener al menos 12 caracteres: protege "
                "las claves fiscales de tus clientes."
            )
        self._clave_maestra = clave
        return clave

    @staticmethod
    def _derivar(clave_maestra: str, sal: bytes) -> bytes:
        _, _, Scrypt = _dependencias()
        kdf = Scrypt(salt=sal, length=32, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P)
        return base64.urlsafe_b64encode(kdf.derive(clave_maestra.encode("utf-8")))

    # ------------------------------------------------------------ E/S disco
    def existe(self) -> bool:
        return self.ruta.exists()

    def _cargar(self) -> dict[str, dict[str, str]]:
        if self._datos is not None:
            return self._datos

        if not self.existe():
            self._datos = {}
            return self._datos

        Fernet, InvalidToken, _ = _dependencias()
        try:
            envoltorio = json.loads(self.ruta.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise ErrorBoveda(f"No pude leer la bóveda {self.ruta}: {exc}") from exc

        if envoltorio.get("version") != VERSION_BOVEDA:
            raise ErrorBoveda(
                f"Versión de bóveda no soportada: {envoltorio.get('version')!r}"
            )

        sal = base64.b64decode(envoltorio["sal"])
        clave = self._derivar(self._obtener_clave_maestra(), sal)
        try:
            texto = Fernet(clave).decrypt(envoltorio["contenido"].encode("ascii"))
        except InvalidToken as exc:
            raise ErrorBoveda(
                "Contraseña maestra incorrecta o bóveda alterada."
            ) from exc

        self._datos = json.loads(texto.decode("utf-8"))
        for entrada in self._datos.values():
            registrar_secreto(entrada.get("clave"))
        return self._datos

    def _guardar(self, datos: dict[str, dict[str, str]]) -> None:
        Fernet, _, _ = _dependencias()
        sal = secrets.token_bytes(16)
        clave = self._derivar(self._obtener_clave_maestra(confirmar=not self.existe()), sal)
        cifrado = Fernet(clave).encrypt(json.dumps(datos, ensure_ascii=False).encode("utf-8"))

        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        temporal = self.ruta.with_suffix(self.ruta.suffix + ".tmp")
        temporal.write_text(
            json.dumps(
                {
                    "version": VERSION_BOVEDA,
                    "sal": base64.b64encode(sal).decode("ascii"),
                    "contenido": cifrado.decode("ascii"),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        os.chmod(temporal, 0o600)
        temporal.replace(self.ruta)
        self._datos = datos

    # --------------------------------------------------------- operaciones
    def guardar_cliente(
        self, cuil: str, clave: str, alias: str = "", nota: str = ""
    ) -> None:
        cuil = normalizar_cuil(cuil)
        datos = dict(self._cargar())
        datos[cuil] = {"clave": clave, "alias": alias, "nota": nota}
        self._guardar(datos)
        registrar_secreto(clave)

    def obtener_cliente(self, cuil: str) -> EntradaCliente:
        cuil = normalizar_cuil(cuil)
        datos = self._cargar()
        if cuil not in datos:
            raise ErrorBoveda(
                f"No hay credenciales guardadas para {formatear_cuil(cuil)}."
            )
        entrada = datos[cuil]
        return EntradaCliente(
            cuil=cuil,
            clave=entrada["clave"],
            alias=entrada.get("alias", ""),
            nota=entrada.get("nota", ""),
        )

    def eliminar_cliente(self, cuil: str) -> bool:
        cuil = normalizar_cuil(cuil)
        datos = dict(self._cargar())
        if cuil not in datos:
            return False
        del datos[cuil]
        self._guardar(datos)
        return True

    def listar(self) -> list[dict[str, Any]]:
        """Lista los clientes guardados sin exponer ninguna clave."""
        return [
            {"cuil": formatear_cuil(cuil), "alias": e.get("alias", ""), "nota": e.get("nota", "")}
            for cuil, e in sorted(self._cargar().items())
        ]
