#ifndef SENDER_BLE_H
#define SENDER_BLE_H

#include <BLEDevice.h>
#include <BLEUtils.h>
#include <BLEServer.h>
#include <BLEBeacon.h>

namespace SenderBle {
    void setup();
    void loop();
}

#endif