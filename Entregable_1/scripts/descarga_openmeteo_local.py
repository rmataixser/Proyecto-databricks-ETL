"""
Descarga los JSON de Open-Meteo desde el ordenador local.

Se usa cuando la API no responde desde Databricks (HTTP 429 por la IP compartida
de Databricks Free Edition). Los ficheros quedan en muestras/openmeteo/ y el
notebook de extracción los usa como fallback.

Uso (desde la carpeta Entregable_1, con el venv activado):
    python scripts/descarga_openmeteo_local.py

Ver docs/incidencia_openmeteo_429.md
"""

import os
import sys
from datetime import date

# Este script es para ejecutarse en local, no en Databricks
if "DATABRICKS_RUNTIME_VERSION" in os.environ:
    sys.exit(
        "No estás en un entorno local: este script se ejecuta desde tu ordenador (VS Code), "
        "no desde Databricks. En Databricks usa el notebook de extracción."
    )

# Raíz del entregable: la carpeta que contiene src/, scripts/ y muestras/
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(RAIZ)

from src.openmeteo_api import LimiteApiAlcanzado, descargar_periodo

DESDE = date(2022, 1, 1)
HASTA = date(2022, 12, 31)
DESTINO = os.path.join(RAIZ, "muestras", "openmeteo")

try:
    resumen = descargar_periodo(desde=DESDE, hasta=HASTA, carpeta_destino=DESTINO)
except LimiteApiAlcanzado as error:
    sys.exit(
        f"Tu IP también ha alcanzado el límite de Open-Meteo: {error}\n"
        "Espera (el límite diario se reinicia al día siguiente) o prueba desde otra red."
    )

for fichero, origen in resumen.items():
    print(f"{fichero}: {origen}")

errores = [f for f, origen in resumen.items() if origen == "error"]
if errores:
    sys.exit(f"No se han podido descargar: {', '.join(errores)}. Revisa los mensajes de arriba.")

print(f"\nJSON guardados en {DESTINO}")
print("Siguiente paso: commit y push de muestras/openmeteo/, Pull en Databricks y ejecutar el notebook.")