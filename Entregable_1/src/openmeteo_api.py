"""
Descarga del tiempo horario de Madrid desde la API de histórico de Open-Meteo.

Guarda la respuesta en bruto (un JSON por mes) en la carpeta indicada.

Comportamiento ante errores:
- 429 (límite de uso alcanzado): no se reintenta. Se deja de llamar a la API,
  se intenta completar con el fallback (muestras/openmeteo/) y, si falta algún
  mes, se detiene la ejecución indicando que se lance el script local.
- 5xx o error de red: reintentos con backoff exponencial.
- Otros 4xx (400, 403...): no se reintenta; se pasa al fallback.

Ver docs/incidencia_openmeteo_429.md
"""

import json
import os
import shutil
import time
from datetime import timedelta

import requests

URL = "https://archive-api.open-meteo.com/v1/archive"
LATITUD = 40.4168     # Madrid, Puerta del Sol
LONGITUD = -3.7038

VARIABLES = [
    "temperature_2m", "relative_humidity_2m", "precipitation", "rain",
    "snowfall", "weather_code", "cloud_cover",
    "wind_speed_10m", "wind_gusts_10m", "wind_direction_10m",
]

TIMEOUT = 30                  # segundos máximos por petición
MAX_REINTENTOS = 4
ESPERA_MAXIMA = 60            # nunca esperar más de 60 s entre reintentos
PAUSA = 3                     # segundos entre peticiones, para respetar los límites
CODIGOS_REINTENTABLES = [500, 502, 503, 504]
CABECERAS = {"User-Agent": "CUNEF-ETL-proyecto-academico"}

MENSAJE_SCRIPT_LOCAL = (
    "Lanza la descarga desde tu ordenador (VS Code), en la carpeta Entregable_1:\n"
    "    python scripts/descarga_openmeteo_local.py\n"
    "Después haz commit y push de muestras/openmeteo/, Pull en Databricks y vuelve a ejecutar."
)


class LimiteApiAlcanzado(Exception):
    """La API ha respondido 429: se ha agotado el límite de uso para esta IP."""


def meses_entre(desde, hasta):
    """Devuelve una lista de (primer_dia, ultimo_dia) de cada mes del periodo."""
    meses = []
    inicio = desde
    while inicio <= hasta:
        mes_siguiente = (inicio.replace(day=1) + timedelta(days=32)).replace(day=1)
        fin = min(mes_siguiente - timedelta(days=1), hasta)
        meses.append((inicio, fin))
        inicio = fin + timedelta(days=1)
    return meses


def motivo_error(respuesta):
    """Open-Meteo explica el error en el campo 'reason' del JSON."""
    try:
        return respuesta.json().get("reason", respuesta.text[:200])
    except ValueError:
        return respuesta.text[:200]


def pedir_con_reintentos(params):
    """Hace la petición con timeout y reintentos con backoff exponencial.
    Devuelve el JSON de la respuesta o lanza un error si no se consigue."""
    for intento in range(1, MAX_REINTENTOS + 1):
        try:
            respuesta = requests.get(URL, params=params, headers=CABECERAS, timeout=TIMEOUT)
        except requests.exceptions.RequestException as error:
            print(f"  Error de red: {error}")
            respuesta = None

        if respuesta is not None:
            if respuesta.status_code == 200:
                return respuesta.json()

            if respuesta.status_code == 429:
                # Límite de uso agotado: reintentar solo empeora las cosas
                raise LimiteApiAlcanzado(motivo_error(respuesta))

            if respuesta.status_code not in CODIGOS_REINTENTABLES:
                # 400, 403...: reintentar no lo arregla
                raise RuntimeError(f"HTTP {respuesta.status_code}: {motivo_error(respuesta)}")

            print(f"  HTTP {respuesta.status_code}: {motivo_error(respuesta)}")

        espera = min(2 ** intento, ESPERA_MAXIMA)     # backoff: 2, 4, 8, 16 segundos
        print(f"  Reintento {intento}/{MAX_REINTENTOS} en {espera} s")
        time.sleep(espera)

    raise RuntimeError(f"Sin respuesta tras {MAX_REINTENTOS} reintentos")


def comprobar_respuesta(datos, inicio, fin):
    """Comprueba que llegan todas las horas del mes antes de guardar."""
    horas_recibidas = len(datos["hourly"]["time"])
    horas_esperadas = ((fin - inicio).days + 1) * 24
    if horas_recibidas != horas_esperadas:
        raise ValueError(f"Se esperaban {horas_esperadas} horas y llegaron {horas_recibidas}")


def guardar_json(datos, ruta):
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False)


def usar_fallback(nombre_fichero, carpeta_fallback, carpeta_destino):
    """Copia el JSON de respaldo al destino. Devuelve True si existía."""
    if not carpeta_fallback:
        return False
    origen = os.path.join(carpeta_fallback, nombre_fichero)
    if not os.path.exists(origen):
        return False
    shutil.copy2(origen, os.path.join(carpeta_destino, nombre_fichero))   # conserva la fecha original
    return True


def descargar_periodo(desde, hasta, carpeta_destino, carpeta_fallback=None):
    """Descarga mes a mes el periodo indicado y guarda un JSON por mes.

    Si la API falla una vez, deja de llamarla y usa el fallback para el resto.
    Si el fallo es un 429 y el fallback no cubre todos los meses, lanza
    LimiteApiAlcanzado con las instrucciones para descargar en local.

    Devuelve un resumen con el origen de cada fichero (api, existente, fallback o error)."""
    os.makedirs(carpeta_destino, exist_ok=True)
    resumen = {}
    api_disponible = True
    limite_alcanzado = None

    for inicio, fin in meses_entre(desde, hasta):
        nombre = f"openmeteo_{inicio:%Y-%m}.json"
        ruta = os.path.join(carpeta_destino, nombre)

        # Si ya está descargado no se vuelve a pedir (respeta los límites de uso)
        if os.path.exists(ruta):
            resumen[nombre] = "existente"
            continue

        if api_disponible:
            params = {
                "latitude": LATITUD,
                "longitude": LONGITUD,
                "start_date": inicio.isoformat(),
                "end_date": fin.isoformat(),
                "hourly": ",".join(VARIABLES),
                "timezone": "GMT",        # UTC: evita la hora repetida del cambio de hora
            }
            print(f"Descargando {nombre}...")
            try:
                datos = pedir_con_reintentos(params)
                comprobar_respuesta(datos, inicio, fin)
                guardar_json(datos, ruta)
                resumen[nombre] = "api"
                time.sleep(PAUSA)
                continue
            except LimiteApiAlcanzado as error:
                print(f"  HTTP 429, límite de la API alcanzado: {error}")
                print("  No se volverá a llamar a la API en esta ejecución.")
                limite_alcanzado = str(error)
                api_disponible = False
            except Exception as error:
                print(f"  Falla la API ({error}). No se volverá a llamar en esta ejecución.")
                api_disponible = False

        # API no disponible: se usa la copia de respaldo
        if usar_fallback(nombre, carpeta_fallback, carpeta_destino):
            resumen[nombre] = "fallback"
        else:
            resumen[nombre] = "error"

    if limite_alcanzado:
        faltan = [f for f, origen in resumen.items() if origen == "error"]
        if faltan:
            raise LimiteApiAlcanzado(
                f"Límite de la API de Open-Meteo alcanzado ({limite_alcanzado}).\n"
                f"Faltan {len(faltan)} meses y no están en el fallback: {', '.join(faltan)}.\n"
                + MENSAJE_SCRIPT_LOCAL
            )
        print("Límite de la API alcanzado, pero todos los meses se han completado con el fallback.")

    return resumen