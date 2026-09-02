# Ayudante contable previsional — historia laboral ANSES

Automatiza el trabajo mecánico y repetitivo sobre la historia laboral de un
afiliado: controla el mínimo imponible, verifica que los aportes hayan
ingresado de verdad y arma la línea de servicios con fechas de inicio y fin.

Lo que **no** hace: reemplazar el criterio profesional. El informe ordena los
datos y señala lo que no cierra; la conclusión y la certificación son tuyas.

---

## Qué controla

| Control | Qué detecta | Severidad |
|---|---|---|
| `APORTE_BAJO_MINIMO` | Remuneración imponible por debajo de la base mínima del período | error |
| `APORTE_NO_INGRESADO` | Meses declarados cuyo aporte nunca ingresó | error |
| `APORTE_INGRESO_PARCIAL` | El monto ingresado es menor al declarado | advertencia |
| `APORTE_INGRESO_INCIERTO` | La fuente no informa si el aporte ingresó | advertencia |
| `APORTE_INCOHERENTE` | El aporte no guarda relación con remuneración × alícuota | advertencia |
| `SIN_PARAMETRO_BASE_MINIMA` | Períodos sin base mínima cargada: **no se emitió juicio** | advertencia |
| `PARAMETROS_NO_VERIFICADOS` | Se usaron valores que nadie cotejó contra la norma | advertencia |
| `LAGUNA_PREVISIONAL` | Meses sin servicios computables entre el primer y el último aporte | información |
| `EMPLEOS_SIMULTANEOS` | Meses con más de un empleador (se computan una sola vez) | información |
| `CUIL_INVALIDO` / `SIN_REGISTROS` | Problemas con el dato de entrada | error |

Y produce la **línea de servicios**: cada relación laboral con su CUIT, régimen,
fecha de inicio, fecha de fin, meses declarados y observaciones; más el
consolidado de antigüedad sin duplicar meses de empleo simultáneo.

---

## Cómo entran los datos: dos caminos

### 1. Importar la historia laboral descargada — **recomendado**

Descargás la historia laboral desde Mi ANSES y la importás. Es estable, no toca
credenciales, no depende del HTML del portal y deja el archivo original como
respaldo del informe.

```bash
ayudante-contable analizar \
  --cuil 20-12345678-6 \
  --nombre "PEREZ, JUAN CARLOS" \
  --planilla historia_laboral.csv \
  --todo
```

Acepta CSV, TSV, XLSX y PDF (`--pdf`). El mapeo de columnas tolera los nombres
habituales en castellano, con o sin tildes y en cualquier orden.

### 2. Entrar al portal con las credenciales del cliente

```bash
ayudante-contable anses --cuil 20-12345678-6 --todo
```

Abre un navegador visible, completa CUIL y Clave de la Seguridad Social, **se
detiene para que una persona resuelva el CAPTCHA o el código de verificación**,
navega hasta la historia laboral y descarga el archivo.

Antes de apoyarte en este camino, tres cosas que conviene tener claras:

- **ANSES no publica una API para esto.** Se automatiza sobre el HTML del portal
  y ese HTML cambia sin aviso. Por eso los selectores viven en
  `ayudante_contable/fuentes/selectores_mianses.json`, editables sin tocar
  código. **Los selectores que vienen de fábrica no están verificados contra el
  portal real**: ajustalos la primera vez con `--inspeccionar` y el inspector del
  navegador.
- **El CAPTCHA y el segundo factor no se sortean.** Están puestos a propósito.
  El módulo trabaja con una persona presente, no en modo desatendido.
- **Encuadre.** Automatizar el portal puede chocar con sus términos de uso.
  Verificalo, dejá asentada por escrito la autorización del cliente para operar
  su cuenta, y guardá el registro de auditoría que genera la herramienta.

Si el portal cambia y el flujo se rompe, la salida es la de siempre: descargar a
mano e importar con `analizar`. El motor de control es el mismo.

---

## Antes de analizar: cargá los parámetros

**La herramienta no trae ninguna cifra legal incorporada, a propósito.** Un
informe previsional no puede apoyarse en números que un programa inventó. La
base imponible mínima y las alícuotas se cargan en una tabla que mantiene y
audita el estudio.

```bash
# Genera una plantilla vacía en tu carpeta de trabajo
ayudante-contable parametros plantilla

# Revisa qué tenés cargado y qué falta verificar
ayudante-contable parametros verificar
```

La tabla es un JSON con tramos:

```json
{
  "version": 1,
  "bases_minimas": [
    {
      "desde": "202401",
      "hasta": "202406",
      "valor": "59668.54",
      "norma": "Res. ANSES .../2024 — tabla de topes y bases imponibles",
      "verificado": true
    }
  ],
  "alicuotas_personales": [
    { "desde": "199407", "hasta": null, "sipa": "0.11", "inssjp": "0.03",
      "norma": "Ley 24.241 art. 11 / Ley 19.032", "verificado": true }
  ]
}
```

Dónde conseguir los valores: las resoluciones de movilidad de ANSES y la tabla
de topes y bases imponibles que publica ARCA/AFIP. El campo `norma` es para que
dentro de dos años sepas de dónde salió cada número, y `verificado` para dejar
constancia de que alguien lo cotejó.

**Un período sin base cargada no se juzga**: aparece como
`SIN_PARAMETRO_BASE_MINIMA` en lugar de pasar en silencio. Ese es el
comportamiento buscado — un falso "todo en orden" es peor que un dato faltante.

Para probar el flujo sin cargar nada hay un archivo de demostración con importes
inventados y redondos:

```bash
ayudante-contable analizar --cuil 20-12345678-6 \
  --planilla ejemplos/historia_laboral_ejemplo.csv \
  --parametros datos/parametros_previsionales.ejemplo.json
```

---

## Instalación

```bash
git clone https://github.com/Castore1987/ayudante_contable_1.0.git
cd ayudante_contable_1.0
pip install -e .
```

El motor de análisis y la importación de CSV funcionan **solo con la biblioteca
estándar**. Lo demás es opcional:

```bash
pip install -e ".[boveda]"    # bóveda cifrada de credenciales
pip install -e ".[archivos]"  # PDF y planillas .xlsx
pip install -e ".[portal]"    # acceso automatizado a Mi ANSES
playwright install chromium   # solo si vas a usar el portal
```

---

## Manejo de credenciales

Por defecto la clave **se pide en el momento, no se muestra al tipear y se
descarta de memoria al terminar**. No queda en disco, ni en el historial del
shell, ni en el log.

Si procesás muchos clientes por lote y decidís guardarlas, hay una bóveda
cifrada con AES (Fernet) y clave derivada por scrypt de una contraseña maestra:

```bash
ayudante-contable boveda guardar --cuil 20-12345678-6 --alias "Pérez"
ayudante-contable boveda listar     # nunca muestra claves
ayudante-contable boveda eliminar --cuil 20-12345678-6
```

Recaudos que ya vienen puestos:

- La contraseña maestra nunca se persiste: sale de `AYUDANTE_CLAVE_MAESTRA` o se
  pide por consola.
- Los archivos sensibles se crean con permisos `0600` y la carpeta con `0700`.
- Todo texto que sale del sistema pasa por un redactor que tapa claves y
  enmascara CUIL (`20-****5678-6`), incluidos los mensajes de error.
- Cada acceso queda asentado en `auditoria.jsonl` (JSON Lines, append-only) con
  el CUIL enmascarado, la acción, el resultado y el operador.

```bash
ayudante-contable auditoria --limite 20
```

Guardar credenciales de terceros es una decisión con consecuencias. La
herramienta te da los recaudos técnicos; la política de resguardo, el
consentimiento del cliente y el cumplimiento de la Ley 25.326 de protección de
datos personales son del estudio.

---

## Comandos

```
ayudante-contable analizar    Analiza una historia laboral ya descargada
ayudante-contable anses       Entra al portal Mi ANSES y descarga la historia
ayudante-contable boveda      Administra credenciales cifradas
ayudante-contable parametros  Revisa o genera la tabla de parámetros
ayudante-contable auditoria   Muestra el registro de accesos
ayudante-contable entorno     Muestra rutas y variables en uso
```

Opciones de salida comunes a `analizar` y `anses`: `--csv`, `--html`, `--json`,
`--todo`, `--salida CARPETA`, `--parametros ARCHIVO`, `--nombre "APELLIDO, Nombre"`.

**Códigos de salida**, para encadenar en scripts del estudio:

| Código | Significado |
|---|---|
| `0` | Corrió y no encontró hallazgos de nivel error |
| `1` | Corrió y encontró errores en la historia laboral |
| `2` | El comando no se pudo ejecutar |

### Variables de entorno

| Variable | Para qué |
|---|---|
| `AYUDANTE_DIR` | Carpeta de trabajo (por defecto `~/.ayudante-contable`) |
| `AYUDANTE_CLAVE_MAESTRA` | Contraseña maestra de la bóveda, para uso desatendido |
| `AYUDANTE_PARAMETROS` | Ruta alternativa a la tabla de parámetros |
| `AYUDANTE_OPERADOR` | Nombre que queda asentado en la auditoría |

---

## Usarlo como biblioteca

```python
from ayudante_contable import analizar, ParametrosPrevisionales
from ayudante_contable.fuentes.planilla import leer_planilla

parametros = ParametrosPrevisionales.desde_archivo("datos/parametros_previsionales.json")
historia = leer_planilla("historia.csv", "20-12345678-6")
informe = analizar(historia, parametros)

for tramo in informe.linea.tramos:
    print(f"{tramo.empleador}: {tramo.inicio} a {tramo.fin} ({tramo.meses_declarados} meses)")

print(informe.linea.antiguedad_texto)          # "27 año(s) y 4 mes(es)"
print([h.codigo for h in informe.errores])
```

---

## Criterios de cómputo

Decisiones que toma la herramienta y conviene conocer antes de firmar un informe:

- **Un mes computa** si tiene remuneración declarada y no consta que el aporte
  no ingresó. Un ingreso parcial o sin dato **se computa igual, pero queda
  señalado** como "mes con reservas": el criterio conservador sería descartarlo,
  pero eso escondería el problema en lugar de mostrarlo.
- **Los empleos simultáneos suman un solo mes** de antigüedad, aunque figuren
  dos empleadores.
- **Un tramo se corta** cuando hay un mes sin declarar. Si tu criterio es otro,
  subí `meses_interrupcion_tolerada` en las tolerancias.
- **Sin CUIT, el régimen forma parte de la identidad del tramo**: pasar de
  monotributo a autónomo da dos tramos, no uno.
- **La tolerancia por defecto** es 1 % por debajo de la base mínima (redondeos de
  liquidación) y 2 % en la coherencia del aporte. Ambas son configurables.

---

## Desarrollo

```bash
python -m unittest discover -s tests -t .
```

150 pruebas, sin dependencias externas más allá de `cryptography` para las de la
bóveda.

Estructura:

```
ayudante_contable/
  modelo/dominio.py        Período, RegistroMensual, TramoServicio, CUIL
  analisis/parametros.py   Tabla de bases mínimas y alícuotas por período
  analisis/evaluacion.py   Juicio mes a mes (mínimo, coherencia, ingreso)
  analisis/linea_servicios.py  Tramos, consolidado y lagunas
  analisis/validador.py    Controles y agrupamiento de hallazgos
  fuentes/planilla.py      Importación CSV/TSV/XLSX
  fuentes/pdf_anses.py     Importación PDF (tablas y texto)
  fuentes/mianses_web.py   Portal Mi ANSES con persona en el circuito
  seguridad/               Bóveda cifrada, redacción de secretos, auditoría
  reportes/                Consola, HTML, CSV y JSON
```

---

## Límites conocidos

- Los selectores del portal **no están verificados** contra Mi ANSES: hay que
  ajustarlos la primera vez y cuando el portal cambie.
- El parser de PDF por texto es heurístico. Cuando lo usa, el informe lo avisa y
  pide cotejar una muestra contra el original.
- Un PDF escaneado sin capa de texto no se puede leer: necesita OCR previo.
- La tabla de parámetros llega vacía y **es responsabilidad del estudio
  cargarla y verificarla**.
- La herramienta controla consistencia sobre los datos que entrega la fuente. Si
  ANSES tiene mal un dato de origen, esto no lo puede saber.

## Licencia

MIT.
