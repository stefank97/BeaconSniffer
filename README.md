# Intervalls for Sending Beacons/MQTT/etc.

| Was | Wo | Default |
|---|---|---|
| BLE Beacon | `include/secrets.h` -> `BLE_BEACON_SENDING_INTERVALL` | `0x40` = ca. 25/s |
| Receiver Median | `include/secrets.h` -> `BLE_BEACON_RSSI_MEDIAN_SIZE` | `20` Samples |
| WiFi RSSI | `src/wifi_scanner.cpp` -> `lastDetailScan < 2000` | 2 s |
| Python/WebSocket | `CalculateServer/server.py` -> `time.sleep(2)` | 2 s |


# ESP32-RECEIVER:

NEU:

"platformio.ini" hat eine build_flag mit der man über "n" iterieren kann, wenn man die ESP32-Receiver flasht.

```
build_flags =
        -D RECEIVER_ID=n
```

Farbe LED ESP32: 1 == rot, 2 == grün, 3 == blau , n == weiß...

Zusätzlich muss man "secrets_example.h" zu "Secrets.h" kopieren/umbenennen und die WLAN- sowie HOST-Informationen für die WLAN-/MQTT-Verbindung ausfüllen.

# MQTT-Docker-Container

Einfach in Linux bzw. WSL im Ordner "Mosquitto":
```
docker compose up
```

Bekannte Fehler:
```
Verbinde MQTT...fehlgeschlagen, rc=-2
```
Hier kann sein, dass die IP-Adresse des Hosts sich durch DHCP geändert hat!

## Test CLI command:

```
docker exec -it mymqtt mosquitto_sub -h localhost -t "receivers/#" -v
```
Die ESP32-Receiver publishen per "receivers/#" den BLE-RSSI Wert vom ePaper (Achtung nicht den WLAN-ePaper-RSSI-Wert)

## 1m-Kalibrierung

```
#define BEACON_MAJOR
```

Wird nur gemacht wenn bei ePaper der Beacon auf MAJOR = 100 geändert wird.

MAJOR = 1 ist der normale Beacon.

FUTURE-WORK => Sobald Trilateration funtioniert, das vielleicht verwenden um die Trilateration genauer zu machen?

//TODO Implement useful for run-time, now it would need manual changes to work... //Change MAJOR to 100 in ePaper + read manually the 1m Values (change serial-output needed) + add a new field in the mqtt-publish of ESP32-Receiver


# Platformio.ini

## build_flags:

```
build_flags =
    -D BOARD_HAS_PSRAM
    -D ARDUINO_USB_CDC_ON_BOOT=1    ; Startet Ausgabe von Texten sofort (damit beim Booten alles tdm alles im Terminal ladnet)
```

TLDR which USB => mit Flags == links || ohne Flags == rechts

Die Flags braucht man eigentlich nicht, diese sagen nur aus, dass der normale USB-Input (links) vom ESP32 als Serial-Ausgabe dient. Ohne Flags einfach den Serial-USB (rechts) verwenden.

## upload_ports:

```
upload_port = COMn
monitor_port = COMn
```

COM[n]-Port zu finden unter: Change -> PIO Home -> left hand Devices -> Port

Durch die Angabe von Port kann man mehrere Geräte angesteckt haben und mit wechsel der ENV wechselt auch der Port/das Gerät für den Upload.


# Pyhton-Server

```
python -m pip install -r requirements.txt
```

```
.../source/repos/BeaconSniffer/CalculateServer$ python server.py
```

Am besten wie immer direkt aus dem Ordner starten, sonst gibts Probleme mit der .env-file!

## Fragen:
* Was ist eigentlich dieser "Kalman-Filter" genau?
* Was ist eigentlich der "path-loss-exponent" genau?
* Was ist eigentlich "Least Square Multilateration" genau?



# Epaper README

Diese Notiz beschreibt die aktuell wichtigsten ePaper-Module:

- `Display`: einfache Textausgabe auf das ePaper
- `Input`: Button-Navigation und Screen-State
- `WifiScanner`: WLAN-Scan, Details, MQTT-Publish

## Display

Dateien:

- `include/display.h`
- `src/display.cpp`

Das `Display`-Modul verwaltet einen eigenen Framebuffer im PSRAM. Text und Icons werden zuerst in diesen Framebuffer gezeichnet. Sichtbar wird etwas erst nach einem Refresh.

Wichtige Funktionen:

```cpp
Display::init();
Display::clear();
Display::printLine(line, text);
Display::refresh();
Display::refreshLine(firstLine, lineCount);
Display::clearLine(firstLine, lineCount);
```

`Display::printLine()` verwendet logische Zeilennummern. Zeile `0` wird intern nicht bei Pixel `0`, sondern bei `BOARDER_Y * (0 + 1)` gezeichnet. Dadurch bleibt oben Abstand.

Wichtig: `clear()` löscht nur den Framebuffer. Erst `refresh()` aktualisiert das echte ePaper.

`refreshLine()` und `clearLine()` arbeiten mit einem Teilbereich. Wegen der aktuellen Berechnung starten sie bei `firstLine = 0` trotzdem erst ab `y = BOARDER_Y`. Für Screens, die wirklich oben beginnen sollen, ist ein Full Refresh mit `clear()` + `refresh()` zuverlässiger.

## Input

Dateien:

- `include/input.h`
- `src/input.cpp`

Das `Input`-Modul nutzt `Button2` auf `BUTTON_1` (GPIO21) und verwaltet den aktuellen Screen:

```cpp
enum class ScreenState {
    MainMenu,
    WifiList,
    WifiDetails,
    BleList,
    BleDetails
};
```

Aktuelle Button-Belegung:

- Main Menu:
  - kurzer Klick: nächster Menüpunkt
  - langer Klick: ausgewählten Menüpunkt öffnen/ausführen
- WiFi-Liste:
  - kurzer Klick: nächster Listeneintrag
  - langer Klick: Return ausführen oder WLAN-Details öffnen
  - Doppelklick: WLAN neu scannen
- WiFi-Details:
  - langer Klick: zurück zur WLAN-Liste

Aktuelle Main-Menu-Punkte:

```text
WiFi Scanner
Bluetooth Scanner
Standard Beacon
Calibration
```

`Standard Beacon` setzt den BLE-iBeacon-Major auf `1`.

`Calibration` setzt den BLE-iBeacon-Major auf `100`.

Der aktuelle Major wird im Main Menu über `SenderBle::getMajor()` angezeigt.

## WifiScanner

Dateien:

- `include/wifi_scanner.h`
- `src/wifi_scanner.cpp`

Das `WifiScanner`-Modul scannt WLANs und speichert maximal `maxNetworks` Einträge in einem internen Array:

```cpp
struct NetworkInfo {
    String ssid;
    String bssid;
    int rssi;
    int channel;
    int encryption;
};
```

Wichtige Funktionen:

```cpp
WifiScanner::scan();
WifiScanner::scanAndShowList();
WifiScanner::nextSelection();
WifiScanner::showDetails();
WifiScanner::showList();
WifiScanner::loop();
WifiScanner::exitDetails();
WifiScanner::returnSelected();
```

Die WLAN-Liste enthält einen virtuellen ersten Eintrag:

```text
Return to Main Menu
```

Daher gibt es zwei Indizes:

- `selectedListItem`: Index in der sichtbaren Liste
- `selectedNetwork`: Index im `networks[]`-Array

Mapping:

```text
selectedListItem = 0 -> Return to Main Menu
selectedListItem = 1 -> networks[0]
selectedListItem = 2 -> networks[1]
```

Beim Öffnen der Details wird die BSSID des ausgewählten Netzwerks gespeichert. Während `WifiDetails` aktiv ist, scannt `WifiScanner::loop()` regelmäßig neu, sucht dieselbe BSSID wieder und published aktuelle Daten per MQTT.

MQTT-Topic:

```text
beaconsniffer/wifi
```

Payload-Beispiel:

```json
{"ssid":"Home2","bssid":"F0:09:0D:B3:12:B6","rssi":-58,"channel":4}
```

Der Payload wird mit ArduinoJson gebaut.

## Zusammenspiel

Startup in `main_epaper.cpp`:

```cpp
Display::init();
Input::init();
SenderBle::setup();
```

`Input::init()` zeigt das Main Menu. Der WLAN-Scan startet nicht automatisch beim Boot, sondern erst bei Longclick auf `WiFi Scanner`.

In der Hauptschleife laufen:

```cpp
Input::loop();
SenderBle::loop();
WifiScanner::loop();
```

`Input::loop()` muss regelmäßig laufen, damit Button-Klicks erkannt werden. Lange blockierende Funktionen verschlechtern die Bedienung.

## Bekannte Hinweise

- WLAN-Scans und MQTT-Verbindungsaufbau können blockieren. Währenddessen reagiert der Button verzögert.
- `Display::refreshLine()` eignet sich nicht gut für Inhalte, die ganz oben beginnen. Für komplette Screens lieber Full Refresh verwenden.
- `Bluetooth Scanner` ist im Main Menu aktuell noch Platzhalter.
