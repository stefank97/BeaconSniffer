#include "input.h"

#include <Arduino.h>
#include "Button2.h"
#include "utilities.h"
#include "display.h"
#include "wifi_scanner.h"

namespace Input {

    enum class ScreenState {
        MainMenu,
        WifiList,
        WifiDetails
    };

    static ScreenState screenState = ScreenState::MainMenu;

    static Button2 navButton(BUTTON_1);
    static int selectedItem = 0;

    void init() {
        navButton.setClickHandler([](Button2 &button) {
            if (screenState == ScreenState::WifiList) {
                WifiScanner::nextSelection();
                return;
            }

            if (screenState == ScreenState::WifiDetails) {
                return;
            }

            selectedItem++;
            selectedItem %=3;
        });

        navButton.setLongClickHandler([] (Button2 &button) {
            if (screenState == ScreenState::MainMenu && selectedItem == 0) {
                WifiScanner::scan();
                setWifiListState();
                return;
            }
            
            if (screenState == ScreenState::WifiList) {
                WifiScanner::showDetails();
                screenState = ScreenState::WifiDetails;
                return;
            }

            if (screenState == ScreenState::WifiDetails) {
                WifiScanner::showListFullScreen();
                setWifiListState();
                return;
            }
        });

        navButton.setLongClickTime(800);
    }

    void loop() {
        navButton.loop();
    }

    void setWifiListState() {
        screenState = ScreenState::WifiList;
    }
}
