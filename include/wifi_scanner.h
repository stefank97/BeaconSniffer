#ifndef WIFI_SCANNER_H
#define WIFI_SCANNER_H

#include <Arduino.h>

namespace WifiScanner {

    struct NetworkInfo {
        String ssid;
        String bssid;
        int rssi;
        int channel;
        int encryption;
    };

    void scan(int mode);
    void nextSelection();
    void showDetails();
    void showList();
    void scanAndShowList();
    void loop();
    void exitDetails();
    bool returnSelected();
}

#endif
