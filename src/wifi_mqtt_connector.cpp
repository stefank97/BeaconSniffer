#include <WiFi.h>
#include <PubSubClient.h>

#include "secrets.h"
#include "wifi_mqtt_connector.h"

//Wifi PubSub Configs:
constexpr const char *WIFI_SSID = WIFI_SSID_FOR_MQTT;
constexpr const char *WIFI_PASSWORD = WIFI_PW_FOR_MQTT;

constexpr const char *MQTT_HOST = MQTT_SERVER_HOST_IP; // Laptop-IP im WLAN
constexpr int MQTT_PORT = MQTT_SERVER_PORT;

namespace Wifi_Mqtt_Connector {

  void connectWifi() {
    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

    Serial.print("Verbinde WLAN");
    while (WiFi.status() != WL_CONNECTED) {
      delay(500);
      Serial.print(".");
    }

    Serial.print("\nWLAN verbunden, IP: ");
    Serial.println(WiFi.localIP());
  }

  void connectMqtt(PubSubClient &mqttClient, const char *clientNameId) {
    mqttClient.setServer(MQTT_HOST, MQTT_PORT);

    while (!mqttClient.connected()) {
      Serial.print("Verbinde MQTT...");

      if (mqttClient.connect(clientNameId)) {
        Serial.println("ok");
      } else {
        Serial.printf("fehlgeschlagen, rc=%d\n", mqttClient.state());
        delay(1000);
      }
    }
  }

  bool publish(PubSubClient &mqttClient, const char *topic, const char *payload) {
    return mqttClient.publish(topic, payload);
  }
}
