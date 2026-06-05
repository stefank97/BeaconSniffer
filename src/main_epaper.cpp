#include <Arduino.h>
#include "display.h"
#include "ble_scanner.h"
#include "location.h"
#include "wifi_scanner.h"
#include "epaper_sender_ble.h"
#include "input.h"


void setup() {
  Serial.begin(115200);

  Display::init();
  Input::init();

  //Debug
  Serial.println("Start BeaconSniffer");
  //WifiScanner::scan();

  //Send BLE Beacons for later localisation:
  SenderBle::setup();
}

void loop() {
  Input::loop();
  SenderBle::loop(); //Nur für Debugging, aber da der BLE-Chip alles übernimmt ist das nur Mockup!
  WifiScanner::loop();
  BleScanner::loop();
}




