import asyncio
import json
import logging
import os
import threading
import time
from collections import deque
from datetime import datetime

import paho.mqtt.client as mqtt
import websockets
from dotenv import load_dotenv

from calc import TrilaterationController
from filter import apply_kalman_filter, initialize_kalman_filter

# Load env variables from .env file
load_dotenv()

# Logging configuration
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

# State to stop the threads
stop_threads = False

# Environment variables
host = os.getenv("MQTT_HOST")
port = os.getenv("MQTT_PORT")
topic = os.getenv("MQTT_TOPIC")
epaper_topic = os.getenv("MQTT_TOPIC_EPAPER", "beaconsniffer/wifi")
heatmap_websocket = os.getenv("HEATMAP_WEBSOCKET")
heatmap_token = os.getenv("HEATMAP_TOKEN")

if not all([host, port, topic, epaper_topic, heatmap_websocket, heatmap_token]):
    logging.error("Environment variables not set")
    exit(1)

port = int(port) #If done too early, it crashed before the if-control!

# Create a client instance
client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1, "SubscriberClient")

# Stores for messages (max length 10 - removes old values when full)
receiver_1 = deque(maxlen=20)
receiver_2 = deque(maxlen=20)
receiver_3 = deque(maxlen=20)
latest_wifi = None

# Initialize the Kalman filter for the 3 receivers
kf1 = initialize_kalman_filter()
kf2 = initialize_kalman_filter()
kf3 = initialize_kalman_filter()

def get_receiver_pos(receiver_id):
    return (
        float(os.getenv(f"RECEIVER_{receiver_id}_X")),
        float(os.getenv(f"RECEIVER_{receiver_id}_Y")),
    )


def build_heatmap_url():
    if "{token}" in heatmap_websocket:
        return heatmap_websocket.replace("{token}", heatmap_token)

    if heatmap_websocket.endswith("token="):
        return heatmap_websocket + heatmap_token

    separator = "&" if "?" in heatmap_websocket else "?"
    return f"{heatmap_websocket}{separator}token={heatmap_token}"


async def send_heatmap_sample(sample):
    async with websockets.connect(build_heatmap_url(), open_timeout=10) as websocket:
        await websocket.send(json.dumps(sample))


# Initialize the trilateration controller
locationEstimator = TrilaterationController(
    bp_1=get_receiver_pos(1),
    bp_2=get_receiver_pos(2),
    bp_3=get_receiver_pos(3),
    measured_power_1=float(os.getenv("RECEIVER_1_TX_POWER", -59)),
    measured_power_2=float(os.getenv("RECEIVER_2_TX_POWER", -59)),
    measured_power_3=float(os.getenv("RECEIVER_3_TX_POWER", -59)),
    path_loss_exponent=float(os.getenv("PATH_LOSS_EXPONENT", 2.2)),
)


# MQTT event handlers
def on_connect(client, userdata, flags, return_code):
    if return_code != 0:
        return logging.info("could not connect, return code:", return_code)

    logging.info("Connected to broker")
    logging.info("Subscribing to topic: " + topic)
    client.subscribe(topic)
    logging.info("Subscribing to topic: " + epaper_topic)
    return client.subscribe(epaper_topic)


def on_message(client, userdata, message):
    global latest_wifi

    logging.info(message.topic + " - Received message: " + str(message.payload))
    try:
        decoded_message = str(message.payload.decode("utf-8"))
        response = json.loads(decoded_message)

        if message.topic == epaper_topic:
            latest_wifi = {
                "ssid": response["ssid"],
                "bssid": response["bssid"],
                "wifi_rssi": response["rssi"],
            }
            logging.info(f"Latest WiFi: {latest_wifi}")
            return

        # ESP receiver payload: {"target":"...","rssi":-65,"oneMeterRssi":-59}
        response["time"] = datetime.now()
        response["address"] = response.get("target", "unknown")

        # Apply Kalman filter to the RSSI values and store them
        if message.topic == "receivers/1":
            if "oneMeterRssi" in response:
                locationEstimator.measured_power_1 = response["oneMeterRssi"]
            response["filtered_rssi"] = apply_kalman_filter(kf1, response["rssi"])
            receiver_1.append(response)
        elif message.topic == "receivers/2":
            if "oneMeterRssi" in response:
                locationEstimator.measured_power_2 = response["oneMeterRssi"]
            response["filtered_rssi"] = apply_kalman_filter(kf2, response["rssi"])
            receiver_2.append(response)
        elif message.topic == "receivers/3":
            if "oneMeterRssi" in response:
                locationEstimator.measured_power_3 = response["oneMeterRssi"]
            response["filtered_rssi"] = apply_kalman_filter(kf3, response["rssi"])
            receiver_3.append(response)
        else:
            return logging.error("Unknown topic received: " + message.topic)

    except Exception as e:
        logging.error("Error processing message: " + str(e))


# Assign event handlers
client.on_connect = on_connect
client.on_message = on_message


def process_values():
    while not stop_threads:
        if receiver_1 and receiver_2 and receiver_3:
            logging.info(
                f"Latest Values: {' | '.join(str(receiver[-1]['rssi']) for receiver in [receiver_1, receiver_2, receiver_3])}"
            )
            logging.info(
                f"Latest Filtered: {' | '.join(str(receiver[-1]['filtered_rssi']) for receiver in [receiver_1, receiver_2, receiver_3])}"
            )

        # Calculate the estimated position
        if not (receiver_1 and receiver_2 and receiver_3):
            logging.info("Not enough data to calculate position")
            time.sleep(5)
            continue

        rssi_1 = receiver_1[-1]["filtered_rssi"][0]
        rssi_2 = receiver_2[-1]["filtered_rssi"][0]
        rssi_3 = receiver_3[-1]["filtered_rssi"][0]

        # Update the position
        position = locationEstimator.get_position(rssi_1, rssi_2, rssi_3)
        logging.info(f"Estimated position: {position}")

        if latest_wifi is None:
            logging.info("No WiFi data yet, not sending heatmap sample")
            time.sleep(5)
            continue

        sample = {
            "target": receiver_1[-1].get("target", "ePaperBLE_Sender"),
            "x": round(float(position[0]), 2),
            "y": round(float(position[1]), 2),
            "wifi_rssi": latest_wifi["wifi_rssi"],
            "ssid": latest_wifi["ssid"],
            "bssid": latest_wifi["bssid"],
        }

        try:
            asyncio.run(send_heatmap_sample(sample))
            logging.info(f"Sent heatmap sample: {sample}")
        except Exception as e:
            logging.error("Error sending heatmap sample: " + str(e))

        time.sleep(5)

def run():
    global stop_threads

    processing_thread = None
    mqtt_thread = None

    try:
        logging.info("Connecting to broker")
        client.connect(host, port)

        # Start the processing thread
        logging.info("Starting processing thread")
        processing_thread = threading.Thread(target=process_values, daemon=True)
        processing_thread.start()

        # Start the MQTT subscriber loop in a new thread
        logging.info("Starting MQTT subscriber")
        mqtt_thread = threading.Thread(target=client.loop_forever, daemon=True)
        mqtt_thread.start()

        while True:
            time.sleep(1) #Program would end itself here, because mqtt_thread doesnt keep python alive...

    except KeyboardInterrupt:
        logging.info("Gracefully shutting down...")

        # Stop the threads
        stop_threads = True
        client.disconnect()
        logging.info("MQTT disconnected.")

        if processing_thread is not None:
            processing_thread.join()
            logging.info("Processing (display) thread stopped.")

        if mqtt_thread is not None:
            mqtt_thread.join()
            logging.info("MQTT thread stopped.")

        # Exit the program
        exit(0)


if __name__ == "__main__":
    run()
