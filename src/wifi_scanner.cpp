#include "wifi_scanner.h"
#include <Arduino.h>
#include <WiFi.h>
#include "display.h"
#include <WiFiClient.h>
#include <PubSubClient.h>
#include "wifi_mqtt_connector.h"
#include <ArduinoJson.h>

#define MQTT_TOPIC "beaconsniffer/wifi"

namespace WifiScanner {

    static void drawList(int firstLine);
    static int getNetworkByBssid(const String &bssid);
    static void publishNetwork(const NetworkInfo &network);
    static String buildPayload(const NetworkInfo &network);

    static int selectedListItem = 0; //Für main menu (0 main menu, 1 network0, 2 network1, ...)
    static const int listFirstLine = 0;
    static const int maxNetworks = 10;
    static int networkCount = 0;
    static int selectedNetwork = 0;
    static NetworkInfo networks[maxNetworks];

    //Details MQTT 
    static String trackedBssid;
    static bool detailsActive = false;
    static long lastDetailScan = 0;     //letzte Aktualisierung

    //Wifi & Mqtt Client
    static WiFiClient wifiClient;
    static PubSubClient mqttClient(wifiClient);

    void scan() {
        WiFi.mode(WIFI_STA);
        // WiFi.disconnect();
        // delay(100);



        int foundNetworks = WiFi.scanNetworks();

        networkCount = min(foundNetworks, maxNetworks);
        selectedListItem = 0;
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
        Display::printLine(firstLine, selectedListItem == 0 ? "> Return to Main Menu" : "  Return to Main Menu");
        Display::printLine(firstLine + 1, "--WiFi scan results--");

        for (int i = 0; i < networkCount; i++) {
            int listItem = i + 1;
            String line = String(selectedListItem == listItem ? "> " : "  ") +
                        String(i + 1) + ": " +
                        networks[i].ssid + " " +
                        String(networks[i].rssi) + "dBm";

            Display::printLine(firstLine + 2 + i, line.c_str());
        }
    }

    void nextSelection() {
        selectedListItem++;
        selectedListItem %= (networkCount + 1);     //+1 wegen return to main menu.

        if (selectedListItem > 0) {
            selectedNetwork = selectedListItem - 1;
        }

        showList();
    }

    void showDetails() {
        if (selectedListItem == 0) {
            return;
        }
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

        Wifi_Mqtt_Connector::connectWifi();
        Wifi_Mqtt_Connector::connectMqtt(mqttClient, "epaper-wifi-scanner");

    }


    void showList() {
        Display::clear();
        drawList(0);
        Display::refresh();
    }

    void loop() {
        if (!detailsActive) {
            return;
        }
        
        //delay here:
        if (millis() - lastDetailScan < 2000) {
            return;
        }

        int oldSelectedListItem = selectedListItem;
        lastDetailScan = millis();
        scan();
        selectedListItem = oldSelectedListItem;

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

        if (WiFi.status() != WL_CONNECTED) {
            Serial.println("Wifi not connected. Connecting...");
            Wifi_Mqtt_Connector::connectWifi();
        }

        if (!mqttClient.connected()) {
            Serial.println("MQTT Client not connected. Connecting...");
            Wifi_Mqtt_Connector::connectMqtt(mqttClient, "epaper-wifi-scanner");
        }

        mqttClient.loop();
        publishNetwork(network);
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

    static String buildPayload(const NetworkInfo &network) {
        JsonDocument json;

        json["ssid"] = network.ssid;
        json["bssid"] = network.bssid;
        json["rssi"] = network.rssi;
        json["channel"] = network.channel;

        String payload;
        serializeJson(json, payload);

        return payload;
    }

    static void publishNetwork(const NetworkInfo &network) {
        String payload = buildPayload(network);
        bool success = Wifi_Mqtt_Connector::publish(mqttClient, MQTT_TOPIC, payload.c_str());

        if (!success) {
            Serial.println("Publishing of network failed. Payload: ");
            Serial.println(payload);
        } else {
            Serial.println("Publishing of network successful. Payload: ");
            Serial.println(payload);
        }
    }

    bool returnSelected() {
        return selectedListItem == 0;
    }

}
