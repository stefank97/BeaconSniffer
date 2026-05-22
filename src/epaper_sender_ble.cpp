#include <Arduino.h>
#include "epaper_sender_ble.h"

//relocate into SIGNATURE of the functions later!
#define BEACON_UUID "00000000-0000-0000-0000-000000000001"
#define BEACON_MAJOR 1 //CHANGE if needed
#define BEACON_MINOR 1 //CHANGE if needed

BLEServer *pServer;
BLEAdvertising *pAdvertising;

void epaperBleSenderSetup() {
  Serial.begin(115200);
  delay(1000);

  Serial.println("ESP32 BLE Beacon");

  BLEDevice::init("ESP32 Beacon");
  pServer = BLEDevice::createServer();

  BLEBeacon beacon;
  beacon.setManufacturerId(0x4C00);
  beacon.setProximityUUID(BLEUUID(BEACON_UUID));
  beacon.setMajor(BEACON_MAJOR);
  beacon.setMinor(BEACON_MINOR);
  beacon.setSignalPower(-59);

  std::string beaconData = beacon.getData();

  Serial.print("Raw manufacturer data: ");
  for (size_t i = 0; i < beaconData.length(); i++) {
    Serial.printf("%02X ", (uint8_t)beaconData[i]);
  }
  Serial.println();

  BLEAdvertisementData advertisementData;
  advertisementData.setFlags(0x1A);
  advertisementData.setManufacturerData(beaconData);

  pAdvertising = pServer->getAdvertising();
  pAdvertising->setAdvertisementData(advertisementData);
  pAdvertising->start();

  Serial.printf("Beacon started with UUID: %s, Major: %d, Minor: %d\n",
                BEACON_UUID, BEACON_MAJOR, BEACON_MINOR);
}

void epaperBleSenderLoop() {
  delay(5000);
  printf("Beacon sending läuft noch (hoffentlich)...\n");
}