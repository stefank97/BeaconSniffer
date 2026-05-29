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
data_lock = threading.Lock()

# Environment variables
def get_required_env(name):
    value = os.getenv(name)
    if value is None or value == "":
        raise ValueError(f"Missing {name} in environment")
    return value


def get_required_float_env(name):
    return float(get_required_env(name))


host = get_required_env("MQTT_HOST")
port = get_required_env("MQTT_PORT")
topic = get_required_env("MQTT_TOPIC")
epaper_topic = get_required_env("MQTT_TOPIC_EPAPER")
heatmap_websocket = get_required_env("HEATMAP_WEBSOCKET")
heatmap_token = get_required_env("HEATMAP_TOKEN")

port = int(port) #If done too early, it crashed before the if-control!

# Create a client instance
client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1, "SubscriberClient")

latest_wifi = None
MQTT_PACKET_VALID_SECONDS = get_required_float_env("MAX_SAMPLE_AGE_SECONDS")


def is_recent_packet(packet, now=None):
    if packet is None:
        return False

    received_at = packet.get("received_at")
    if received_at is None:
        return False

    if now is None:
        now = time.monotonic()

    return now - received_at <= MQTT_PACKET_VALID_SECONDS


def get_receiver_pos(receiver_id):
    return (
        get_required_float_env(f"RECEIVER_{receiver_id}_X"),
        get_required_float_env(f"RECEIVER_{receiver_id}_Y"),
    )


def get_receiver_ids():
    receiver_ids = get_required_env("RECEIVER_IDS")

    return [
        int(receiver_id.strip())
        for receiver_id in receiver_ids.split(",")
        if receiver_id.strip()
    ]


def build_receivers():
    return {
        receiver_id: {
            "position": get_receiver_pos(receiver_id),
            "measured_power": None,
            "samples": deque(maxlen=20),
            "kalman_filter": initialize_kalman_filter(),
        }
        for receiver_id in get_receiver_ids()
    }


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


receivers = build_receivers()
if len(receivers) < 3:
    logging.error("At least 3 receivers must be configured")
    exit(1)

locationEstimator = TrilaterationController(
    receivers=receivers,
    path_loss_exponent=get_required_float_env("PATH_LOSS_EXPONENT"),
    min_distance_meters=get_required_float_env("MIN_DISTANCE_METERS"),
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
            with data_lock:
                latest_wifi = {
                    "ssid": response["ssid"],
                    "bssid": response["bssid"],
                    "wifi_rssi": response["rssi"],
                    "received_at": time.monotonic(),
                }
            logging.info(f"Latest WiFi: {latest_wifi}")
            return

        # ESP receiver payload: {"target":"...","rssi":-65,"oneMeterRssi":-59}
        response["time"] = datetime.now()
        response["received_at"] = time.monotonic()
        response["address"] = response.get("target", "unknown")

        if not message.topic.startswith("receivers/"):
            return logging.error("Unknown topic received: " + message.topic)

        try:
            receiver_id = int(message.topic.rsplit("/", 1)[1])
        except ValueError:
            return logging.error("Invalid receiver topic received: " + message.topic)

        if receiver_id not in receivers:
            return logging.error(f"Receiver {receiver_id} is not configured")

        with data_lock:
            receiver = receivers[receiver_id]
            if "oneMeterRssi" in response:
                locationEstimator.set_measured_power(
                    receiver_id, response["oneMeterRssi"]
                )
            response["filtered_rssi"] = apply_kalman_filter(
                receiver["kalman_filter"], response["rssi"]
            )
            receiver["samples"].append(response)

    except Exception as e:
        logging.error("Error processing message: " + str(e))


# Assign event handlers
client.on_connect = on_connect
client.on_message = on_message


def process_values():
    while not stop_threads:
        with data_lock:
            now = time.monotonic()
            latest_samples = {
                receiver_id: receiver["samples"][-1]
                for receiver_id, receiver in receivers.items()
                if receiver["samples"] and is_recent_packet(receiver["samples"][-1], now)
            }
            wifi = latest_wifi if is_recent_packet(latest_wifi, now) else None

        # Calculate the estimated position
        if len(latest_samples) < len(receivers):
            logging.info(
                "Not enough recent data to calculate position "
                f"(valid window: {MQTT_PACKET_VALID_SECONDS:.0f}s)"
            )
            time.sleep(5)
            continue

        missing_measured_power = [
            receiver_id
            for receiver_id, receiver in receivers.items()
            if receiver["measured_power"] is None
        ]
        if missing_measured_power:
            logging.info(
                "Waiting for oneMeterRssi from receivers: "
                + ", ".join(str(receiver_id) for receiver_id in missing_measured_power)
            )
            time.sleep(5)
            continue

        logging.info(
            "Latest Values: "
            + " | ".join(
                f"{receiver_id}: {sample['rssi']}"
                for receiver_id, sample in sorted(latest_samples.items())
            )
        )
        logging.info(
            "Latest Filtered: "
            + " | ".join(
                f"{receiver_id}: {sample['filtered_rssi']}"
                for receiver_id, sample in sorted(latest_samples.items())
            )
        )

        rssi_by_receiver = {
            receiver_id: sample["filtered_rssi"][0]
            for receiver_id, sample in latest_samples.items()
        }

        with data_lock:
            position = locationEstimator.get_position(rssi_by_receiver)
        logging.info(f"Estimated position: {position}")

        if wifi is None:
            logging.info(
                "No recent WiFi data, not sending heatmap sample "
                f"(valid window: {MQTT_PACKET_VALID_SECONDS:.0f}s)"
            )
            time.sleep(5)
            continue

        first_sample = latest_samples[min(latest_samples)]
        sample = {
            "target": first_sample.get("target", "ePaperBLE_Sender"),
            "x": round(float(position[0]), 2),
            "y": round(float(position[1]), 2),
            "wifi_rssi": wifi["wifi_rssi"],
            "ssid": wifi["ssid"],
            "bssid": wifi["bssid"],
        }

        try:
            asyncio.run(send_heatmap_sample(sample))
            logging.info(f"Sent heatmap sample: {sample}")
        except Exception as e:
            logging.error("Error sending heatmap sample: " + str(e))

        time.sleep(get_required_float_env("SENDING_INTERVAL_SECONDS"))


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
