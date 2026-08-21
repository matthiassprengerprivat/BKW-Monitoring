// Euer persönlicher Link zur veröffentlichten Google-Tabelle (Log-Tab, als CSV).
// Diese Datei bitte NIE komplett ersetzen, wenn ihr eine neue index.html bekommt -
// nur den Link unten bei Bedarf aktualisieren (z. B. wenn ihr neu "Im Web veröffentlichen" macht).
//
// WICHTIG: Der Link unten ist der letzte Stand, den wir gemeinsam eingerichtet haben. Bitte einmal
// prüfen, dass es wirklich der Link zu eurem "Log"-Tab ist (nicht "Ganzes Dokument"), bevor ihr
// diese Datei ins Repo hochladet - ihr wisst selbst am besten, welcher Link bei euch gerade aktiv ist.
var CSV_URL = "https://docs.google.com/spreadsheets/d/1NIzBtVhiM6uhWBfdarMKfbDlWYVakJoy-gRRUzbfAek/gviz/tq?tqx=out:csv&sheet=Log";
// Standort fuer den Wetter-Kontext (Sonnenauf-/-untergang, Bewoelkung) ueber die kostenlose
// Open-Meteo-API (kein Account/Key noetig). Grobe Koordinaten reichen voellig - fuer Wetterdaten
// macht ein Unterschied von ein paar hundert Metern ohnehin keinen Unterschied. Aktuell auf
// Bergisch Gladbach eingestellt; bei Umzug hier einfach die zwei Werte anpassen.
var WEATHER_LAT = 50.9856;
var WEATHER_LON = 7.13298;
