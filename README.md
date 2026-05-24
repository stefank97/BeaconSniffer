# ESP32-RECEIVER:

Für "main_receiver.cpp" muss man in "receiver_ble.cpp" pro Gerät die Nummer erhöhen!

Farbe LED ESP32: 1 == rot, 2 == grün, 3 == blau , n == weiß...

```
constexpr const int RECEIVER_ID = 1;
constexpr const char *MQTT_TOPIC = "receivers/1";
constexpr const char *MQTT_CLIENT_ID = "esp32-receiver-1";
```

Zusätzlich muss man unter "secrets_example.h" zu "Secrets.h" kopieren/umbenennen und die WLAN- sowie HOST-Informationen für die WLAN-/MQTT-Verbindung ausfüllen.

# MQTT-Docker-Container

Einfach in Linux bzw. WSL im Ordner "Mosquitto":
```
docker compose up
```

## Test CLI command:

```
docker exec -it mymqtt mosquitto_sub -h localhost -t "receivers/#" -v
```
Die ESP32-Receiver publishen per "receivers/#" den BLE-RSSI Wert vom ePaper (Achtung nicht den WLAN-ePaper-RSSI-Wert)

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


