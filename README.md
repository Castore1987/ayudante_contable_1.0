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
| `MAS_QUE_ANSES` | Meses que el sistema computa y el resumen de ANSES no reconoce | advertencia |
| `ALICUOTA_NO_VERIFICADA` | Alícuotas sin auditar: el control de coherencia no corrió | advertencia |
| `MENOS_QUE_ANSES` | Meses que ANSES reconoce y el sistema no computó (posible error de lectura) | advertencia |
| `LAGUNA_PREVISIONAL` | Meses sin servicios computables entre el primer y el último aporte | información |
| `EMPLEOS_SIMULTANEOS` | Meses con más de un empleador (se computan una sola vez) | información |
| `CUIL_INVALIDO` / `SIN_REGISTROS` | Problemas con el dato de entrada | error |

Y produce la **línea de servicios**: cada relación laboral con su CUIT, régimen,
fecha de inicio, fecha de fin, meses declarados y observaciones; más el
consolidado de antigüedad sin duplicar meses de empleo simultáneo.

---

## Las tres fuentes

Ninguna alcanza sola, y cada una es buena en algo distinto:

| Fuente | Aporta | No aporta |
|---|---|---|
| **HLAB** de ANSES (PDF) | Remuneración **imponible**, ya topeada, mes a mes | Si el aporte ingresó |
| **ARCA «Aportes en Línea»** (.xls, en realidad HTML) | `Declarado` vs `Depositado` en relación de dependencia | La imponible (informa la bruta) |
| **SICAM** (Situación de Revista + Detalle de Deuda) | Deuda y prescripción de autónomos y monotributo | Nada de relación de dependencia |

Se combinan en un solo informe:

```bash
ayudante-contable analizar --cuil 23-14366086-9 \
  --hlab HLAB_23143660869.pdf \
  --arca Historico23143660869.xls \
  --sicam-revista revista.pdf --sicam-deuda deuda.pdf \
  --todo
```

**Precedencia**: el pago efectivo manda sobre la declaración, y la remuneración
imponible se toma de quien la informa como imponible. Cuando dos fuentes se
contradicen la diferencia no se resuelve en silencio: sale listada como
discrepancia. La diferencia entre la imponible del HLAB y la bruta de ARCA **no**
cuenta como contradicción: son conceptos distintos.

### Reglas de autónomos

Dos criterios del estudio, aplicados de forma explícita y configurable:

| Situación en SICAM | Tratamiento | Cómo cambiarlo |
|---|---|---|
| Período con deuda | **Regularizado** (plan de pagos o moratoria): el mes computa, señalado | `--sicam-deuda-sin-regularizar` lo trata como no ingresado |
| `Art. 1 Ley 25.321` en `Benef. Aplic.` | **Prescripto**: no se contabiliza ni se reclama | `--sin-prescripcion-art1` lo computa igual |

El detalle de deuda **no dice** si algo está en plan de pagos: ese dato lo aporta
el estudio. Por eso es una política declarada, que queda asentada en cada
informe, y no una deducción del archivo.

---

## Cómo entran los datos: dos caminos

### 1. Importar la historia laboral descargada — **recomendado**

Descargás el HLAB desde Mi ANSES y lo importás. Es estable, no toca
credenciales, no depende del HTML del portal y deja el archivo original como
respaldo del informe.

```bash
ayudante-contable analizar \
  --cuil 20-12345678-6 \
  --pdf HLAB_20123456786.pdf \
  --todo
```

El PDF del HLAB se reconoce solo y se lee con un lector específico que entiende
sus secciones reales (ver más abajo). También acepta planillas con `--planilla`
(CSV, TSV, XLSX), con mapeo de columnas tolerante a los nombres habituales en
castellano, con o sin tildes y en cualquier orden. `--pdf-generico` fuerza el
lector genérico si alguna vez hiciera falta.

### Muchos clientes de una vez

```bash
ayudante-contable lote --padron clientes.csv --todo
```

El padrón es un CSV con una columna `cuil` y, opcionalmente, `nombre` y
`archivo`. Un expediente que falla **no corta el lote**: se procesan todos y al
final sale el resumen, con los fallidos separados de los que salieron limpios.
Genera además un índice CSV y un índice HTML navegable con enlace al informe de
cada cliente.

Un expediente que no se pudo procesar nunca se cuenta como "en orden".

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

## Qué puede y qué no puede probar el HLAB

Esto es lo más importante de entender antes de usar el informe, y sale de leer
un HLAB real renglón por renglón.

**El HLAB no informa lo mismo para todos los regímenes.**

| Régimen | Qué trae el documento | Qué se puede afirmar |
|---|---|---|
| Relación de dependencia | Remuneración **declarada** por el empleador, mes a mes | Que se declaró, y si la remuneración imponible alcanzó el mínimo. **No** si el aporte ingresó. |
| Autónomos | Alta en el padrón + `DETALLE DE PAGOS` con fecha de depósito y acreditación | Que el aporte **ingresó o no ingresó**, mes a mes. |
| Monotributo | Alta en el padrón; el detalle de pagos puede venir **vacío** | Si no hay tabla de pagos: nada sobre el ingreso. Queda «sin dato». |

De ahí salen tres reglas que el sistema aplica y conviene tener presentes:

1. **Los meses en relación de dependencia quedan con ingreso «sin dato»**, no
   como "ingresados". Para confirmarlos hace falta la constancia de pago del
   empleador. El informe lo dice en cada corrida.
2. **Un padrón sin detalle de pagos no prueba deuda**: prueba que el documento
   no informa esos pagos. Marcar deuda con eso sería inventar un reclamo.
3. **La columna que vale para el mínimo es `REM IMP. SS`, no `REM TOTAL`.** La
   primera ya viene topeada por ANSES. Por eso la tabla de parámetros carga
   también el **tope máximo**: sin él, todo sueldo alto daría falso positivo.

**El contraste contra el propio ANSES.** El HLAB trae su `RESUMEN HISTORIA
LABORAL`, que es la antigüedad según ANSES. El sistema la compara con la que
calcula y reporta las diferencias en los dos sentidos. Sobre un caso real: ANSES
reconocía 288 meses y el sistema computaba 330, sin que faltara ninguno de los
que ANSES sí reconoce. Esos 42 meses de diferencia son exactamente los que están
en discusión — y son los que hay que mirar.

---

## Antes de analizar: cargá los parámetros

El repositorio trae la tabla oficial de bases imponibles cargada:
**82 tramos que cubren 04/1994 a 03/2026 sin huecos**, cada uno con su mínimo,
su máximo y la norma que lo fija (Res. S.S.S., decretos y resoluciones ANSES).
Salió del ANEXO «Remuneración Imponible – Monto Mínimo y Máximo».

**Todos los tramos vienen con `"verificado": false.`** La extracción del PDF fue
automática: nadie del estudio la cotejó todavía. El sistema los usa igual, pero
avisa con `PARAMETROS_NO_VERIFICADOS` en cada corrida hasta que los marques.

```bash
ayudante-contable parametros verificar   # cobertura y qué falta verificar
ayudante-contable parametros plantilla   # tabla vacía, si preferís cargarla vos
```

Cada tramo se ve así:

```json
{
  "desde": "202603",
  "hasta": "202603",
  "valor": "124481.49",
  "maximo": "4045590.45",
  "norma": "Res ANSES 38/2026",
  "verificado": false
}
```

Para mantenerla: cada resolución nueva de movilidad agrega un tramo. Cerrá el
`hasta` del anterior; solo el último puede quedar abierto con `null`.

**Un período sin base cargada no se juzga**: aparece como
`SIN_PARAMETRO_BASE_MINIMA` en lugar de pasar en silencio. Ese es el
comportamiento buscado — un falso "todo en orden" es peor que un dato faltante.
Hoy eso alcanza a los períodos posteriores a 03/2026.

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
pip install -e ".[sicam]"     # lectura de los PDF de SICAM
pip install -e ".[portal]"    # acceso automatizado a Mi ANSES
playwright install chromium   # solo si vas a usar el portal
```

Los PDF de SICAM necesitan además OCR del sistema:

```bash
apt-get install -y tesseract-ocr tesseract-ocr-spa
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
ayudante-contable lote        Procesa muchos clientes desde un padrón CSV
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
- **Un mes cuenta aunque no traiga remuneración** si la fuente lo reconoce como
  servicio: los anteriores a 06/94 y los períodos de autónomo se informan sin
  sueldo, y descartarlos le borraría antigüedad al afiliado.
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

244 pruebas, sin dependencias externas más allá de `cryptography` para las de la
bóveda. Las de SICAM no ejercitan el OCR: prueban la limpieza de celdas, la
detección del Art. 1 Ley 25.321 y el cruce alta/deuda con lecturas armadas a
mano. Incluyen un HLAB sintético (`tests/hlab_ejemplo.txt`) que reproduce el
formato real —secciones, columnas pegadas, renglones vacíos— con datos
inventados: ninguna historia laboral de un cliente entra al repositorio.

Estructura:

```
ayudante_contable/
  modelo/dominio.py        Período, RegistroMensual, TramoServicio, CUIL
  analisis/parametros.py   Tabla de bases mínimas y alícuotas por período
  analisis/evaluacion.py   Juicio mes a mes (mínimo, coherencia, ingreso)
  analisis/linea_servicios.py  Tramos, consolidado y lagunas
  analisis/validador.py    Controles y agrupamiento de hallazgos
  analisis/consolidacion.py  Fusión de varias fuentes, con precedencia y conflictos
  fuentes/hlab_anses.py    Lector del HLAB de ANSES, sección por sección
  fuentes/arca_aportes.py  Export «Aportes en Línea»: declarado vs depositado
  fuentes/sicam.py         Revista y deuda de SICAM por OCR guiado por la grilla
  fuentes/planilla.py      Importación CSV/TSV/XLSX
  fuentes/pdf_anses.py     Importación PDF genérica (tablas y texto)
  lote.py                  Procesamiento por lote, aislando cada expediente
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
- La tabla de parámetros llega cargada pero **sin verificar**: cotejarla contra
  las normas citadas es responsabilidad del estudio.
- Cubre hasta 03/2026. Los períodos posteriores no se juzgan hasta que se
  agreguen los tramos nuevos.
- El lector del HLAB se calibró contra un documento real. Si ANSES cambia el
  formato, hay que ajustar las expresiones de `fuentes/hlab_anses.py`; el
  sistema avisa cuando no reconoce renglones en vez de devolver un informe
  incompleto en silencio.
- **Los PDF de SICAM no tienen capa de texto**: el texto viene convertido a
  contornos vectoriales, así que se leen por OCR. Sobre el documento de prueba
  el reconocimiento fue del orden del 76 % de los renglones del detalle de
  deuda, con algunos importes mal leídos. El lector se autocontrola —informa el
  porcentaje reconocido por página y marca como dudoso todo renglón donde
  capital + intereses no cierra con el total— pero **para un informe que se
  firma conviene guardar las pantallas de SICAM como HTML** y leer los valores
  exactos, igual que el export de ARCA. La situación de revista, en cambio, se
  reconoce completa.
- La herramienta controla consistencia sobre los datos que entrega la fuente. Si
  ANSES tiene mal un dato de origen, esto no lo puede saber.

## Licencia

MIT.
