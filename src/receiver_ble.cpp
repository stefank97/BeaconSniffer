#include <Arduino.h>
#include <BLEAdvertisedDevice.h>
#include <BLEDevice.h>
#include <BLEScan.h>
#include <BLEUtils.h>

#include "wifi_mqtt_connector.h"
#include <WiFi.h>
#include <PubSubClient.h>

#include "oneMeterCalibration.h"

//Name of ePaper for filtering! //FutureWork == change filtering to UUID...
constexpr const char *TARGET_BLE_NAME = "ePaperBLE_Sender";

//How long should be scanned for ePaper-BLEs:
constexpr int SCAN_TIME_SECONDS = 1;

//Change each Number for each ESP32 from 1 - n //FutureWork == set it in the platformio.ini for easy change for uploads:
constexpr const int RECEIVER_ID = 1;
constexpr const char *MQTT_TOPIC = "receivers/1";
constexpr const char *MQTT_CLIENT_NAME_ID = "esp32-receiver-1";
//Change each Number for each ESP32 from 1 - n

//Globals for MQTT_PAYLOAD:
int latestRssi = 0;
bool hasNewRssi = false;
int oneMeterRssi = -59; //Calibration, or Default -59...

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

      latestRssi = advertisedDevice.getRSSI();
      hasNewRssi = true; //Only send MQTT-Message in loop() if new Beacon is sniffed...


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

        if (major == 100) {
          //extract 1m Value:
          // oneMeterRssi = static_cast<int8_t>(data[24]); //WRONG USE the calculated value!!!

          OneMeterCalibration::addRssiSample(advertisedDevice.getRSSI());

          if (OneMeterCalibration::checkRssiSamplesReady()) {
            oneMeterRssi = OneMeterCalibration::calculateMedianRssi();

            Serial.printf("Median RSSI nach 100 Paketen: %d dBm\n", oneMeterRssi);

            OneMeterCalibration::reset();
          }
        }
        //MEDIAN END
      }
    }
  };

  void setup() {
    Serial.begin(115200);
    delay(3000);

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

    if (hasNewRssi) {
      hasNewRssi = false;

      char payload[128];
      snprintf(payload, sizeof(payload),
              "{\"target\":\"%s\",\"rssi\":%d,\"oneMeterRssi\":%d}",
              TARGET_BLE_NAME,
              latestRssi,
              oneMeterRssi);

      bool ok = mqttClient.publish(MQTT_TOPIC, payload);

      Serial.printf("MQTT publish %s: %s\n", ok ? "ok" : "failed", payload);
    }
  }
}

