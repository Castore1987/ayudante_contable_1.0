"""Adaptador del portal Mi ANSES mediante navegador automatizado.

Lo que este módulo *puede* hacer: abrir el portal, completar CUIL y Clave de la
Seguridad Social que aporta el estudio, esperar a que una persona resuelva el
CAPTCHA o el segundo factor, navegar hasta la historia laboral y descargar el
archivo para que lo procese el importador.

Lo que este módulo *no* puede hacer, y conviene tener claro antes de apoyarse en
él:

* ANSES no publica una API para esto. Se automatiza sobre el HTML del portal, y
  ese HTML cambia sin aviso: los selectores viven en ``selectores_mianses.json``
  justamente para poder corregirlos sin tocar código.
* El acceso suele estar protegido con CAPTCHA y/o código de verificación. Eso es
  deliberado: no se puede sortear sin intervención humana, y este módulo no lo
  intenta. Trabaja con una persona presente que resuelve el desafío.
* Automatizar el portal puede chocar con sus términos de uso. Verificá el
  encuadre con el cliente y dejá asentada la autorización antes de usarlo.

Por eso el flujo recomendado para producción es el importador de planillas: es
estable, no maneja credenciales y deja el archivo original como respaldo.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence

from ..modelo.dominio import HistoriaLaboral, formatear_cuil
from ..seguridad.auditoria import RegistroAuditoria
from ..seguridad.redaccion import redactar, registrar_secreto
from .base import CredencialesANSES, ErrorFuente

__all__ = ["ConfiguracionPortal", "SesionMiANSES", "ClienteMiANSES", "RUTA_SELECTORES"]

RUTA_SELECTORES = Path(__file__).with_name("selectores_mianses.json")


@dataclass
class ConfiguracionPortal:
    """Selectores y tiempos del portal, cargados desde JSON editable."""

    url_login: str
    url_historia_laboral: str
    espera_ms: int
    pasos: dict[str, list[str]]
    origen: str = str(RUTA_SELECTORES)

    @classmethod
    def cargar(cls, ruta: str | Path | None = None) -> "ConfiguracionPortal":
        ruta = Path(ruta) if ruta else RUTA_SELECTORES
        try:
            datos = json.loads(ruta.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ErrorFuente(f"No pude leer los selectores en {ruta}: {exc}") from exc
        return cls(
            url_login=datos["url_login"],
            url_historia_laboral=datos["url_historia_laboral"],
            espera_ms=int(datos.get("espera_ms", 20000)),
            pasos={k: list(v) for k, v in datos["pasos"].items()},
            origen=str(ruta),
        )

    def selectores(self, paso: str) -> list[str]:
        if paso not in self.pasos:
            raise ErrorFuente(f"No hay selectores configurados para el paso '{paso}'.")
        return self.pasos[paso]


@dataclass
class ResultadoDescarga:
    """Qué quedó en disco después de la sesión."""

    archivos: list[Path] = field(default_factory=list)
    capturas: list[Path] = field(default_factory=list)
    notas: list[str] = field(default_factory=list)


def _importar_playwright():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - depende del entorno
        raise ErrorFuente(
            "El acceso al portal necesita Playwright:\n"
            "    pip install playwright\n"
            "    playwright install chromium\n"
            "Si preferís no automatizar el portal, descargá la historia laboral a "
            "mano e importala con 'ayudante-contable analizar --planilla ARCHIVO'."
        ) from exc
    return sync_playwright


class SesionMiANSES:
    """Sesión de navegador contra Mi ANSES, con persona en el circuito.

    Uso previsto::

        with SesionMiANSES(config, carpeta_descargas) as sesion:
            sesion.iniciar_sesion(credenciales)
            resultado = sesion.descargar_historia_laboral()
    """

    def __init__(
        self,
        configuracion: ConfiguracionPortal,
        carpeta_descargas: str | Path,
        visible: bool = True,
        auditoria: RegistroAuditoria | None = None,
        confirmar: Callable[[str], bool] | None = None,
        modo_inspeccion: bool = False,
    ) -> None:
        self.configuracion = configuracion
        self.carpeta = Path(carpeta_descargas)
        self.carpeta.mkdir(parents=True, exist_ok=True)
        self.visible = visible
        self.auditoria = auditoria
        self.confirmar = confirmar or (lambda mensaje: _confirmar_por_consola(mensaje))
        self.modo_inspeccion = modo_inspeccion
        self._playwright = None
        self._navegador = None
        self._pagina = None

    # ----------------------------------------------------------- ciclo de vida
    def __enter__(self) -> "SesionMiANSES":
        sync_playwright = _importar_playwright()
        self._playwright = sync_playwright().start()
        self._navegador = self._playwright.chromium.launch(headless=not self.visible)
        contexto = self._navegador.new_context(accept_downloads=True)
        contexto.set_default_timeout(self.configuracion.espera_ms)
        self._pagina = contexto.new_page()
        return self

    def __exit__(self, *_excepcion) -> None:
        for recurso, cerrar in (
            (self._navegador, "close"),
            (self._playwright, "stop"),
        ):
            if recurso is not None:
                try:
                    getattr(recurso, cerrar)()
                except Exception:  # pragma: no cover - cierre best-effort
                    pass
        self._pagina = self._navegador = self._playwright = None

    @property
    def pagina(self):
        if self._pagina is None:
            raise ErrorFuente("La sesión no está abierta: usá 'with SesionMiANSES(...)'.")
        return self._pagina

    # -------------------------------------------------------------- utilidades
    def _primer_visible(self, paso: str, espera_ms: int = 3000):
        """Devuelve el primer selector del paso que exista en la página."""
        for selector in self.configuracion.selectores(paso):
            try:
                elemento = self.pagina.locator(selector).first
                elemento.wait_for(state="visible", timeout=espera_ms)
                if self.modo_inspeccion:
                    print(f"  ✓ {paso}: encontrado con {selector!r}")
                return elemento
            except Exception:
                continue
        if self.modo_inspeccion:
            print(f"  ✗ {paso}: ninguno de los selectores coincidió")
            print(f"    probados: {self.configuracion.selectores(paso)}")
        return None

    def _existe(self, paso: str, espera_ms: int = 1500) -> bool:
        return self._primer_visible(paso, espera_ms) is not None

    def capturar(self, nombre: str) -> Path:
        """Guarda una captura de pantalla para diagnóstico.

        Las capturas del portal contienen datos personales del cliente: quedan
        en la carpeta de trabajo con el resto del expediente, no en /tmp.
        """
        destino = self.carpeta / f"{nombre}-{int(time.time())}.png"
        try:
            self.pagina.screenshot(path=str(destino), full_page=True)
        except Exception as exc:  # pragma: no cover
            raise ErrorFuente(f"No pude tomar la captura: {redactar(exc)}") from exc
        return destino

    # ------------------------------------------------------------------ login
    def iniciar_sesion(self, credenciales: CredencialesANSES) -> None:
        """Completa el formulario y espera a que la persona resuelva los desafíos."""
        registrar_secreto(credenciales.clave)
        if self.auditoria:
            self.auditoria.registrar(
                "portal.login.inicio", credenciales.cuil, portal=self.configuracion.url_login
            )

        self.pagina.goto(self.configuracion.url_login)

        campo_cuil = self._primer_visible("campo_cuil")
        if campo_cuil is None:
            captura = self.capturar("login-sin-campo-cuil")
            raise ErrorFuente(
                "No encontré el campo de CUIL en la pantalla de ingreso. "
                f"El portal probablemente cambió: ajustá {self.configuracion.origen}. "
                f"Captura guardada en {captura}."
            )
        campo_cuil.fill(credenciales.cuil)

        campo_clave = self._primer_visible("campo_clave")
        if campo_clave is None:
            captura = self.capturar("login-sin-campo-clave")
            raise ErrorFuente(
                "No encontré el campo de clave. Ajustá los selectores en "
                f"{self.configuracion.origen}. Captura guardada en {captura}."
            )
        # fill() no deja el valor en el historial ni en el log de Playwright.
        campo_clave.fill(credenciales.clave)

        if self._existe("indicador_captcha"):
            if not self.confirmar(
                "El portal muestra un CAPTCHA. Resolvelo en la ventana del navegador "
                "y confirmá acá cuando esté listo."
            ):
                raise ErrorFuente("Ingreso cancelado por el operador en el CAPTCHA.")

        boton = self._primer_visible("boton_ingresar")
        if boton is None:
            captura = self.capturar("login-sin-boton")
            raise ErrorFuente(
                f"No encontré el botón de ingreso. Captura guardada en {captura}."
            )
        boton.click()

        if self._existe("indicador_segundo_factor", espera_ms=5000):
            if not self.confirmar(
                "El portal pide un código de verificación. Ingresalo en el navegador "
                "y confirmá acá cuando hayas entrado."
            ):
                raise ErrorFuente("Ingreso cancelado por el operador en el segundo factor.")

        if self._existe("indicador_credencial_invalida", espera_ms=3000):
            if self.auditoria:
                self.auditoria.registrar(
                    "portal.login", credenciales.cuil, resultado="credencial_rechazada"
                )
            raise ErrorFuente(
                f"El portal rechazó las credenciales de {formatear_cuil(credenciales.cuil)}. "
                "Verificá la Clave de la Seguridad Social con el cliente. "
                "Ojo: varios intentos fallidos pueden bloquear la cuenta."
            )

        if not self._existe("indicador_sesion_iniciada", espera_ms=self.configuracion.espera_ms):
            captura = self.capturar("login-sin-confirmar")
            raise ErrorFuente(
                "No pude confirmar que la sesión quedó iniciada. "
                f"Revisá la captura en {captura} y ajustá 'indicador_sesion_iniciada'."
            )

        if self.auditoria:
            self.auditoria.registrar("portal.login", credenciales.cuil, resultado="ok")

    # ------------------------------------------------------ historia laboral
    def descargar_historia_laboral(self) -> ResultadoDescarga:
        """Navega hasta la historia laboral y descarga lo que ofrezca el portal."""
        resultado = ResultadoDescarga()

        enlace = self._primer_visible("enlace_historia_laboral", espera_ms=8000)
        if enlace is not None:
            enlace.click()
        else:
            self.pagina.goto(self.configuracion.url_historia_laboral)
            resultado.notas.append(
                "No encontré el enlace a historia laboral; entré por URL directa."
            )

        boton = self._primer_visible("boton_descargar", espera_ms=8000)
        if boton is None:
            captura = self.capturar("historia-laboral")
            resultado.capturas.append(captura)
            resultado.notas.append(
                "No encontré el botón de descarga. Guardé una captura de la pantalla "
                f"({captura.name}) para que ajustes el selector 'boton_descargar'."
            )
            return resultado

        try:
            with self.pagina.expect_download(
                timeout=self.configuracion.espera_ms
            ) as espera_descarga:
                boton.click()
            descarga = espera_descarga.value
            destino = self.carpeta / (descarga.suggested_filename or "historia_laboral")
            descarga.save_as(str(destino))
            resultado.archivos.append(destino)
        except Exception as exc:
            captura = self.capturar("descarga-fallida")
            resultado.capturas.append(captura)
            resultado.notas.append(
                f"La descarga no se completó ({redactar(exc)}). Captura: {captura.name}"
            )

        return resultado


def _confirmar_por_consola(mensaje: str) -> bool:
    print(f"\n⏸  {mensaje}")
    respuesta = input("   ¿Seguimos? [s/N]: ").strip().lower()
    return respuesta in {"s", "si", "sí", "y", "yes"}


class ClienteMiANSES:
    """Fuente de alto nivel: entra al portal y devuelve la historia laboral.

    Descarga el archivo y lo procesa con el mismo importador que usa la ruta
    manual, así el análisis no depende de por dónde entraron los datos.
    """

    nombre = "mi-anses"

    def __init__(
        self,
        credenciales: CredencialesANSES,
        carpeta_trabajo: str | Path,
        configuracion: ConfiguracionPortal | None = None,
        visible: bool = True,
        auditoria: RegistroAuditoria | None = None,
    ) -> None:
        self.credenciales = credenciales
        self.carpeta = Path(carpeta_trabajo)
        self.configuracion = configuracion or ConfiguracionPortal.cargar()
        self.visible = visible
        self.auditoria = auditoria

    def obtener(self, cuil: str) -> HistoriaLaboral:
        if cuil and cuil != self.credenciales.cuil:
            raise ErrorFuente(
                "El CUIL pedido no coincide con el de las credenciales cargadas."
            )

        with SesionMiANSES(
            self.configuracion,
            self.carpeta,
            visible=self.visible,
            auditoria=self.auditoria,
        ) as sesion:
            sesion.iniciar_sesion(self.credenciales)
            resultado = sesion.descargar_historia_laboral()

        if not resultado.archivos:
            detalle = " ".join(resultado.notas) or "sin detalle"
            raise ErrorFuente(
                "Entré al portal pero no pude descargar la historia laboral: "
                f"{detalle}\n"
                "Descargala manualmente desde Mi ANSES y procesala con "
                "'ayudante-contable analizar --planilla ARCHIVO'."
            )

        archivo = resultado.archivos[0]
        historia = _procesar_descarga(archivo, self.credenciales.cuil)
        historia.fuente = f"mi-anses:{archivo.name}"
        historia.advertencias_origen.extend(resultado.notas)

        if self.auditoria:
            self.auditoria.registrar(
                "portal.historia_laboral",
                self.credenciales.cuil,
                archivo=archivo.name,
                periodos=str(len(historia)),
            )
        return historia


def _procesar_descarga(archivo: Path, cuil: str) -> HistoriaLaboral:
    """Deriva el archivo descargado al parser que corresponda por extensión."""
    sufijo = archivo.suffix.lower()
    if sufijo == ".pdf":
        from .pdf_anses import leer_pdf_historia_laboral

        return leer_pdf_historia_laboral(archivo, cuil)
    if sufijo in {".csv", ".tsv", ".txt", ".xlsx", ".xlsm"}:
        from .planilla import leer_planilla

        return leer_planilla(archivo, cuil)
    raise ErrorFuente(
        f"No sé cómo leer un archivo {sufijo or 'sin extensión'} ({archivo.name}). "
        "Convertilo a CSV o PDF y usá 'ayudante-contable analizar --planilla'."
    )


def inspeccionar_selectores(
    configuracion: ConfiguracionPortal, pasos: Sequence[str] | None = None
) -> dict[str, Any]:
    """Informe estático de los selectores configurados, sin abrir el navegador."""
    pasos = pasos or list(configuracion.pasos)
    return {
        "origen": configuracion.origen,
        "url_login": configuracion.url_login,
        "pasos": {paso: configuracion.pasos.get(paso, []) for paso in pasos},
    }
