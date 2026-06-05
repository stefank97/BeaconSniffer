#include "input.h"

#include <Arduino.h>
#include "Button2.h"
#include "utilities.h"
#include "display.h"
#include "wifi_scanner.h"
#include "epaper_sender_ble.h"
#include "ble_scanner.h"

namespace Input {

    enum class ScreenState {
        MainMenu,
        WifiList,
        WifiDetails,
        BleList,
        BleDetails
    };

    static ScreenState screenState = ScreenState::MainMenu;
    static void showMainMenu();
    static void nextMainMenuSelection();
    static const int mainMenuItemCount = 3;

    static bool calibrationActive = false;
    static unsigned long calibrationStartedAt = 0;
    static const unsigned long calibrationDurationMs = 10000;

    static Button2 navButton(BUTTON_1);
    static int selectedItem = 0;

    void init() {
        navButton.setClickHandler([](Button2 &button) {
            if (screenState == ScreenState::MainMenu) {
                nextMainMenuSelection();
                return;
            }
            if (screenState == ScreenState::WifiList) {
                WifiScanner::nextSelection();
                return;
            }

            if (screenState == ScreenState::WifiDetails) {
                return;
            }
            if (screenState == ScreenState::BleList) {
                BleScanner::nextSelection();
                return;
            }
            if(screenState == ScreenState::BleDetails) {
                return;
            }
        });

        navButton.setLongClickHandler([] (Button2 &button) {
            if (screenState == ScreenState::MainMenu) {
                if (selectedItem == 0) {    //WiFi Scanner
                    WifiScanner::scanAndShowList();
                    setWifiListState();
                    return;
                }
                if (selectedItem == 1) { //Bluetooth Scanner
                    BleScanner::scanAndShowList();
                    screenState = ScreenState::BleList;
                    return;
                }
                if (selectedItem == 2) {
                    SenderBle::setMajor(100);
                    calibrationActive = true;
                    calibrationStartedAt = millis();
                    showMainMenu();
                    return;
                }
                

            }
            //Wifi
            if (screenState == ScreenState::WifiList) {
                if (WifiScanner::returnSelected()) {
                    showMainMenu();
                    screenState = ScreenState::MainMenu;
                    return;
                }
                WifiScanner::showDetails();
                screenState = ScreenState::WifiDetails;
                return;
            }

            if (screenState == ScreenState::WifiDetails) {
                WifiScanner::exitDetails();
                WifiScanner::showList();
                setWifiListState();
                return;
            }
            //Ble
            if (screenState == ScreenState::BleList) {
                if (BleScanner::returnSelected()) {
                    showMainMenu();
                    screenState = ScreenState::MainMenu;
                    return;
                }
                BleScanner::showDetails();
                screenState = ScreenState::BleDetails;
                return;
            }

            if (screenState == ScreenState::BleDetails) {
                BleScanner::exitDetails();
                BleScanner::showList();
                screenState = ScreenState::BleList;
                return;
            }



        });

        navButton.setDoubleClickHandler([](Button2 &button) {
            if (screenState == ScreenState::WifiList) {
                WifiScanner::scanAndShowList();
                return;
            }
            if (screenState == ScreenState::BleList) {
                BleScanner::scanAndShowList();
                return;
            }
        });

        navButton.setLongClickTime(800);
        showMainMenu();
    }

    void loop() {
        navButton.loop();

        if (calibrationActive && millis() - calibrationStartedAt >= calibrationDurationMs) {
            SenderBle::setMajor(1);
            calibrationActive = false;
            showMainMenu();
        }
    }

    void setWifiListState() {
        screenState = ScreenState::WifiList;
    }

    static void showMainMenu() {
        Display::clear();

        //MOST IMPORTANT: SNIFFING
        // 'breathing', 32x32px
        const uint8_t epd_bitmap_breathing [] PROGMEM = {
            0xff, 0xef, 0xf7, 0xff, 0xff, 0xcf, 0xf3, 0xff, 0xff, 0xcf, 0xf3, 0xff, 0xff, 0xcf, 0xf3, 0xff, 
            0xff, 0xcf, 0xf3, 0xff, 0xff, 0xcf, 0xf3, 0xff, 0xff, 0xdf, 0xfb, 0xff, 0xff, 0x9f, 0xf9, 0xff, 
            0xff, 0x9f, 0xf9, 0xff, 0xff, 0x9f, 0xf9, 0xff, 0xff, 0x9f, 0xf9, 0xff, 0xff, 0x3f, 0xfc, 0xff, 
            0xfe, 0x7f, 0xfc, 0x7f, 0xfc, 0x7f, 0xfe, 0x3f, 0xf9, 0xff, 0xff, 0x9f, 0xf3, 0xff, 0xff, 0xcf, 
            0xf3, 0xff, 0xff, 0xcf, 0xf3, 0xff, 0xff, 0xcf, 0xf3, 0x8f, 0xf1, 0xcf, 0xf1, 0x87, 0xe1, 0x8f, 
            0xf8, 0x71, 0x8e, 0x1f, 0xfe, 0x78, 0x1e, 0x7f, 0xff, 0xfe, 0x7f, 0xff, 0xff, 0x9f, 0xf9, 0xff, 
            0xff, 0x9f, 0xf9, 0xff, 0xff, 0x93, 0xc9, 0xff, 0xff, 0x33, 0xcc, 0xff, 0xfc, 0x33, 0xcc, 0x3f, 
            0xf0, 0x73, 0xce, 0x0f, 0xfb, 0xe7, 0xe7, 0xdf, 0xff, 0x07, 0xe0, 0xff, 0xff, 0x1f, 0xf8, 0xff
        };

        // Array of all bitmaps for convenience. (Total bytes used to store images in PROGMEM = 144)
        const int epd_bitmap_allArray_LEN = 1;
        const uint8_t* epd_bitmap_allArray[1] = {
            epd_bitmap_breathing
        };

        Display::printLine(0, ">>BeaconSniffer<<", epd_bitmap_breathing);
        // Display::printLine(1, ">>Sniffing for Networks...", epd_bitmap_breathing);

        Display::printLine(1, "--Main Menu--");
        // String beaconMode = "Current Beacon Major: " + String(SenderBle::getMajor());
        // Display::printLine(2, beaconMode.c_str());
        
        Display::printLine(2, selectedItem == 0 ? "> WiFi Scanner" : "  WiFi Scanner");
        Display::printLine(3, selectedItem == 1 ? "> Bluetooth Scanner" : "  Bluetooth Scanner");
        Display::printLine(4, selectedItem == 2 ? "> Calibration" : "  Calibration");
        Display::refresh();
    }

    static void nextMainMenuSelection() {
        selectedItem++;
        selectedItem %= mainMenuItemCount;
        showMainMenu();
    }
}
