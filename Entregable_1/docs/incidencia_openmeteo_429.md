# Incidencia: límite de uso de Open-Meteo (HTTP 429) desde Databricks

## Qué pasa

Al llamar a la API de histórico de Open-Meteo desde un notebook de Databricks Free Edition,
la primera petición ya devuelve:

```
HTTP 429: {"error":true,"reason":"Daily API request limit exceeded. Please try again tomorrow."}
```

La misma llamada, lanzada desde nuestro ordenador, funciona sin problemas.

## Por qué pasa

- Open-Meteo limita el uso gratuito **por dirección IP** (por minuto, por hora y por día).
- Los notebooks serverless de Databricks Free Edition salen a Internet desde **IPs compartidas
  por muchísimos usuarios**. Cuando otros usuarios ya han agotado el cupo de esa IP, nuestra
  primera petición llega rechazada, aunque nosotros no hayamos hecho ninguna llamada antes.
- La respuesta trae la cabecera `Retry-After` con esperas de varios minutos (p. ej. 933 s).
  Esperar y reintentar no tiene sentido: el límite es diario y lo consumen otros.

No es un fallo de nuestro código ni un uso excesivo por nuestra parte.

## Qué dice el enunciado

La FAQ del Trabajo 1 contempla exactamente este caso:

> *La salida a Internet de Databricks Free Edition no funciona con nuestra API.*
> Ocurre con algunos dominios. Haced la llamada desde vuestro equipo (script de Python incluido
> en el repositorio), subid el JSON al volumen y documentadlo. Mantened en el notebook el código
> de la llamada con try/except.

Y en la extracción a bronze pide *"tened un fallback con una copia local por si la API o la
salida a Internet fallan"*.

## Cómo lo resolvemos

Una sola lógica de descarga (`src/openmeteo_api.py`, Python puro) que se usa desde dos sitios:

| Pieza | Dónde se ejecuta | Qué hace |
|---|---|---|
| `scripts/descarga_openmeteo_local.py` | Ordenador local (VS Code) | Llama a la API con nuestra IP y guarda los JSON en `muestras/openmeteo/` |
| Notebook de extracción | Databricks | Intenta la API; si falla, copia los JSON de `muestras/openmeteo/` al volumen y carga bronze |

Comportamiento de `src/openmeteo_api.py` ante errores:

| Respuesta | Acción |
|---|---|
| 200 | Valida que llegan todas las horas del mes y guarda el JSON |
| 429 (límite alcanzado) | No reintenta. Deja de llamar a la API en esa ejecución y usa el fallback. Si falta algún mes en el fallback, **detiene la ejecución** indicando que se lance el script local |
| 5xx o error de red | Reintenta con backoff exponencial (2, 4, 8, 16 s; máximo 60 s) |
| Otros 4xx | No reintenta; usa el fallback |

Medidas para respetar los límites de uso:

- Una petición por mes (12 en total para 2022), con 3 s de pausa entre peticiones.
- Los meses que ya están en el volumen no se vuelven a pedir.
- Tras el primer fallo de la API no se hace ninguna llamada más en esa ejecución
  (como máximo 4 peticiones fallidas, en lugar de 12 × 4 = 48).
- Cabecera `User-Agent` que identifica el proyecto.

El script local comprueba que no se está ejecutando en Databricks
(variable de entorno `DATABRICKS_RUNTIME_VERSION`); si es así, se detiene con el mensaje
*"No estás en un entorno local"*.

## Cómo ejecutarlo

1. En el ordenador, desde la carpeta `Entregable_1` y con el entorno virtual activado:
   ```
   python scripts/descarga_openmeteo_local.py
   ```
   Genera `muestras/openmeteo/openmeteo_2022-01.json` … `openmeteo_2022-12.json` (≈ 600 KB en total).
2. Commit y push de `muestras/openmeteo/`.
3. En Databricks: *Pull* en la carpeta Git y *Restart Python* en el notebook.
4. Ejecutar el notebook de extracción. La tabla de resumen indica el origen de cada fichero
   (`api`, `existente`, `fallback` o `error`).

## Evidencias

- Salida de la celda de extracción con el 429 y el resumen por fichero.
- Fecha de descarga de los JSON del fallback: <!-- completar -->
