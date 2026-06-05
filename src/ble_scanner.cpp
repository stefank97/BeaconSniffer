#include "ble_scanner.h"
#include "display.h"

#include <Arduino.h>
#include <BLEDevice.h>
#include <BLEScan.h>
#include <BLEAdvertisedDevice.h>


namespace BleScanner {

    struct BleDeviceInfo {
        String name;
        String address;
        int rssi;
    };

    static const int maxDevices = 10;
    static BleDeviceInfo devices[maxDevices];
    static int deviceCount = 0;
    static int selectedListItem = 0;

    static int selectedDevice = 0;
    static bool detailsActive = false;

    void scanAndShowList() {
        BLEScan *scan = BLEDevice::getScan();
        scan->setActiveScan(true);
        scan->setInterval(100);
        scan->setWindow(99);

        BLEScanResults results = scan->start(5, false);

        deviceCount = 0;
        selectedListItem = 0;
        selectedDevice = 0;
        detailsActive = false;

        for (int i = 0; i < results.getCount() && deviceCount < maxDevices; i++) {
            BLEAdvertisedDevice device = results.getDevice(i);

            devices[deviceCount].name = device.haveName()
                ? String(device.getName().c_str())
                : String("Unknown");

            devices[deviceCount].address = String(device.getAddress().toString().c_str());
            devices[deviceCount].rssi = device.getRSSI();

            deviceCount++;
        }

        scan->clearResults();
        showList();
    }

    void showList() {
        Display::clear();

        Display::printLine(0, selectedListItem == 0 ? "> Return to Main Menu" : "  Return to Main Menu");
        Display::printLine(1, "--BLE scan results--");

        for (int i = 0; i < deviceCount; i++) {
            int listItem = i + 1;

            String line = String(selectedListItem == listItem ? "> " : "  ") +
                          String(i + 1) + ": " +
                          devices[i].name + " " +
                          String(devices[i].rssi) + "dBm";

            Display::printLine(i + 2, line.c_str());
        }

        Display::refresh();
    }

    void nextSelection() {
        selectedListItem++;
        selectedListItem %= (deviceCount + 1);

        if (selectedListItem > 0) {
            selectedDevice = selectedListItem - 1;
        }

        showList();
    }

    bool returnSelected() {
        return selectedListItem == 0;
    }

    void showDetails() {
        if (selectedListItem == 0) {
            return;
        }

        Display::clear();

        if (deviceCount == 0) {
            Display::printLine(0, "No BLE selected");
            Display::refresh();
            return;
        }

        BleDeviceInfo &device = devices[selectedDevice];

        Display::printLine(0, "BLE details");
        Display::printLine(1, device.name.c_str());

        String rssi = "RSSI: " + String(device.rssi) + "dBm";
        Display::printLine(2, rssi.c_str());

        String address = "MAC: " + device.address;
        Display::printLine(3, address.c_str());

        Display::refresh();

        detailsActive = true;
    }

    void exitDetails() {
        detailsActive = false;
    }

}