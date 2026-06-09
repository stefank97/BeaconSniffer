# BeaconSniffer

Die einfache Erfassung der WLAN-Signalstaerke im Eigenheim.

BeaconSniffer ist ein Prototyp aus ePaper-Client, BLE-Receivern, MQTT, Python-Positionsberechnung und Webserver. Das LilyGo T5-4.7 scannt WLANs, sendet parallel BLE-Beacons, die Receiver messen die BLE-RSSI-Werte und ein Python-Server berechnet daraus eine Position. Die gemessene WLAN-Signalstaerke wird anschliessend im Webserver als Heatmap dargestellt.

## Architektur

```text
LilyGo T5-4.7
  - WLAN-Scan am ePaper
  - BLE-iBeacon Sender
  - MQTT Publish: beaconsniffer/wifi

Receiver
  - ARCELI ESP32-S3-DevKitC-1 oder Pycom LoPy4
  - BLE-RSSI Messung
  - MQTT Publish: receivers/<id>

Mosquitto
  - lokaler MQTT-Broker

CalculateServer
  - liest MQTT-Daten
  - filtert RSSI-Werte
  - berechnet Position per Multilateration
  - sendet Heatmap-Samples per WebSocket

webserver
  - Docker-Stack mit FastAPI und PostgreSQL
  - Dashboard, Raumansicht und Heatmap
```

## Hardware

Getestet wurde mit:

- LilyGo T5-4.7 als ePaper-Client
- ARCELI ESP32-S3-DevKitC-1 als Receiver
- Pycom LoPy4 v1.0 mit Expansionboard v3.1 als Receiver
- mindestens 3 Receiver fuer Multilateration, im Prototyp wurden 4 verwendet

Andere Boards koennen funktionieren, wurden aber nicht validiert.

## Voraussetzungen

- Windows mit VS Code und PlatformIO
- Docker Desktop oder Docker in WSL
- Python 3
- optional fuer Pycom LoPy4: Pycom Firmware Upgrade Tool

Die COM-Ports findet man in PlatformIO unter `PlatformIO Home -> Devices` oder im Windows-Geraetemanager. In den Beispielen wird `COM<n>` als Platzhalter verwendet.

## Konfiguration

### Environment-Files | Umgebungsdateien

Die verschiedenen vorbereiteten Umgebungsdateien (.env-files) kopieren und befüllen.

Zugangsdaten müssen selbst befüllt werden, Standard-Daten können belassen werden.

```powershell
Copy-Item include\secrets_example.h include\secrets.h
```

Danach in `include/secrets.h` WLAN und MQTT-Broker eintragen:

```cpp
#define WIFI_SSID_FOR_MQTT "SSID"
#define WIFI_PW_FOR_MQTT "PW"
#define MQTT_SERVER_HOST_IP "192.168.x.x"
#define MQTT_SERVER_PORT 1883
```

`MQTT_SERVER_HOST_IP` ist die IP des Rechners, auf dem Mosquitto laeuft. Wenn sich die IP durch DHCP aendert, muessen die Boards neu geflasht oder die Adresse angepasst werden.

### CalculateServer

```powershell
Copy-Item CalculateServer\.env.example CalculateServer\.env
```

Wichtige Werte in `CalculateServer/.env`:

```env
MQTT_HOST=localhost
MQTT_PORT=1883
MQTT_TOPIC=receivers/#
MQTT_TOPIC_EPAPER=beaconsniffer/wifi
RECEIVER_IDS=1,2,3

RECEIVER_1_X=0.0
RECEIVER_1_Y=0.0
RECEIVER_2_X=0.0
RECEIVER_2_Y=5.0
RECEIVER_3_X=5.0
RECEIVER_3_Y=2.5

HEATMAP_WEBSOCKET=ws://localhost:8000/ws/heatmap-samples?token=
HEATMAP_TOKEN=change-me
```

Bei 4 Receivern `RECEIVER_IDS=1,2,3,4` setzen und `RECEIVER_4_X/Y` ergaenzen. Die Koordinaten sind Meter im Raum.

### Webserver

```powershell
Copy-Item webserver\.env.example webserver\.env
```

In `webserver/.env` mindestens setzen:

```env
POSTGRES_PASSWORD=change-me
WS_TOKEN=change-me
BACKEND_BIND_IP=127.0.0.1
```

`WS_TOKEN` muss dem `HEATMAP_TOKEN` aus `CalculateServer/.env` entsprechen.

## MQTT-Broker starten

Derzeit wird fuer die Multilateration der Mosquitto-Container im Root-Ordner `Mosquitto` verwendet.

```powershell
cd Mosquitto
docker compose up
```

Der Broker lauscht auf `1883`. Zum Testen der Topics:

```powershell
docker exec -it mymqtt mosquitto_sub -h localhost -t "receivers/#" -v
docker exec -it mymqtt mosquitto_sub -h localhost -t "beaconsniffer/wifi" -v
```

## Firmware bauen und flashen

Vor dem Flashen in `platformio.ini` den passenden `upload_port` und `monitor_port` auf `COM<n>` setzen.

### ePaper LilyGo T5-4.7

```powershell
pio run -e t5-epaper-s3
pio run -e t5-epaper-s3 -t upload
pio device monitor -e t5-epaper-s3
```

Erster Funktionstest: Das ePaper muss starten und ueber das Menue WLANs scannen koennen. Dabei wird bei geoeffneten WLAN-Details regelmaessig auf `beaconsniffer/wifi` published.

### ESP32-S3 Receiver

In `platformio.ini` pro Receiver die ID setzen:

```ini
build_flags =
    -D RECEIVER_ID=1
```

IDs muessen zu `RECEIVER_IDS` im CalculateServer passen. Danach flashen:

```powershell
pio run -e esp32_receiver
pio run -e esp32_receiver -t upload
pio device monitor -e esp32_receiver
```

Die Receiver publishen auf `receivers/<id>`, zum Beispiel `receivers/1`.

### Pycom LoPy4

`pycom_receiver` ist in PlatformIO nur fuer den Build vorgesehen. Das Flashen erfolgt ueber `esptool.py`, nachdem der LoPy4 in den Update-Modus gebracht wurde.

Build:

```powershell
pio run -e pycom_receiver
```

Update-Modus vorbereiten:

```powershell
& "C:\Program Files (x86)\Pycom\Pycom Firmware Update\pycom-fwtool-cli.exe" -p COM<n> -s 115200 --pic -x chip_id
```

Flashen:

```powershell
C:\Users\<username>\.platformio\penv\Scripts\python.exe C:\Users\<username>\.platformio\packages\tool-esptoolpy\esptool.py --chip esp32 --port COM<n> --baud 115200 --before no_reset --after hard_reset write_flash -z --flash_mode dio --flash_freq 40m --flash_size detect 0x1000 .pio\build\pycom_receiver\bootloader.bin 0x8000 .pio\build\pycom_receiver\partitions.bin 0xe000 C:\Users\<username>\.platformio\packages\framework-arduinoespressif32\tools\partitions\boot_app0.bin 0x10000 .pio\build\pycom_receiver\firmware.bin
```

Wenn `Connecting ...` erscheint: `Safe Boot` am Expansionboard gedrueckt halten, `RST` kurz druecken, nach 2-3 Sekunden `Safe Boot` loslassen.

Update-Modus verlassen:

```powershell
& "C:\Program Files (x86)\Pycom\Pycom Firmware Update\pycom-fwtool-cli.exe" -p COM<n> --pic exit
```

## Webserver starten

```powershell
cd webserver
docker compose up --build
```

Danach im Browser:

- `http://localhost:8000/health`
- `http://localhost:8000/dashboard`
- `http://localhost:8000/room`
- `http://localhost:8000/heatmap`

Die Heatmap-Samples kommen ueber WebSocket vom `CalculateServer`.

## CalculateServer starten

Zur WSL wechseln falls die Python-Umgeung darin erstellt wurde.

```powershell
cd CalculateServer
python -m pip install -r requirements.txt
python server.py
```

Der Server muss aus dem Ordner `CalculateServer` gestartet werden, damit `.env` korrekt geladen wird.

Der CalculateServer wartet, bis von allen konfigurierten Receivern aktuelle Pakete vorhanden sind. Danach berechnet er die Position und sendet Samples an den Webserver.

## Test

1. ePaper einzeln testen
   - Firmware flashen
   - ePaper-Menue oeffnen
   - WLAN-Scan starten
   - WLAN-Details anzeigen

2. MQTT-Daten pruefen
   - Mosquitto starten
   - Receiver flashen und einschalten
   - `receivers/#` abonnieren
   - `beaconsniffer/wifi` abonnieren
   - es muessen JSON-Payloads von Receivern und ePaper sichtbar sein

3. Verarbeitung und Heatmap pruefen
   - Webserver starten
   - CalculateServer starten
   - `http://localhost:8000/heatmap` oeffnen
   - sobald aktuelle Receiver- und WLAN-Daten vorhanden sind, erscheinen Heatmap-Samples

## Kalibrierung

Die 1m-Kalibrierung ist optional und kann die Entfernungsschaetzung in der konkreten Umgebung verbessern. Stoersignale, Raumgeometrie und Hardware beeinflussen RSSI stark.

Im ePaper-Menue setzt `Calibration` den BLE-iBeacon-Major auf `100`. Die Receiver berechnen daraus einen Wert fuer `oneMeterRssi`, nach etwa 10 Sekunden wird der BLE-iBeacon-Major wieder auf `1` gesetzt.

Ohne Kalibrierung wird ein Default-Wert von -59 dBm verwendet.

## Bekannte Einschraenkungen

- RSSI-basierte Lokalisation ist ungenau und stark von Raum, Ausrichtung und Stoerquellen abhaengig.
- WLAN-Scans und MQTT-Verbindungsaufbau koennen die Bedienung am ePaper kurz blockieren.
- Pycom LoPy4 wird nicht direkt ueber PlatformIO geflasht.
- Bei DHCP-IP-Aenderungen muss `MQTT_SERVER_HOST_IP` in `include/secrets.h` angepasst und neu geflasht werden.

## Wichtige Topics und Payloads

Receiver:

```text
receivers/<id>
```

Beispiel:

```json
{"target":"ePaperBLE_Sender","rssi":-65,"oneMeterRssi":-59}
```

ePaper WLAN:

```text
beaconsniffer/wifi
```

Beispiel:

```json
{"ssid":"HomeWifi","bssid":"AA:BB:CC:DD:EE:FF","rssi":-58,"channel":4}
```
