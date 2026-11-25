"""
Descarga del tiempo horario de Madrid desde la API de histórico de Open-Meteo.

Guarda la respuesta en bruto (un JSON por mes) en la carpeta indicada.
Si la API falla, copia los JSON de respaldo de la carpeta de fallback.
"""

import json
import os
import shutil
import time
from datetime import date, timedelta

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
PAUSA = 3                     # segundos entre peticiones, para respetar los límites
CODIGOS_REINTENTABLES = [429, 500, 502, 503, 504]
CABECERAS = {"User-Agent": "CUNEF-ETL-proyecto-academico"}


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

            if respuesta.status_code not in CODIGOS_REINTENTABLES:
                # 400, 403...: reintentar no lo arregla, se para aquí
                raise RuntimeError(f"HTTP {respuesta.status_code}: {respuesta.text[:200]}")

            print(f"  HTTP {respuesta.status_code}")

        espera = 2 ** intento                 # backoff: 2, 4, 8, 16 segundos
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
    origen = os.path.join(carpeta_fallback, nombre_fichero)
    if not os.path.exists(origen):
        return False
    shutil.copy(origen, os.path.join(carpeta_destino, nombre_fichero))
    return True


def descargar_periodo(desde, hasta, carpeta_destino, carpeta_fallback=None):
    """Descarga mes a mes el periodo indicado y guarda un JSON por mes.
    Devuelve un resumen con el origen de cada fichero (api, existente o fallback)."""
    os.makedirs(carpeta_destino, exist_ok=True)
    resumen = {}

    for inicio, fin in meses_entre(desde, hasta):
        nombre = f"openmeteo_{inicio:%Y-%m}.json"
        ruta = os.path.join(carpeta_destino, nombre)

        # Si ya está descargado no se vuelve a pedir (respeta los límites de uso)
        if os.path.exists(ruta):
            resumen[nombre] = "existente"
            continue

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
        except Exception as error:
            print(f"  Falla la API ({error}). Se usa el fallback.")
            if carpeta_fallback and usar_fallback(nombre, carpeta_fallback, carpeta_destino):
                resumen[nombre] = "fallback"
            else:
                resumen[nombre] = "error"

    return resumen