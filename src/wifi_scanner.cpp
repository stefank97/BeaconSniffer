#include "wifi_scanner.h"
#include <Arduino.h>
#include <WiFi.h>
#include "display.h"

namespace WifiScanner {
    void scan() {
        WiFi.mode(WIFI_STA);
        WiFi.disconnect();
        delay(100);

        int n = WiFi.scanNetworks();
        Serial.printf("Found %d networks\n", n);
        
        const int resultStartingLine = 3;
        
        Display::printLine(resultStartingLine - 1, "--WiFi scan results--");

        
        int maxLines = min(n, 10);

        for (int i = 0; i < maxLines; i++) {
            String line = String(i + 1) + ": " +
                            WiFi.SSID(i) + " " +
                            String(WiFi.RSSI(i)) + "dBm";
                            // + " | Channel: " + WiFi.channel(i)
                            // + " | BSSID: " + WiFi.BSSIDstr(i);
            Serial.println(line);
            Display::printLine( resultStartingLine + i, line.c_str());
        }



        // //DEBUG
        // for (int i = 0; i< n; i++) {
        //     Serial.printf("%d: %s | RSSI: %d dBm | Channel: %d | BSSID: %s\n", 
        //         i+1,
        //         WiFi.SSID(i).c_str(),
        //         WiFi.RSSI(i),
        //         WiFi.channel(i),
        //         WiFi.BSSIDstr(i).c_str()
        //     );
        // }
        Display::refresh();
        WiFi.scanDelete();
    }


}
