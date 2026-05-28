#include <Arduino.h>
#include <BLEAdvertisedDevice.h>
#include <BLEDevice.h>
#include <BLEScan.h>
#include <BLEUtils.h>

#include "wifi_mqtt_connector.h"
#include <WiFi.h>
#include <PubSubClient.h>

#include "oneMeterCalibration.h"
#include "secrets.h"

//Name of ePaper for filtering! //FutureWork == change filtering to UUID...
constexpr const char *TARGET_BLE_NAME = "ePaperBLE_Sender";

//How long should be scanned for ePaper-BLEs:
constexpr int SCAN_TIME_SECONDS = 1;

//The build_flag in platformio.ini sets the ID via these string helper:
#define STR_HELPER(x) #x
#define STR(x) STR_HELPER(x)
constexpr const char *MQTT_TOPIC = "receivers/" STR(RECEIVER_ID);
constexpr const char *MQTT_CLIENT_NAME_ID = "esp32-receiver-" STR(RECEIVER_ID);

//Globals for MQTT_PAYLOAD:
int medianRssi = 0;
bool hasNewMedianRssi = false;
int oneMeterRssi = -59; //Calibration needed, or Default -59...

namespace ReceiverBle {
  BLEScan *pBLEScan = nullptr;

  WiFiClient wifiClient;
  PubSubClient mqttClient(wifiClient);

  class AdvertisedDeviceCallbacks : public BLEAdvertisedDeviceCallbacks {
    void onResult(BLEAdvertisedDevice advertisedDevice) override {

      //Check for Name of ePaper, ignore other Beacons: //Future-Work, better would be the UUID
      if (!advertisedDevice.haveName() || advertisedDevice.getName() != TARGET_BLE_NAME){
        return;
      }

      //iBeacon: //data[20..21] = Major //data[22..23] = Minor //data[24] = SignalPower
      if(advertisedDevice.haveManufacturerData()) {
        std::string data = advertisedDevice.getManufacturerData();

        if(data.length() < 25){
          Serial.printf("iBeacon is only %u long, so not 25!\n", data.length());
          return;
        }

        //TODO Implement useful for run-time, now it would need manual changes to work... //Change MAJOR to 100 in ePaper + read manually the 1m Values + add a new field in the mqtt-publish of ESP32-Receiver
        //BEGIN CALIBRATION OF 1m from ePaper to ESP32-Receivers:

        //extract MAJOR: // 1 == normal Beacon, 100 == CalibrationPhase
        uint16_t major =
          (static_cast<uint8_t>(data[20]) << 8) |
          static_cast<uint8_t>(data[21]);

        if (major == 1) {
          OneMeterCalibration::setRssiSampleSize(BLE_BEACON_RSSI_MEDIAN_SIZE);
          OneMeterCalibration::addRssiSample(advertisedDevice.getRSSI());

          if (OneMeterCalibration::checkRssiSamplesReady()){
            medianRssi = OneMeterCalibration::calculateMedianRssi();
            hasNewMedianRssi = true; //Only send MQTT-Message in loop() if new Beacon is sniffed...

            Serial.printf("Median RSSI nach 20 Paketen: %d dBm\n", medianRssi);

            OneMeterCalibration::reset();
          }
        }

        if (major == 100) {
          //extract 1m Value:
          // oneMeterRssi = static_cast<int8_t>(data[24]); //WRONG USE the calculated value!!!
          OneMeterCalibration::setRssiSampleSize(100);

          OneMeterCalibration::addRssiSample(advertisedDevice.getRSSI());

          if (OneMeterCalibration::checkRssiSamplesReady()) {
            oneMeterRssi = OneMeterCalibration::calculateMedianRssi();

            Serial.printf("Median RSSI nach 100 Paketen: %d dBm\n", oneMeterRssi);

            OneMeterCalibration::reset();
          }
        }
      }
    }
  };

  void setup() {
    Serial.begin(115200);
    neopixelWrite(LED_BUILTIN, 0, 0, 0); //Turn off LED, LED will turn on if Setup() was ok!
    delay(2000);

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
    if(!mqttClient.connected()){
      Wifi_Mqtt_Connector::connectMqtt(mqttClient, MQTT_CLIENT_NAME_ID);
    }

    mqttClient.loop();

    if (hasNewMedianRssi) {
      hasNewMedianRssi = false;

      char payload[128];
      snprintf(payload, sizeof(payload),
              "{\"target\":\"%s\",\"rssi\":%d,\"oneMeterRssi\":%d}",
              TARGET_BLE_NAME,
              medianRssi,
              oneMeterRssi);

      bool ok = mqttClient.publish(MQTT_TOPIC, payload);

      Serial.printf("MQTT publish %s: %s\n", ok ? "ok" : "failed", payload);
    }
  }
}

