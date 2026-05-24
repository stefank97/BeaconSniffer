#include <Arduino.h>
#include "epaper_sender_ble.h"

#define BLE_DEVICE_NAME "ePaperBLE_Sender"

//relocate into SIGNATURE of the functions later!
#define BEACON_UUID "00000000-0000-0000-0000-000000000001" //ProjectID //Future Work own UUID aber für Testing ist das einfacher...
#define BEACON_MAJOR 1 //Version
#define BEACON_MINOR 1 //ePaperID
#define CALIBRATED_RSSI -52 // 1m Calculation for Example - self tested in clean-environment!

namespace SenderBle {
  BLEServer *pServer;
  BLEAdvertising *pAdvertising;

  void setup() {
    Serial.begin(115200);
    delay(1000);

    Serial.println("ePaper_Sender_Start_Setup:");

    BLEDevice::init(BLE_DEVICE_NAME);
    pServer = BLEDevice::createServer();

    BLEBeacon beacon;
    beacon.setManufacturerId(0x4C00);
    beacon.setProximityUUID(BLEUUID(BEACON_UUID));
    beacon.setMajor(BEACON_MAJOR);
    beacon.setMinor(BEACON_MINOR);
    beacon.setSignalPower(CALIBRATED_RSSI);

    std::string beaconData = beacon.getData();

    Serial.print("Manufacturere data for iBeacon are set.");
    // Serial.print("Raw manufacturer data: ");
    // for (size_t i = 0; i < beaconData.length(); i++) {
    //   Serial.printf("%02X ", (uint8_t)beaconData[i]);
    // }
    // Serial.println();

    BLEAdvertisementData advertisementData;
    advertisementData.setFlags(0x1A);
    advertisementData.setManufacturerData(beaconData);

    pAdvertising = pServer->getAdvertising();
    pAdvertising->setMinInterval(0x40); //0x40 == 40ms ==  ca. 25x pro Sekunde || 0x320 == 500ms == 2x pro Sekunde
    pAdvertising->setMaxInterval(0x40); //0xA0 == 100ms == ca. 10x pro Sekunde || usw...
    pAdvertising->setAdvertisementData(advertisementData);
    pAdvertising->start();

    Serial.printf("Beacon started with UUID: %s, Major: %d, Minor: %d\n",
                  BEACON_UUID, BEACON_MAJOR, BEACON_MINOR);
  }

  void loop() {
    delay(5000);
    Serial.printf("Beacon sending läuft noch: \"%s\".\n", BLE_DEVICE_NAME);
  }
}
