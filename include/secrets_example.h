#pragma once

#define WIFI_SSID_FOR_MQTT "SSID"
#define WIFI_PW_FOR_MQTT "PW"
#define MQTT_SERVER_HOST_IP "10.0.0.72"
#define MQTT_SERVER_PORT 1883

#define BLE_BEACON_SENDING_INTERVAL 0x40 //"0x40"=40ms=25x pro Sekunde //"0xA0"=100ms=10x pro Sekunde // "0x320"=500ms=2x pro Sekunde
#define BLE_BEACON_RSSI_MEDIAN_SIZE 10 // lower == less accurate, but faster Heatmap