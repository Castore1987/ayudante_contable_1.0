# Procedimiento operativo del estudio

Guía corta para el trabajo diario. La referencia completa está en el README.

## Una sola vez, al instalar

1. **Verificar la tabla de parámetros.**

   Ya viene cargada con los 82 tramos oficiales (04/1994 a 03/2026), pero todos
   marcados sin verificar.

   ```bash
   ayudante-contable parametros verificar
   ```

   Cotejá los tramos contra la norma que cita cada uno y andá poniendo
   `"verificado": true` en `datos/parametros_previsionales.json`. Hasta que no
   estén todos, cada informe sale con la advertencia
   `PARAMETROS_NO_VERIFICADOS`, que es lo correcto.

   Cuando salga una resolución nueva de movilidad, agregá el tramo y cerrá el
   `hasta` del anterior.

2. **Si vas a usar el acceso al portal**, ajustá los selectores:

   ```bash
   ayudante-contable anses --cuil <CUIL> --inspeccionar
   ```

   Abrí Mi ANSES en el navegador, inspeccioná cada campo y corregí
   `ayudante_contable/fuentes/selectores_mianses.json`. Es un archivo de
   configuración: no hace falta tocar código.

3. **Definí dónde vive la carpeta de trabajo** (guarda bóveda, auditoría,
   descargas e informes con datos de clientes):

   ```bash
   export AYUDANTE_DIR=/ruta/protegida/ayudante
   export AYUDANTE_OPERADOR="Nombre del operador"
   ```

   Incluila en el resguardo del estudio y en la política de retención.

## Por cada cliente

1. **Dejá asentada la autorización** del cliente para consultar su cuenta.
2. Obtené la historia laboral, por el camino que corresponda:

   ```bash
   # Expediente completo: dependencia (HLAB + ARCA) y autónomos (SICAM)
   ayudante-contable analizar --cuil <CUIL> \
     --hlab HLAB_<CUIL>.pdf --arca AportesEnLinea.xls \
     --sicam-revista revista.xlsx --sicam-deuda deuda.xlsx --todo

   # Solo el HLAB, si es lo único que tenés
   ayudante-contable analizar --cuil <CUIL> --pdf HLAB_<CUIL>.pdf --todo

   # O una planilla exportada
   ayudante-contable analizar --cuil <CUIL> --nombre "APELLIDO, Nombre" \
     --planilla historia.csv --todo

   # Portal, con vos presente para el CAPTCHA / código
   ayudante-contable anses --cuil <CUIL> --nombre "APELLIDO, Nombre" --todo
   ```

3. **Leé los hallazgos de nivel ERROR primero.** Son los que hay que reclamar
   antes de presentar cualquier trámite.
4. **Cotejá contra documentación respaldatoria** los meses marcados: recibos de
   sueldo, F.931, constancias de pago.
5. Archivá en el legajo del cliente: el archivo original de la historia laboral,
   el `-informe.html` y el `-linea-servicios.csv`.

## Muchos clientes de una vez

```bash
ayudante-contable lote --padron clientes.csv --todo
```

`clientes.csv` necesita una columna `cuil`; `nombre` y `archivo` son
opcionales pero conviene ponerlas:

```csv
cuil;nombre;archivo
20-12345678-6;PEREZ JUAN;./hlab/HLAB_20123456786.pdf
27-11111111-4;GOMEZ ANA;./hlab/HLAB_27111111114.pdf
```

Un expediente que falla no corta la corrida. Al final salen tres grupos: en
orden, con errores, y **no procesados**. Mirá siempre los no procesados: no
fueron analizados, así que no son "clientes sin problemas".

Deja un `lote-indice.csv` para la planilla de seguimiento y un
`lote-indice.html` navegable con enlace al informe de cada uno.

## Cómo leer el resultado

- **Meses computables** — antigüedad reconocida por la herramienta.
- **`MAS_QUE_ANSES` / `MENOS_QUE_ANSES`** — el contraste contra el `RESUMEN` del
  propio HLAB. Los `MAS_QUE_ANSES` son los meses en discusión: ANSES no los
  reconoce, y sin respaldo del aporte no los va a contar. Los `MENOS_QUE_ANSES`
  apuntan más bien a un renglón que el lector no interpretó: revisalos contra
  el PDF.
- **Meses con reservas** — se computaron, pero el ingreso fue parcial o no hay
  dato. Pedí la constancia de pago antes de darlos por buenos.
- **Meses descartados** — declarados y sin ingresar. No suman antigüedad y son
  el reclamo más frecuente al empleador.
- **Lagunas** — huecos entre el primer y el último aporte. Pueden ser períodos
  sin actividad (normal) o períodos no declarados (a investigar).

## Cuando algo se rompe

| Síntoma | Qué hacer |
|---|---|
| `SIN_PARAMETRO_BASE_MINIMA` | Falta cargar la base mínima de esos períodos (hoy, posteriores a 03/2026). |
| `APORTE_INGRESO_INCIERTO` en relación de dependencia | Es lo esperado: el HLAB no informa el ingreso para ese régimen. Pedí la constancia de pago al empleador. |
| Un padrón «sin detalle de pagos» | El documento no trae esos pagos. No es deuda: es falta de dato. |
| `PARAMETROS_NO_VERIFICADOS` | Alguien tiene que cotejar esos tramos contra la norma. |
| El portal no encuentra un campo | Ajustá el selector que menciona el error; hay una captura de pantalla guardada en la carpeta de descargas. |
| El PDF no se lee | Probá exportar la historia laboral a CSV. Si es un escaneo, necesita OCR previo. |
| SICAM avisa que reconoció pocos renglones | Estás usando el PDF. Bajá los dos reportes en **planilla (.xlsx)**: se leen completos, sin OCR y sin riesgo de inventar tramos. |
| Salida con código 2 | El comando no corrió: leé el mensaje de error, es específico. |

## Higiene de datos

- Las claves se piden en el momento y se descartan; guardarlas en la bóveda es
  opcional y una decisión del estudio.
- `auditoria.jsonl` registra cada acceso con el CUIL enmascarado. No lo borres:
  es el respaldo de qué se consultó y cuándo.
- Las capturas de pantalla del portal contienen datos personales del cliente.
  Quedan en la carpeta de descargas, junto al resto del expediente.
- Nada de esto va al repositorio: el `.gitignore` ya excluye bóveda, auditoría,
  descargas e informes.
