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
  SESSION_WORKSHEET_NAME  Standard: "Session" (siehe unten)

Login-Zwischenspeicherung (wichtig bei 1-Minuten-Takt):
  Bei jedem Lauf komplett neu bei Meross einzuloggen ist bei einem 1-Minuten-
  Takt (1440 Logins/Tag) riskanter als bei einem 5-Minuten-Takt, weil ein
  Login-Vorgang serverseitig eher wie eine automatisierte/verdaechtige
  Aktivitaet aussieht als eine reine Messwert-Abfrage. Deshalb wird der
  Login jetzt in einem eigenen, versteckten Tabellenblatt "Session"
  zwischengespeichert und - solange er noch gueltig ist - einfach
  wiederverwendet, statt sich jedes Mal neu anzumelden. Schlaegt das
  Wiederverwenden fehl (Token abgelaufen, Format veraendert, Blatt fehlt),
  faellt das Skript automatisch und ohne Fehler auf einen ganz normalen,
  frischen Login zurueck - genau wie bisher.
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
from meross_iot.model.credentials import MerossCloudCreds

BERLIN = ZoneInfo("Europe/Berlin")
HEADER = ["Zeitstempel", "Geraet", "Leistung_W", "Spannung_V", "Strom_A"]
SESSION_SHEET_NAME = os.environ.get("SESSION_WORKSHEET_NAME", "Session")


def get_spreadsheet():
    """Oeffnet die Google-Tabelle ueber den Service-Account."""
    creds_info = json.loads(os.environ["GOOGLE_CREDENTIALS_JSON"])
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_info(creds_info, scopes=scopes)
    gc = gspread.authorize(creds)
    return gc.open_by_key(os.environ["SPREADSHEET_ID"])


def get_log_worksheet(sh):
    """Gibt das Arbeitsblatt mit den Messwerten zurueck, legt es bei Bedarf an."""
    worksheet_name = os.environ.get("WORKSHEET_NAME", "Log")
    try:
        ws = sh.worksheet(worksheet_name)
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.add_worksheet(title=worksheet_name, rows=1000, cols=len(HEADER))

    first_row = ws.row_values(1)
    if not first_row:
        ws.append_row(HEADER, value_input_option="USER_ENTERED")

    return ws


def load_cached_creds():
    """Versucht, einen zwischengespeicherten Meross-Login aus dem 'Session'-Blatt
    zu laden. Bei jedem Problem wird einfach None zurueckgegeben - der Aufrufer
    macht dann ganz normal einen frischen Login. Das darf also nie hart
    fehlschlagen, es ist reine Kann-Optimierung.
    """
    try:
        ws = _session_worksheet_readonly()
        if ws is None:
            return None
        raw = ws.acell("A1").value
        if not raw:
            return None
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError):
            parsed = raw
        return MerossCloudCreds.from_json(parsed)
    except Exception as exc:
        print(f"Kein nutzbarer zwischengespeicherter Meross-Login vorhanden ({exc}), melde mich frisch an.")
        return None


def _session_worksheet_readonly():
    global _CACHED_SPREADSHEET
    try:
        return _CACHED_SPREADSHEET.worksheet(SESSION_SHEET_NAME)
    except gspread.exceptions.WorksheetNotFound:
        return None


def save_cached_creds(creds):
    """Speichert den aktuellen Meross-Login im 'Session'-Blatt fuer den naechsten
    Lauf. Schlaegt das fehl, ist das unproblematisch - beim naechsten Mal wird
    dann einfach wieder ganz normal frisch angemeldet.
    """
    global _CACHED_SPREADSHEET
    try:
        try:
            ws = _CACHED_SPREADSHEET.worksheet(SESSION_SHEET_NAME)
        except gspread.exceptions.WorksheetNotFound:
            ws = _CACHED_SPREADSHEET.add_worksheet(title=SESSION_SHEET_NAME, rows=2, cols=1)
        data = creds.to_json()
        if not isinstance(data, str):
            data = json.dumps(data)
        ws.update_acell("A1", data)
    except Exception as exc:
        print(f"Konnte Meross-Login nicht zwischenspeichern ({exc}) - nicht kritisch.", file=sys.stderr)


async def get_authenticated_manager():
    api_base_url = os.environ.get("MEROSS_API_BASE_URL", "https://iotx-eu.meross.com")

    cached = load_cached_creds()
    if cached is not None:
        try:
            client = MerossHttpClient(cloud_credentials=cached)
            manager = MerossManager(http_client=client)
            await manager.async_init()
            await manager.async_device_discovery()
            print("Zwischengespeicherten Meross-Login wiederverwendet (kein neuer Login noetig).")
            return manager
        except Exception as exc:
            print(f"Zwischengespeicherter Meross-Login ist nicht mehr gueltig ({exc}), melde mich neu an.")

    # Hinweis: async_from_user_password() reicht "agree_to_terms" nicht durch und
    # sendet es standardmaessig als 0 ("Nutzungsbedingungen nicht akzeptiert").
    # Das fuehrt bei aktuellen Meross-Konten zu ErrorCodes.INVALID_PARAMETER (20101).
    # Deshalb rufen wir async_login() direkt auf und setzen agree_to_terms=1 explizit.
    creds = await MerossHttpClient.async_login(
        api_base_url=api_base_url,
        email=os.environ["MEROSS_EMAIL"],
        password=os.environ["MEROSS_PASSWORD"],
        country_code="de",
        agree_to_terms=1,
    )
    save_cached_creds(creds)
    client = MerossHttpClient(cloud_credentials=creds)
    manager = MerossManager(http_client=client)
    await manager.async_init()
    await manager.async_device_discovery()
    return manager


async def collect_readings():
    manager = await get_authenticated_manager()

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
    # Absichtlich KEIN async_logout() mehr hier: das wuerde den (ggf. gerade erst
    # wiederverwendeten) Login serverseitig ungueltig machen und die Zwischen-
    # speicherung fuer den naechsten Lauf zunichtemachen. Der Login bleibt
    # einfach bis zu seinem natuerlichen Ablauf gueltig.
    return rows


def main():
    global _CACHED_SPREADSHEET
    _CACHED_SPREADSHEET = get_spreadsheet()

    rows = asyncio.run(collect_readings())
    if not rows:
        print("Keine Messwerte erhalten, es wird nichts in die Tabelle geschrieben.")
        return

    ws = get_log_worksheet(_CACHED_SPREADSHEET)
    ws.append_rows(rows, value_input_option="USER_ENTERED")
    print(f"{len(rows)} Zeile(n) in die Google-Tabelle geschrieben.")


_CACHED_SPREADSHEET = None

if __name__ == "__main__":
    main()
