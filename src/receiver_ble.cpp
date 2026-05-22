#include <Arduino.h>
#include <BLEAdvertisedDevice.h>
#include <BLEDevice.h>
#include <BLEScan.h>
#include <BLEUtils.h>

constexpr const char *TARGET_BLE_NAME = "ESP32 Beacon"; //Global Config?
constexpr int SCAN_TIME_SECONDS = 5;

BLEScan *pBLEScan;

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
  Serial.printf("  TX Power: %d dBm\n", static_cast<int8_t>(data[24]));
}

class AdvertisedDeviceCallbacks : public BLEAdvertisedDeviceCallbacks {
  void onResult(BLEAdvertisedDevice advertisedDevice) override {
    if (!advertisedDevice.haveName() || 
        advertisedDevice.getName() != TARGET_BLE_NAME) {
      return;
    }


    Serial.println();
    Serial.println("BLE device gefunden");
    Serial.printf("  Adresse: %s\n", advertisedDevice.getAddress().toString().c_str());
    Serial.printf("  RSSI: %d dBm\n", advertisedDevice.getRSSI());

    Serial.printf("  Name: %s\n", advertisedDevice.getName().c_str());

    if (advertisedDevice.haveManufacturerData()) {
      std::string manufacturerData = advertisedDevice.getManufacturerData();

      Serial.print("  Manufacturer data: ");
      printHex(manufacturerData);
      Serial.println();

      printIBeaconData(manufacturerData);
    }
  }
};

void receiverSetup() {
  Serial.begin(115200);
  delay(1000);

  Serial.println("ESP32 BLE Receiver");

  BLEDevice::init("ESP32 Receiver");

  pBLEScan = BLEDevice::getScan();
  pBLEScan->setAdvertisedDeviceCallbacks(new AdvertisedDeviceCallbacks());
  pBLEScan->setActiveScan(true);
  pBLEScan->setInterval(100);
  pBLEScan->setWindow(99);

  neopixelWrite(LED_BUILTIN, 10, 0, 0); //Receiver is red...
}

void receiverMockupLoop() {
  Serial.println();
  Serial.println("Starte BLE scan...");

  BLEScanResults results = pBLEScan->start(SCAN_TIME_SECONDS, false);

  Serial.printf("Scan fertig. Geraete gefunden: %d\n", results.getCount());
  pBLEScan->clearResults();

  delay(2000);
}
