"""
Fragt alle Meross-Steckdosen mit Energiemessung ab und schreibt eine Zeile
pro Gerät in eine Google-Tabelle.

Erwartet folgende Umgebungsvariablen (werden in GitHub Actions aus den
Repository-Secrets befuellt, siehe SETUP-ANLEITUNG.md):

  MEROSS_EMAIL            E-Mail-Adresse des Meross-Kontos (dieselbe wie in der App)
  MEROSS_PASSWORD         Passwort des Meross-Kontos
  GOOGLE_CREDENTIALS_JSON Kompletter Inhalt der Service-Account-JSON-Datei (als Text)
  SPREADSHEET_ID          Die ID der Google-Tabelle (aus deren URL)

Optional:
  MEROSS_API_BASE_URL     Standard: https://iotx-eu.meross.com (Europa-Region)
  WORKSHEET_NAME          Standard: "Log"
"""

import asyncio
import json
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import gspread
from google.oauth2.service_account import Credentials

from meross_iot.controller.mixins.electricity import ElectricityMixin
from meross_iot.http_api import MerossHttpClient
from meross_iot.manager import MerossManager

BERLIN = ZoneInfo("Europe/Berlin")
HEADER = ["Zeitstempel", "Geraet", "Leistung_W", "Spannung_V", "Strom_A"]


def get_worksheet():
    """Oeffnet die Google-Tabelle ueber den Service-Account und gibt das Arbeitsblatt zurueck."""
    creds_info = json.loads(os.environ["GOOGLE_CREDENTIALS_JSON"])
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_info(creds_info, scopes=scopes)
    gc = gspread.authorize(creds)

    spreadsheet_id = os.environ["SPREADSHEET_ID"]
    sh = gc.open_by_key(spreadsheet_id)

    worksheet_name = os.environ.get("WORKSHEET_NAME", "Log")
    try:
        ws = sh.worksheet(worksheet_name)
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.add_worksheet(title=worksheet_name, rows=1000, cols=len(HEADER))

    # Kopfzeile anlegen, falls die Tabelle noch leer ist
    first_row = ws.row_values(1)
    if not first_row:
        ws.append_row(HEADER, value_input_option="USER_ENTERED")

    return ws


async def collect_readings():
    api_base_url = os.environ.get("MEROSS_API_BASE_URL", "https://iotx-eu.meross.com")

    http_client = await MerossHttpClient.async_from_user_password(
        api_base_url=api_base_url,
        email=os.environ["MEROSS_EMAIL"],
        password=os.environ["MEROSS_PASSWORD"],
    )
    manager = MerossManager(http_client=http_client)
    await manager.async_init()
    await manager.async_device_discovery()

    plugs = manager.find_devices(device_class=ElectricityMixin)
    if not plugs:
        print("Keine Geraete mit Energiemessung gefunden. Zugangsdaten/Geraete pruefen.")

    now_str = datetime.now(tz=BERLIN).strftime("%Y-%m-%d %H:%M:%S")
    rows = []
    for plug in plugs:
        try:
            await plug.async_update()
            metrics = await plug.async_get_instant_metrics()
            rows.append([now_str, plug.name, metrics.power, metrics.voltage, metrics.current])
            print(f"{plug.name}: {metrics.power} W, {metrics.voltage} V, {metrics.current} A")
        except Exception as exc:  # ein einzelnes fehlerhaftes Geraet soll die anderen nicht blockieren
            print(f"Konnte {plug.name} nicht auslesen: {exc}", file=sys.stderr)

    manager.close()
    await http_client.async_logout()
    return rows


def main():
    rows = asyncio.run(collect_readings())
    if not rows:
        print("Keine Messwerte erhalten, es wird nichts in die Tabelle geschrieben.")
        return

    ws = get_worksheet()
    ws.append_rows(rows, value_input_option="USER_ENTERED")
    print(f"{len(rows)} Zeile(n) in die Google-Tabelle geschrieben.")


if __name__ == "__main__":
    main()
