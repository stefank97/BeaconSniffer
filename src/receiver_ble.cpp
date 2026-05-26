#include <Arduino.h>
#include <BLEAdvertisedDevice.h>
#include <BLEDevice.h>
#include <BLEScan.h>
#include <BLEUtils.h>

#include "wifi_mqtt_connector.h"
#include <WiFi.h>
#include <PubSubClient.h>

//Name of ePaper for filtering!
constexpr const char *TARGET_BLE_NAME = "ePaperBLE_Sender";

//How long should be scanned for ePaper-BLEs:
constexpr int SCAN_TIME_SECONDS = 1;

//TODO IOT-RSSI-Calibration into Header-File.
//To calibrate the IOT-RSSI for 1m: BEGIN SETUP
constexpr const int RSSI_SAMPLE_COUNT = 100;
int rssiSamplesArray[RSSI_SAMPLE_COUNT];
size_t rssiSampleIndex = 0;
bool rssiSamplesReady = false;
//END SETUP

//Change each Number for each ESP32 from 1 - n //Later - set it in the platformio.ini for easy change:
constexpr const int RECEIVER_ID = 1;
constexpr const char *MQTT_TOPIC = "receivers/1";
constexpr const char *MQTT_CLIENT_NAME_ID = "esp32-receiver-1";
//Change each Number for each ESP32 from 1 - n

//Globals for MQTT_PAYLOAD:
int latestRssi = 0;
uint32_t latestSeenMs = 0;
bool hasNewRssi = false;


namespace ReceiverBle {
  BLEScan *pBLEScan = nullptr;

  WiFiClient wifiClient;
  PubSubClient mqttClient(wifiClient);

  //IOT-RSSI-CALIBRATION BEGIN:
  void addRssiSample(int rssi) {
    if (rssiSampleIndex >= RSSI_SAMPLE_COUNT) {
      return;
    }

    rssiSamplesArray[rssiSampleIndex] = rssi;
    rssiSampleIndex++;

    if (rssiSampleIndex == RSSI_SAMPLE_COUNT) {
      rssiSamplesReady = true;
    }
  }

  int calculateMedianRssi() {
    int sortedSamples[RSSI_SAMPLE_COUNT];

    for (size_t i = 0; i < RSSI_SAMPLE_COUNT; i++) {
      sortedSamples[i] = rssiSamplesArray[i];
    }

    for (size_t i = 0; i < RSSI_SAMPLE_COUNT - 1; i++) {
      for (size_t j = i + 1; j < RSSI_SAMPLE_COUNT; j++) {
        if (sortedSamples[j] < sortedSamples[i]) {
          int temp = sortedSamples[i];
          sortedSamples[i] = sortedSamples[j];
          sortedSamples[j] = temp;
        }
      }
    }

  return (sortedSamples[49] + sortedSamples[50]) / 2;
}
//IOT-RSSI-CALIBRATION END:

  void printHex(const std::string &data) {
    for (size_t i = 0; i < data.length(); i++) {
      Serial.printf("%02X ", static_cast<uint8_t>(data[i]));
    }
  }

  uint16_t readBigEndian16(const std::string &data, size_t offset) {
    return (static_cast<uint8_t>(data[offset]) << 8) |
          static_cast<uint8_t>(data[offset + 1]);
  }

  void printIBeaconData(const std::string &data) {
    if (data.length() < 25) {
      return;
    }

    const bool isIBeacon = static_cast<uint8_t>(data[0]) == 0x4C &&
                          static_cast<uint8_t>(data[1]) == 0x00 &&
                          static_cast<uint8_t>(data[2]) == 0x02 &&
                          static_cast<uint8_t>(data[3]) == 0x15;

    if (!isIBeacon) {
      return;
    }

    Serial.println("  iBeacon erkannt");
    Serial.print("  UUID: ");
    for (size_t i = 4; i < 20; i++) {
      Serial.printf("%02X", static_cast<uint8_t>(data[i]));
      if (i == 7 || i == 9 || i == 11 || i == 13) {
        Serial.print("-");
      }
    }
    Serial.println();

    Serial.printf("  Major: %u\n", readBigEndian16(data, 20));
    Serial.printf("  Minor: %u\n", readBigEndian16(data, 22));
    Serial.printf("  Calibrated-RSSI: %d dBm\n", static_cast<int8_t>(data[24]));
  }

  class AdvertisedDeviceCallbacks : public BLEAdvertisedDeviceCallbacks {
    void onResult(BLEAdvertisedDevice advertisedDevice) override {

      //REAL VALUES SEND: //ONLY FOR TRILATERATION!
      if (!advertisedDevice.haveName() || advertisedDevice.getName() != TARGET_BLE_NAME){
        return;
      }

      latestRssi = advertisedDevice.getRSSI();
      hasNewRssi = true; //Only send MQTT-Message in loop() if new Beacon is sniffed...

      //Check Name of ePaper!
      // if (!advertisedDevice.haveName() || 
      //     advertisedDevice.getName() != TARGET_BLE_NAME) {
      //   return;
      // }

      //BEGIN Debug Output of ePaper Name + RSSI Value:
      // Serial.printf("  Name: %s\n", advertisedDevice.getName().c_str());
      // Serial.printf("  Real-RSSI: %d dBm\n", advertisedDevice.getRSSI());
      //END

      //BEGIN: Debug Beacon Data - But it has Problems, callback is not fast enough UI-Data-Fuck-up-happens...
      /*
      if (advertisedDevice.haveManufacturerData()) {
        std::string manufacturerData = advertisedDevice.getManufacturerData();

        Serial.print("  Manufacturer data: ");
        printHex(manufacturerData);
        Serial.println();

        printIBeaconData(manufacturerData);
      }
      */
      //END

      //MEDIAN CONTROL FOR 1m CALCULATE:
      /*
      if (advertisedDevice.haveManufacturerData()) {
        addRssiSample(advertisedDevice.getRSSI());

        if (rssiSamplesReady) {
          int medianRssi = calculateMedianRssi();

          Serial.printf("Median RSSI nach 100 Paketen: %d dBm\n", medianRssi);

          rssiSampleIndex = 0;
          rssiSamplesReady = false;
        }
      }
      */
      //MEDIAN END
    }
  };

  void setup() {
    Serial.begin(115200);
    delay(3000);
    // Serial.println("\n=== Receiver setup entered ===");

    //Setup Wifi:
    Serial.println("\nconnect to Wifi start...");
    Wifi_Mqtt_Connector::connectWifi();
    //Setup MQTT:
    Serial.println("Connect to Mqtt start...");
    Wifi_Mqtt_Connector::connectMqtt(mqttClient, MQTT_CLIENT_NAME_ID);

    //Setup Scanning:
    Serial.println("ESP32 BLE Receiver");
    BLEDevice::init("ESP32 BLE Receiver");

    pBLEScan = BLEDevice::getScan();
    pBLEScan->setAdvertisedDeviceCallbacks(new AdvertisedDeviceCallbacks(), true, true); //Ovveride with returned serial-monitor debug info.
    pBLEScan->setActiveScan(true);
    pBLEScan->setInterval(100); // 100x 0,625ms scannen
    pBLEScan->setWindow(99); // 99x davon wirklich scannen und 1x sleep...

    switch (RECEIVER_ID) {
      case 1:
        neopixelWrite(LED_BUILTIN, 10, 0, 0); // red
        break;
      case 2:
        neopixelWrite(LED_BUILTIN, 0, 10, 0); // green
        break;
      case 3:
        neopixelWrite(LED_BUILTIN, 0, 0, 10); // blue
        break;
      default:
        neopixelWrite(LED_BUILTIN, 10, 10, 10); // white
        break;
      }
  }

  void loop() {
    //BLE-Scan:
    BLEScanResults results = pBLEScan->start(SCAN_TIME_SECONDS, false);
    // Serial.printf("Scan fertig. Insgesamt %d Geräte in der Nähe.\n", results.getCount());
    pBLEScan->clearResults();

    //MQTT:
    mqttClient.loop();

    if(!mqttClient.connected()){
      Wifi_Mqtt_Connector::connectMqtt(mqttClient, MQTT_CLIENT_NAME_ID);
    }

    //
    if (hasNewRssi) {
      hasNewRssi = false;

      char payload[128];
      snprintf(payload, sizeof(payload),
              "{\"target\":\"%s\",\"rssi\":%d}",
              TARGET_BLE_NAME,
              latestRssi);

      bool ok = mqttClient.publish(MQTT_TOPIC, payload);

      Serial.printf("MQTT publish %s: %s\n", ok ? "ok" : "failed", payload);
    }
  }
}

