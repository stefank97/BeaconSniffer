
#ifndef WIFI_MQTT_CONNECTOR_H
#define WIFI_MQTT_CONNECTOR_H

#include <PubSubClient.h> //Wenn ein Header einen Typ in seiner Signatur benutzt "PubSubClient-Reference", muss der Header diesen Typ kennen.

namespace Wifi_Mqtt_Connector {
    void connectWifi();
    void connectMqtt(PubSubClient &mqttClient, const char *clientNameId);
}

#endif