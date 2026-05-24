# ESP32-RECEIVER:

Für "main_receiver.cpp" muss man in "receiver_ble.cpp" pro Gerät die Nummer erhöhen!
```
constexpr const int RECEIVER_ID = 1;
constexpr const char *MQTT_TOPIC = "receivers/1";
constexpr const char *MQTT_CLIENT_ID = "esp32-receiver-1";
```

Zusätzlich muss man unter "secrets_example.h" zu "Secrets.h" kopieren/umbenennen und die WLAN- sowie HOST-Informationen für die WLAN-/MQTT-Verbindung ausfüllen.