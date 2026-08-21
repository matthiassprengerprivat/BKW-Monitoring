"""
Einmal-Skript zum Nachtragen eines "Datenlochs" in den historical-solar-*.csv-
Dateien - z.B. nach einer Meross-Sperre (TooManyTokensException), waehrend der
der normale Minuten-Takt (collect_meross.py) keine Werte schreiben konnte.

Wichtig zu verstehen: Die Meross-Steckdosen selbst (bzw. die Meross-Cloud)
zeichnen den Tages-Gesamtverbrauch unabhaengig von unserem eigenen Skript auf -
das ist dieselbe Zahl, die auch in der Meross-App unter "Verbrauch" angezeigt
wird. Dieses Skript ruft diese GERAETE-eigene Tages-Historie direkt ab
(async_get_daily_power_consumption) und schreibt sie als Zeile in die
passende historical-solar-*.csv - genau die Datei, die das Dashboard fuer den
jeweiligen Tag ohnehin schon gegenueber dem (hier laueckenhaften) Minuten-Log
bevorzugt. Ergebnis: alle Tages-/Wochen-/Monats-/Jahres-Auswertungen und die
Rekorde sind fuer den betroffenen Tag wieder korrekt.

EINE Einschraenkung bleibt: der Minuten-genaue Kurvenverlauf in "Leistung
ueber den Tag" kann fuer die Ausfallzeit nicht rueckwirkend rekonstruiert
werden (dafuer gibt es keine Quelle) - dort bleibt fuer den betroffenen
Zeitraum eine Luecke/gerade Linie. Alle anderen Kennzahlen sind aber korrekt.

Umgebungsvariablen (dieselben Repository-Secrets wie bei collect_meross.py):
  MEROSS_EMAIL, MEROSS_PASSWORD, GOOGLE_CREDENTIALS_JSON, SPREADSHEET_ID
  (Google-Zugang wird hier nur mitgenutzt, um denselben zwischengespeicherten
  Meross-Login wiederzuverwenden statt unnoetig einen weiteren Token
  auszustellen - siehe collect_meross.py)

Zusaetzlich:
  START_DATE   erster nachzutragender Tag, Format YYYY-MM-DD (Pflicht)
  END_DATE     letzter nachzutragender Tag, Format YYYY-MM-DD
               (optional, Standard: gleich START_DATE)

Hinweis zur Genauigkeit: Fuer den HEUTIGEN Tag liefert Meross nur den
Verbrauch "bis jetzt" (laufender Tag, noch nicht abgeschlossen). Am besten
dieses Skript also erst nach Ende des betroffenen Tages (oder am naechsten
Morgen) laufen lassen, damit der eingetragene Wert der endgueltige Tageswert
ist und nicht spaeter nochmal korrigiert werden muss.
"""

import asyncio
import csv
import os
import sys
from datetime import datetime, date

from meross_iot.controller.mixins.consumption import ConsumptionMixin, ConsumptionXMixin

import collect_meross as base

HISTORICAL_FILES = {
    "Solar Garten": "historical-solar-garten.csv",
    "Solar Garage": "historical-solar-garage.csv",
}


def parse_date(s):
    return datetime.strptime(s, "%Y-%m-%d").date()


def load_csv_map(path):
    """Liest 'Date,kWh' -> {date-string: kwh-float}. Fehlt die Datei, leer starten."""
    out = {}
    if not os.path.exists(path):
        return out
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        rows = list(reader)
    for row in rows[1:]:  # Header ueberspringen
        if len(row) >= 2 and row[0].strip():
            out[row[0].strip()] = float(row[1])
    return out


def write_csv_map(path, data_map):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Date", "kWh"])
        for d in sorted(data_map.keys()):
            writer.writerow([d, "{:.3f}".format(data_map[d])])


async def fetch_daily_consumption(plug):
    if isinstance(plug, ConsumptionXMixin):
        return await plug.async_get_daily_power_consumption()
    if isinstance(plug, ConsumptionMixin):
        return await plug.async_get_daily_power_consumption()
    return None


async def run():
    start_s = os.environ.get("START_DATE", "").strip()
    if not start_s:
        print("START_DATE ist nicht gesetzt - Abbruch.", file=sys.stderr)
        sys.exit(1)
    start = parse_date(start_s)
    end_s = os.environ.get("END_DATE", "").strip()
    end = parse_date(end_s) if end_s else start
    if end < start:
        print("END_DATE liegt vor START_DATE - Abbruch.", file=sys.stderr)
        sys.exit(1)

    base._CACHED_SPREADSHEET = base.get_spreadsheet()
    manager = await base.get_authenticated_manager()

    any_changes = False
    for device_name, csv_file in HISTORICAL_FILES.items():
        plugs = [p for p in manager.find_devices() if p.name == device_name]
        if not plugs:
            print(f"Geraet '{device_name}' nicht gefunden - ueberspringe.", file=sys.stderr)
            continue
        plug = plugs[0]
        await plug.async_update()
        history = await fetch_daily_consumption(plug)
        if history is None:
            print(f"'{device_name}' unterstuetzt keine Tages-Verbrauchshistorie - ueberspringe.", file=sys.stderr)
            continue

        existing = load_csv_map(csv_file)
        touched = []
        for entry in history:
            d = entry["date"].date() if isinstance(entry["date"], datetime) else entry["date"]
            if start <= d <= end:
                key = d.strftime("%Y-%m-%d")
                existing[key] = entry["total_consumption_kwh"]
                touched.append((key, entry["total_consumption_kwh"]))

        if touched:
            write_csv_map(csv_file, existing)
            any_changes = True
            for key, kwh in sorted(touched):
                print(f"{device_name}: {key} -> {kwh:.3f} kWh (in {csv_file} eingetragen)")
        else:
            print(f"{device_name}: keine Meross-Daten fuer {start}..{end} gefunden - nichts eingetragen.", file=sys.stderr)

    manager.close()

    if not any_changes:
        print("Keine Aenderungen vorgenommen - moeglicherweise liegt der Zeitraum ausserhalb der von Meross gespeicherten Historie.")
        sys.exit(2)


if __name__ == "__main__":
    asyncio.run(run())
