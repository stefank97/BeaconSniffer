#include "wifi_scanner.h"
#include <Arduino.h>
#include <WiFi.h>
#include "display.h"

namespace WifiScanner {

    static void drawList(int firstLine);
    static void showList();
    static int getNetworkByBssid(const String &bssid);

    static const int listFirstLine = 3;
    static const int maxNetworks = 10;
    static int networkCount = 0;
    static int selectedNetwork = 0;
    static NetworkInfo networks[maxNetworks];

    //Details MQTT 
    static String trackedBssid;
    static bool detailsActive = false;
    static long lastDetailScan = 0;     //letzte Aktualisierung

    void scan() {
        WiFi.mode(WIFI_STA);
        WiFi.disconnect();
        delay(100);



        int foundNetworks = WiFi.scanNetworks();

        networkCount = min(foundNetworks, maxNetworks);
        selectedNetwork = 0;


        Serial.printf("Found %d networks\n", foundNetworks);

        for (int i = 0; i < networkCount; i++) {
            networks[i].ssid = WiFi.SSID(i);
            networks[i].bssid = WiFi.BSSIDstr(i);
            networks[i].rssi = WiFi.RSSI(i);
            networks[i].channel = WiFi.channel(i);
            networks[i].encryption = WiFi.encryptionType(i);
        }
        
        WiFi.scanDelete();
        //showList();
    }


    static void drawList(int firstLine) {
        Display::printLine(firstLine, "--WiFi scan results--");

        for (int i = 0; i < networkCount; i++) {
            String line = String(i == selectedNetwork ? "> " : "  ") +
                        String(i + 1) + ": " +
                        networks[i].ssid + " " +
                        String(networks[i].rssi) + "dBm";

            Display::printLine(firstLine + 1 + i, line.c_str());
        }
    }

    void nextSelection() {
        if (networkCount == 0) {
            return;
        }

        selectedNetwork++;
        selectedNetwork %= networkCount;

        showList();
    }

    void showDetails() {
        Display::clear();

        if (networkCount == 0) {

            Display::printLine(0, "No WiFi selected");
            Display::refresh();
            return;
        }

        NetworkInfo &network = networks[selectedNetwork];

        Display::printLine(0, "WiFi details");
        Display::printLine(1, network.ssid.c_str());

        String rssi = "RSSI: " + String(network.rssi) + "dBm";
        Display::printLine(2, rssi.c_str());

        String channel = "Channel: " + String(network.channel);
        Display::printLine(3, channel.c_str());

        String bssid = "BSSID: " + network.bssid;
        Display::printLine(4, bssid.c_str());

        Display::refresh();

        trackedBssid = networks[selectedNetwork].bssid;
        detailsActive = true;
        lastDetailScan = 0;

    }


    static void showList() {
        int firstLine = listFirstLine;
        Display::clearLine(firstLine - 1, networkCount + 2);
        drawList(firstLine);
        Display::refreshLine(firstLine - 1, networkCount + 2);
    }

    void showListFullScreen() {
        Display::clear();
        drawList(0);
        Display::refresh();
    }

    void loop() {
        if (!detailsActive) {
            return;
        }

        if (millis() - lastDetailScan < 5000) {
            return;
        }

        lastDetailScan = millis();
        scan();

        int index = getNetworkByBssid(trackedBssid);

        if (index == -1) {
            Serial.println("Tracked WiFi not found.");
            return;
        }

        selectedNetwork = index;

        //DEBUG
        NetworkInfo &network = networks[selectedNetwork];

        Serial.println("Sending updated WiFi data: ");
        Serial.println(network.ssid);
        Serial.println(network.bssid);
        Serial.println(network.rssi);
    }

    void scanAndShowList() {
        scan();
        showList();
    }

    void exitDetails() {
        detailsActive = false;
    }

    static int getNetworkByBssid(const String &bssid) {
        for (int i = 0; i < networkCount; i++) {
            if (networks[i].bssid == bssid) {
                return i;
            }
        }
        return -1;
    }
}
