import json
import os
import time
import threading
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import paho.mqtt.client as mqtt
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from psycopg2.extras import Json, RealDictCursor
from psycopg2.pool import ThreadedConnectionPool


MQTT_HOST = os.getenv("MQTT_HOST", "mosquitto")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_TOPIC = os.getenv("MQTT_TOPIC", "iot/wifi/measurements/#")

DB_HOST = os.getenv("DB_HOST", "postgres")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
DB_NAME = os.getenv("DB_NAME", "iot_wifi")
DB_USER = os.getenv("DB_USER", "iotuser")
DB_PASSWORD = os.getenv("DB_PASSWORD", "iotpass")

WS_TOKEN = os.getenv("WS_TOKEN", "devtoken")

DEFAULT_ROOM_WIDTH = 5.0
DEFAULT_ROOM_HEIGHT = 4.0

VALID_DEVICE_IDS = ["esp01", "esp02", "esp03", "esp04"]

messages = deque(maxlen=1000)
messages_lock = threading.Lock()

mqtt_client = None
db_pool = None


def wait_for_database():
    global db_pool

    while True:
        try:
            db_pool = ThreadedConnectionPool(
                minconn=1,
                maxconn=10,
                host=DB_HOST,
                port=DB_PORT,
                dbname=DB_NAME,
                user=DB_USER,
                password=DB_PASSWORD,
            )
            print("Connected to PostgreSQL")
            return
        except Exception as e:
            print(f"PostgreSQL not ready yet: {e}")
            time.sleep(2)


def init_database():
    conn = db_pool.getconn()

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS devices (
                    device_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    x DOUBLE PRECISION NOT NULL,
                    y DOUBLE PRECISION NOT NULL,
                    room TEXT DEFAULT 'default',
                    enabled BOOLEAN NOT NULL DEFAULT TRUE
                );
                """
            )

            # Default-Positionen nur beim ersten Anlegen einfügen.
            # Wichtig: ON CONFLICT DO NOTHING, damit manuell gesetzte ESP-Positionen
            # nach einem Container-/Server-Neustart nicht überschrieben werden.
            cur.execute(
                """
                INSERT INTO devices (device_id, name, x, y, room, enabled)
                VALUES
                    ('esp01', 'ESP Receiver 1 - links unten', 0, 0, 'Raum 1', TRUE),
                    ('esp02', 'ESP Receiver 2 - links oben', 0, 4, 'Raum 1', TRUE),
                    ('esp03', 'ESP Receiver 3 - rechts oben', 5, 4, 'Raum 1', TRUE),
                    ('esp04', 'ESP Receiver 4 - rechts unten', 5, 0, 'Raum 1', TRUE)
                ON CONFLICT (device_id) DO NOTHING;
                """
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS measurements (
                    id BIGSERIAL PRIMARY KEY,
                    topic TEXT NOT NULL,
                    device_id TEXT,
                    ssid TEXT,
                    bssid TEXT,
                    rssi INTEGER,
                    x DOUBLE PRECISION,
                    y DOUBLE PRECISION,
                    raw_payload JSONB NOT NULL,
                    validation_error TEXT,
                    received_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                """
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS heatmap_samples (
                    id BIGSERIAL PRIMARY KEY,
                    target TEXT NOT NULL,
                    x DOUBLE PRECISION NOT NULL,
                    y DOUBLE PRECISION NOT NULL,
                    wifi_rssi INTEGER NOT NULL,
                    ssid TEXT,
                    bssid TEXT,
                    confidence DOUBLE PRECISION,
                    receivers JSONB,
                    raw_payload JSONB NOT NULL,
                    received_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                """
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS room_objects (
                    object_id TEXT PRIMARY KEY,
                    object_type TEXT NOT NULL,
                    name TEXT NOT NULL,
                    x DOUBLE PRECISION NOT NULL,
                    y DOUBLE PRECISION NOT NULL,
                    enabled BOOLEAN NOT NULL DEFAULT TRUE,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                """
            )

            cur.execute(
                """
                ALTER TABLE measurements
                ADD COLUMN IF NOT EXISTS validation_error TEXT;
                """
            )

        conn.commit()
        print("Database tables are ready")

    finally:
        db_pool.putconn(conn)


def to_int_or_none(value):
    try:
        if value is None or value == "":
            return None
        return int(float(value))
    except (ValueError, TypeError):
        return None


def to_float_or_none(value):
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (ValueError, TypeError):
        return None


def save_measurement(topic: str, payload: dict):
    conn = db_pool.getconn()

    try:
        errors = []

        if not isinstance(payload, dict):
            payload = {
                "value": payload,
                "error": "Payload is valid JSON, but not a JSON object",
            }
            errors.append("Payload is not a JSON object")

        device_id = payload.get("device_id")
        ssid = payload.get("ssid")
        bssid = payload.get("bssid")
        rssi = to_int_or_none(payload.get("rssi"))

        if not device_id:
            errors.append("device_id is missing")

        if rssi is None:
            errors.append("rssi is missing or invalid")

        x = None
        y = None

        with conn.cursor() as cur:
            if device_id:
                cur.execute(
                    """
                    SELECT x, y
                    FROM devices
                    WHERE device_id = %s
                    AND enabled = TRUE
                    """,
                    (device_id,),
                )

                device_row = cur.fetchone()

                if device_row:
                    x = device_row[0]
                    y = device_row[1]
                else:
                    errors.append(f"unknown device_id: {device_id}")
                    x = to_float_or_none(payload.get("x"))
                    y = to_float_or_none(payload.get("y"))

            if x is not None and x < 0:
                errors.append("x must not be negative")
                x = None

            if y is not None and y < 0:
                errors.append("y must not be negative")
                y = None

            validation_error = "; ".join(errors) if errors else None

            cur.execute(
                """
                INSERT INTO measurements
                (topic, device_id, ssid, bssid, rssi, x, y, raw_payload, validation_error)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    topic,
                    device_id,
                    ssid,
                    bssid,
                    rssi,
                    x,
                    y,
                    Json(payload),
                    validation_error,
                ),
            )

        conn.commit()

    except Exception as e:
        conn.rollback()
        print(f"Failed to save measurement: {e}")

    finally:
        db_pool.putconn(conn)


def save_heatmap_sample(payload: dict):
    conn = db_pool.getconn()

    try:
        if not isinstance(payload, dict):
            raise ValueError("Payload must be a JSON object")

        target = payload.get("target")
        x = to_float_or_none(payload.get("x"))
        y = to_float_or_none(payload.get("y"))

        # Kompatibilität:
        # Bevorzugt wifi_rssi, alternativ rssi.
        wifi_rssi = to_int_or_none(payload.get("wifi_rssi"))

        if wifi_rssi is None:
            wifi_rssi = to_int_or_none(payload.get("rssi"))

        ssid = payload.get("ssid")
        bssid = payload.get("bssid")
        confidence = to_float_or_none(payload.get("confidence"))
        receivers = payload.get("receivers")

        if not target:
            raise ValueError("target is missing")

        if x is None:
            raise ValueError("x is missing or invalid")

        if y is None:
            raise ValueError("y is missing or invalid")

        if x < 0:
            raise ValueError("x must not be negative")

        if y < 0:
            raise ValueError("y must not be negative")

        if wifi_rssi is None:
            raise ValueError("wifi_rssi or rssi is missing or invalid")

        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO heatmap_samples
                (target, x, y, wifi_rssi, ssid, bssid, confidence, receivers, raw_payload)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    target,
                    x,
                    y,
                    wifi_rssi,
                    ssid,
                    bssid,
                    confidence,
                    Json(receivers) if receivers is not None else None,
                    Json(payload),
                ),
            )

        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        db_pool.putconn(conn)


def on_connect(client, userdata, flags, reason_code, properties):
    print(f"Connected to MQTT broker with reason code: {reason_code}")
    client.subscribe(MQTT_TOPIC, qos=1)
    print(f"Subscribed to topic: {MQTT_TOPIC}")


def on_message(client, userdata, msg):
    payload_raw = msg.payload.decode("utf-8", errors="replace")

    try:
        payload = json.loads(payload_raw)
    except json.JSONDecodeError:
        payload = {
            "raw": payload_raw,
            "error": "Invalid JSON",
        }

    entry = {
        "topic": msg.topic,
        "qos": msg.qos,
        "received_at": datetime.now(timezone.utc).isoformat(),
        "payload": payload,
    }

    with messages_lock:
        messages.appendleft(entry)

    save_measurement(msg.topic, payload)

    print(f"MQTT message received and saved: {entry}")


def connect_mqtt():
    global mqtt_client

    mqtt_client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id="iot-backend-subscriber",
        clean_session=False,
    )

    mqtt_client.on_connect = on_connect
    mqtt_client.on_message = on_message

    while True:
        try:
            mqtt_client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
            mqtt_client.loop_start()
            print("MQTT client started")
            return
        except Exception as e:
            print(f"MQTT broker not ready yet: {e}")
            time.sleep(2)


@asynccontextmanager
async def lifespan(app: FastAPI):
    wait_for_database()
    init_database()
    connect_mqtt()

    yield

    if mqtt_client:
        mqtt_client.loop_stop()
        mqtt_client.disconnect()

    if db_pool:
        db_pool.closeall()


app = FastAPI(lifespan=lifespan)


@app.get("/")
def hello_world():
    return {
        "message": "IoT WiFi Heatmap Backend",
        "dashboard": "/dashboard",
        "heatmap": "/heatmap",
        "room": "/room",
        "heatmap_samples": "/heatmap-samples",
    }


@app.get("/health")
def health():
    return {
        "status": "ok",
        "mqtt_host": MQTT_HOST,
        "mqtt_port": MQTT_PORT,
        "mqtt_topic": MQTT_TOPIC,
        "database": DB_NAME,
        "websocket": "/ws/heatmap-samples",
    }


@app.get("/messages")
def get_messages():
    with messages_lock:
        return {
            "count": len(messages),
            "messages": list(messages),
        }


@app.get("/measurements")
def get_measurements(limit: int = 50):
    conn = db_pool.getconn()

    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    id,
                    topic,
                    device_id,
                    ssid,
                    bssid,
                    rssi,
                    x,
                    y,
                    raw_payload,
                    validation_error,
                    received_at
                FROM measurements
                ORDER BY received_at DESC
                LIMIT %s
                """,
                (limit,),
            )

            rows = cur.fetchall()

        return {
            "count": len(rows),
            "measurements": rows,
        }

    finally:
        db_pool.putconn(conn)


@app.get("/measurements/latest")
def get_latest_measurements():
    conn = db_pool.getconn()

    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT DISTINCT ON (device_id)
                    id,
                    topic,
                    device_id,
                    ssid,
                    bssid,
                    rssi,
                    x,
                    y,
                    raw_payload,
                    validation_error,
                    received_at
                FROM measurements
                WHERE device_id IS NOT NULL
                AND rssi IS NOT NULL
                ORDER BY device_id, received_at DESC
                """
            )

            rows = cur.fetchall()

        return {
            "count": len(rows),
            "measurements": rows,
        }

    finally:
        db_pool.putconn(conn)


@app.get("/devices")
def get_devices():
    conn = db_pool.getconn()

    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT device_id, name, x, y, room, enabled
                FROM devices
                ORDER BY device_id
                """
            )

            rows = cur.fetchall()

        return {
            "count": len(rows),
            "devices": rows,
        }

    finally:
        db_pool.putconn(conn)


@app.get("/router")
def get_router():
    conn = db_pool.getconn()

    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT object_id, object_type, name, x, y, enabled, updated_at
                FROM room_objects
                WHERE object_id = 'router'
                """
            )

            row = cur.fetchone()

        return {
            "router": row
        }

    finally:
        db_pool.putconn(conn)


@app.get("/heatmap-samples")
def get_heatmap_samples(limit: int = 500):
    conn = db_pool.getconn()

    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    id,
                    target,
                    x,
                    y,
                    wifi_rssi,
                    ssid,
                    bssid,
                    confidence,
                    receivers,
                    raw_payload,
                    received_at
                FROM heatmap_samples
                ORDER BY received_at DESC
                LIMIT %s
                """,
                (limit,),
            )

            rows = cur.fetchall()

        return {
            "count": len(rows),
            "samples": rows,
        }

    finally:
        db_pool.putconn(conn)


@app.get("/test-sample")
def create_test_sample(token: str = ""):
    if token != WS_TOKEN:
        return {
            "status": "error",
            "message": "invalid token",
        }

    sample = {
        "target": "ePaperBLE_Sender",
        "x": 2.7,
        "y": 1.4,
        "wifi_rssi": -63,
        "ssid": "Test-WLAN",
        "bssid": "AA:BB:CC:DD:EE:FF",
    }

    save_heatmap_sample(sample)

    return {
        "status": "ok",
        "stored": True,
        "sample": sample,
    }


@app.post("/admin/reset-samples")
def reset_samples(token: str = ""):
    if token != WS_TOKEN:
        return {
            "status": "error",
            "message": "invalid token",
        }

    conn = db_pool.getconn()

    try:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE TABLE heatmap_samples RESTART IDENTITY;")

        conn.commit()

        return {
            "status": "ok",
            "message": "Heatmap-Samples wurden gelöscht.",
        }

    except Exception as e:
        conn.rollback()
        return {
            "status": "error",
            "message": str(e),
        }

    finally:
        db_pool.putconn(conn)


@app.post("/admin/add-sample")
def add_sample(
    token: str = "",
    x: float = 2.7,
    y: float = 1.4,
    wifi_rssi: int = -63,
):
    if token != WS_TOKEN:
        return {
            "status": "error",
            "message": "invalid token",
        }

    if x < 0:
        return {
            "status": "error",
            "message": "x darf nicht negativ sein.",
        }

    if y < 0:
        return {
            "status": "error",
            "message": "y darf nicht negativ sein.",
        }

    sample = {
        "target": "ePaperBLE_Sender",
        "x": x,
        "y": y,
        "wifi_rssi": wifi_rssi,
        "ssid": "Demo-WLAN",
        "bssid": "AA:BB:CC:DD:EE:FF",
    }

    try:
        save_heatmap_sample(sample)

        return {
            "status": "ok",
            "stored": True,
            "message": "Test-Sample wurde gespeichert.",
            "sample": sample,
        }

    except Exception as e:
        return {
            "status": "error",
            "stored": False,
            "message": str(e),
        }


@app.post("/admin/demo-samples")
def add_demo_samples(token: str = ""):
    if token != WS_TOKEN:
        return {
            "status": "error",
            "message": "invalid token",
        }

    samples = [
        {
            "target": "ePaperBLE_Sender",
            "x": 0.5,
            "y": 0.5,
            "wifi_rssi": -50,
            "ssid": "Demo-WLAN",
            "bssid": "AA:BB:CC:DD:EE:FF",
        },
        {
            "target": "ePaperBLE_Sender",
            "x": 2.5,
            "y": 1.8,
            "wifi_rssi": -63,
            "ssid": "Demo-WLAN",
            "bssid": "AA:BB:CC:DD:EE:FF",
        },
        {
            "target": "ePaperBLE_Sender",
            "x": 4.4,
            "y": 0.6,
            "wifi_rssi": -67,
            "ssid": "Demo-WLAN",
            "bssid": "AA:BB:CC:DD:EE:FF",
        },
        {
            "target": "ePaperBLE_Sender",
            "x": 1.0,
            "y": 3.3,
            "wifi_rssi": -74,
            "ssid": "Demo-WLAN",
            "bssid": "AA:BB:CC:DD:EE:FF",
        },
        {
            "target": "ePaperBLE_Sender",
            "x": 4.3,
            "y": 3.4,
            "wifi_rssi": -84,
            "ssid": "Demo-WLAN",
            "bssid": "AA:BB:CC:DD:EE:FF",
        },
    ]

    try:
        for sample in samples:
            save_heatmap_sample(sample)

        return {
            "status": "ok",
            "stored": True,
            "count": len(samples),
            "message": f"{len(samples)} Demo-Samples wurden gespeichert.",
        }

    except Exception as e:
        return {
            "status": "error",
            "stored": False,
            "message": str(e),
        }


@app.post("/admin/set-router")
def set_router(
    token: str = "",
    x: float = 0.0,
    y: float = 0.0,
    name: str = "WLAN-Router",
):
    if token != WS_TOKEN:
        return {
            "status": "error",
            "message": "invalid token",
        }

    if x < 0:
        return {
            "status": "error",
            "message": "Router-x darf nicht negativ sein.",
        }

    if y < 0:
        return {
            "status": "error",
            "message": "Router-y darf nicht negativ sein.",
        }

    conn = db_pool.getconn()

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO room_objects
                (object_id, object_type, name, x, y, enabled, updated_at)
                VALUES ('router', 'router', %s, %s, %s, TRUE, NOW())
                ON CONFLICT (object_id) DO UPDATE SET
                    object_type = EXCLUDED.object_type,
                    name = EXCLUDED.name,
                    x = EXCLUDED.x,
                    y = EXCLUDED.y,
                    enabled = TRUE,
                    updated_at = NOW();
                """,
                (name, x, y),
            )

        conn.commit()

        return {
            "status": "ok",
            "message": "Router wurde gesetzt.",
            "router": {
                "name": name,
                "x": x,
                "y": y,
            },
        }

    except Exception as e:
        conn.rollback()
        return {
            "status": "error",
            "message": str(e),
        }

    finally:
        db_pool.putconn(conn)


@app.post("/admin/clear-router")
def clear_router(token: str = ""):
    if token != WS_TOKEN:
        return {
            "status": "error",
            "message": "invalid token",
        }

    conn = db_pool.getconn()

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE room_objects
                SET enabled = FALSE, updated_at = NOW()
                WHERE object_id = 'router';
                """
            )

        conn.commit()

        return {
            "status": "ok",
            "message": "Router wurde ausgeblendet.",
        }

    except Exception as e:
        conn.rollback()
        return {
            "status": "error",
            "message": str(e),
        }

    finally:
        db_pool.putconn(conn)


@app.post("/admin/set-device-position")
def set_device_position(
    token: str = "",
    device_id: str = "",
    x: float = 0.0,
    y: float = 0.0,
):
    if token != WS_TOKEN:
        return {
            "status": "error",
            "message": "invalid token",
        }

    device_id = device_id.strip().lower()

    if device_id not in VALID_DEVICE_IDS:
        return {
            "status": "error",
            "message": "Ungültige device_id. Erlaubt sind esp01, esp02, esp03, esp04.",
        }

    if x < 0:
        return {
            "status": "error",
            "message": "ESP-x darf nicht negativ sein.",
        }

    if y < 0:
        return {
            "status": "error",
            "message": "ESP-y darf nicht negativ sein.",
        }

    conn = db_pool.getconn()

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE devices
                SET x = %s, y = %s
                WHERE device_id = %s
                """,
                (x, y, device_id),
            )

            if cur.rowcount == 0:
                return {
                    "status": "error",
                    "message": f"{device_id} wurde nicht gefunden.",
                }

        conn.commit()

        return {
            "status": "ok",
            "message": f"{device_id} wurde auf x={x:.1f} m, y={y:.1f} m gesetzt.",
        }

    except Exception as e:
        conn.rollback()
        return {
            "status": "error",
            "message": str(e),
        }

    finally:
        db_pool.putconn(conn)


@app.post("/admin/reset-device-positions")
def reset_device_positions(token: str = ""):
    if token != WS_TOKEN:
        return {
            "status": "error",
            "message": "invalid token",
        }

    conn = db_pool.getconn()

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE devices
                SET x = CASE device_id
                    WHEN 'esp01' THEN 0
                    WHEN 'esp02' THEN 0
                    WHEN 'esp03' THEN 5
                    WHEN 'esp04' THEN 5
                    ELSE x
                END,
                y = CASE device_id
                    WHEN 'esp01' THEN 0
                    WHEN 'esp02' THEN 4
                    WHEN 'esp03' THEN 4
                    WHEN 'esp04' THEN 0
                    ELSE y
                END
                WHERE device_id IN ('esp01', 'esp02', 'esp03', 'esp04');
                """
            )

        conn.commit()

        return {
            "status": "ok",
            "message": "ESP-Standardpositionen 5,0 m × 4,0 m wurden wiederhergestellt.",
        }

    except Exception as e:
        conn.rollback()
        return {
            "status": "error",
            "message": str(e),
        }

    finally:
        db_pool.putconn(conn)


@app.websocket("/ws/heatmap-samples")
async def websocket_heatmap_samples(websocket: WebSocket):
    token = websocket.query_params.get("token", "")

    if token != WS_TOKEN:
        await websocket.close(code=1008)
        return

    await websocket.accept()

    try:
        while True:
            message = await websocket.receive_text()

            try:
                payload = json.loads(message)
                save_heatmap_sample(payload)

                await websocket.send_json({
                    "status": "ok",
                    "stored": True,
                })

            except Exception as e:
                await websocket.send_json({
                    "status": "error",
                    "stored": False,
                    "message": str(e),
                })

    except WebSocketDisconnect:
        print("WebSocket client disconnected")


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard():
    return """
<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="UTF-8">
    <title>IoT WiFi RSSI Dashboard</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">

    <style>
        body {
            font-family: Arial, sans-serif;
            background: #f4f6f8;
            margin: 0;
            padding: 20px;
            color: #222;
        }

        .box,
        .card {
            background: white;
            padding: 14px 16px;
            border-radius: 12px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
            margin-bottom: 20px;
        }

        .cards {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 15px;
            margin-bottom: 25px;
        }

        .device {
            font-weight: bold;
            font-size: 18px;
        }

        .rssi {
            font-size: 28px;
            font-weight: bold;
            margin: 10px 0;
        }

        .good {
            color: #1e8e3e;
        }

        .medium {
            color: #f9ab00;
        }

        .bad {
            color: #d93025;
        }

        table {
            width: 100%;
            border-collapse: collapse;
            background: white;
            border-radius: 12px;
            overflow: hidden;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
        }

        th,
        td {
            padding: 10px 12px;
            border-bottom: 1px solid #eee;
            text-align: left;
            font-size: 14px;
        }

        th {
            background: #202124;
            color: white;
        }

        .small {
            color: #666;
            font-size: 13px;
        }

        a {
            color: #1a73e8;
            text-decoration: none;
        }
    </style>
</head>

<body>
    <h1>IoT WiFi RSSI Dashboard</h1>

    <div class="box">
        <strong>Status:</strong> <span id="status">Lade Daten...</span><br>
        <span class="small">
            <a href="/heatmap">Heatmap</a> |
            <a href="/room">Raumansicht</a> |
            <a href="/heatmap-samples">Heatmap-Samples</a>
        </span>
    </div>

    <h2>Letzter Messwert pro ESP</h2>
    <div class="cards" id="latestCards"></div>

    <h2>Messwert-Historie</h2>
    <table>
        <thead>
            <tr>
                <th>ID</th>
                <th>Gerät</th>
                <th>SSID</th>
                <th>BSSID</th>
                <th>RSSI</th>
                <th>X</th>
                <th>Y</th>
                <th>Zeitpunkt</th>
            </tr>
        </thead>
        <tbody id="historyTable">
            <tr>
                <td colspan="8">Noch keine Daten geladen...</td>
            </tr>
        </tbody>
    </table>

    <script>
        function esc(value) {
            if (value === null || value === undefined) return "";

            return String(value)
                .replaceAll("&", "&amp;")
                .replaceAll("<", "&lt;")
                .replaceAll(">", "&gt;")
                .replaceAll('"', "&quot;")
                .replaceAll("'", "&#039;");
        }

        function formatDate(value) {
            if (!value) return "";
            return new Date(value).toLocaleString("de-AT");
        }

        function formatMeters(value) {
            if (value === null || value === undefined || value === "") return "";
            return Number(value).toFixed(1);
        }

        function rssiClass(rssi) {
            if (rssi === null || rssi === undefined) return "";
            if (rssi >= -60) return "good";
            if (rssi >= -70) return "medium";
            return "bad";
        }

        async function loadLatest() {
            const response = await fetch("/measurements/latest");
            const data = await response.json();
            const container = document.getElementById("latestCards");

            container.innerHTML = "";

            if (!data.measurements || data.measurements.length === 0) {
                container.innerHTML = "<div class='card'>Noch keine Messwerte vorhanden.</div>";
                return;
            }

            for (const item of data.measurements) {
                const card = document.createElement("div");
                card.className = "card";

                card.innerHTML = `
                    <div class="device">${esc(item.device_id)}</div>
                    <div class="small">${esc(item.ssid || "Unbekannte SSID")}</div>
                    <div class="rssi ${rssiClass(item.rssi)}">${esc(item.rssi)} dBm</div>
                    <div class="small">BSSID: ${esc(item.bssid)}</div>
                    <div class="small">Position: x=${esc(formatMeters(item.x))} m, y=${esc(formatMeters(item.y))} m</div>
                    <div class="small">Zeit: ${esc(formatDate(item.received_at))}</div>
                `;

                container.appendChild(card);
            }
        }

        async function loadHistory() {
            const response = await fetch("/measurements?limit=50");
            const data = await response.json();
            const table = document.getElementById("historyTable");

            table.innerHTML = "";

            if (!data.measurements || data.measurements.length === 0) {
                table.innerHTML = "<tr><td colspan='8'>Noch keine Messwerte vorhanden.</td></tr>";
                return;
            }

            for (const item of data.measurements) {
                const row = document.createElement("tr");

                row.innerHTML = `
                    <td>${esc(item.id)}</td>
                    <td>${esc(item.device_id)}</td>
                    <td>${esc(item.ssid)}</td>
                    <td>${esc(item.bssid)}</td>
                    <td class="${rssiClass(item.rssi)}"><strong>${esc(item.rssi)} dBm</strong></td>
                    <td>${esc(formatMeters(item.x))} m</td>
                    <td>${esc(formatMeters(item.y))} m</td>
                    <td>${esc(formatDate(item.received_at))}</td>
                `;

                table.appendChild(row);
            }
        }

        async function refreshDashboard() {
            try {
                await loadLatest();
                await loadHistory();

                document.getElementById("status").textContent =
                    "Verbunden, letzte Aktualisierung: " + new Date().toLocaleTimeString("de-AT");
            } catch (error) {
                document.getElementById("status").textContent = "Fehler: " + error;
            }
        }

        refreshDashboard();
        setInterval(refreshDashboard, 3000);
    </script>
</body>
</html>
    """


@app.get("/room", response_class=HTMLResponse)
def room_view():
    return """
<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="UTF-8">
    <title>IoT WiFi Raumansicht</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">

    <style>
        body {
            font-family: Arial, sans-serif;
            background: #f4f6f8;
            margin: 0;
            padding: 20px;
            color: #222;
        }

        .box,
        .room-wrapper {
            background: white;
            padding: 16px;
            border-radius: 14px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
            margin-bottom: 20px;
        }

        .room {
            position: relative;
            width: 100%;
            max-width: 820px;
            aspect-ratio: 5 / 4;
            border: 3px solid #202124;
            border-radius: 10px;
            overflow: hidden;
            background:
                linear-gradient(to right, rgba(0,0,0,0.06) 1px, transparent 1px),
                linear-gradient(to bottom, rgba(0,0,0,0.06) 1px, transparent 1px);
            background-size: 20% 25%;
        }

        .device-point {
            position: absolute;
            width: 130px;
            min-height: 70px;
            border-radius: 12px;
            background: white;
            border: 3px solid #444;
            box-shadow: 0 3px 10px rgba(0,0,0,0.20);
            padding: 8px;
            text-align: center;
            font-size: 13px;
            box-sizing: border-box;
        }

        .device-id {
            font-weight: bold;
            font-size: 15px;
        }

        .rssi {
            font-size: 22px;
            font-weight: bold;
            margin: 4px 0;
        }

        .good {
            color: #1e8e3e;
            border-color: #1e8e3e;
        }

        .medium {
            color: #f9ab00;
            border-color: #f9ab00;
        }

        .bad {
            color: #d93025;
            border-color: #d93025;
        }

        .unknown {
            color: #777;
            border-color: #999;
        }

        .small {
            color: #666;
            font-size: 12px;
        }

        a {
            color: #1a73e8;
            text-decoration: none;
        }
    </style>
</head>

<body>
    <h1>IoT WiFi Raumansicht</h1>

    <div class="box">
        <strong>Status:</strong> <span id="status">Lade Daten...</span><br>
        <span class="small">
            <a href="/dashboard">Dashboard</a> |
            <a href="/heatmap">Heatmap</a>
        </span>
    </div>

    <div class="room-wrapper">
        <div id="room" class="room"></div>
    </div>

    <script>
        const ROOM_WIDTH = 5.0;
        const ROOM_HEIGHT = 4.0;

        function esc(value) {
            if (value === null || value === undefined) return "";

            return String(value)
                .replaceAll("&", "&amp;")
                .replaceAll("<", "&lt;")
                .replaceAll(">", "&gt;")
                .replaceAll('"', "&quot;")
                .replaceAll("'", "&#039;");
        }

        function formatMeters(value) {
            if (value === null || value === undefined || value === "") return "";
            return Number(value).toFixed(1);
        }

        function rssiClass(rssi) {
            if (rssi === null || rssi === undefined || rssi === "") return "unknown";
            if (rssi >= -60) return "good";
            if (rssi >= -70) return "medium";
            return "bad";
        }

        function formatRssi(rssi) {
            if (rssi === null || rssi === undefined || rssi === "") return "keine Daten";
            return rssi + " dBm";
        }

        function setPosition(element, x, y) {
            const left = (x / ROOM_WIDTH) * 100;
            const top = 100 - ((y / ROOM_HEIGHT) * 100);

            element.style.left = left + "%";
            element.style.top = top + "%";

            let translateX = -50;
            let translateY = -50;

            if (x <= 0) translateX = 0;
            if (x >= ROOM_WIDTH) translateX = -100;
            if (y <= 0) translateY = -100;
            if (y >= ROOM_HEIGHT) translateY = 0;

            element.style.transform = `translate(${translateX}%, ${translateY}%)`;
        }

        async function loadRoom() {
            const devicesData = await (await fetch("/devices")).json();
            const latestData = await (await fetch("/measurements/latest")).json();

            const latestByDevice = {};

            for (const measurement of latestData.measurements || []) {
                latestByDevice[measurement.device_id] = measurement;
            }

            const room = document.getElementById("room");
            room.innerHTML = "";

            for (const device of devicesData.devices || []) {
                const measurement = latestByDevice[device.device_id];
                const rssi = measurement ? measurement.rssi : null;
                const ssid = measurement ? measurement.ssid : "";

                const point = document.createElement("div");
                point.className = "device-point " + rssiClass(rssi);
                setPosition(point, Number(device.x), Number(device.y));

                point.innerHTML = `
                    <div class="device-id">${esc(device.device_id)}</div>
                    <div class="rssi">${esc(formatRssi(rssi))}</div>
                    <div class="small">${esc(ssid || "Keine SSID")}</div>
                    <div class="small">x=${esc(formatMeters(device.x))} m, y=${esc(formatMeters(device.y))} m</div>
                `;

                room.appendChild(point);
            }

            document.getElementById("status").textContent =
                "Verbunden, letzte Aktualisierung: " + new Date().toLocaleTimeString("de-AT");
        }

        loadRoom();
        setInterval(loadRoom, 3000);
    </script>
</body>
</html>
    """


@app.get("/heatmap", response_class=HTMLResponse)
def heatmap_view():
    return """
<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="UTF-8">
    <title>IoT WiFi Heatmap</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">

    <style>
        body {
            font-family: Arial, sans-serif;
            background: #f4f6f8;
            margin: 0;
            padding: 20px;
            color: #222;
        }

        h1 {
            margin-bottom: 6px;
        }

        .subtitle {
            color: #666;
            margin-bottom: 20px;
        }

        .status,
        .room-wrapper,
        .admin-controls,
        .info-box {
            background: white;
            padding: 16px;
            border-radius: 14px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
            margin-bottom: 20px;
        }

        .room-wrapper {
            max-width: 900px;
        }

        .room {
            position: relative;
            width: 100%;
            max-width: 820px;
            border: 3px solid #202124;
            border-radius: 10px;
            overflow: hidden;
            background: #fff;
        }

        canvas {
            position: absolute;
            inset: 0;
            width: 100%;
            height: 100%;
        }

        .grid {
            position: absolute;
            inset: 0;
            background:
                linear-gradient(to right, rgba(0,0,0,0.08) 1px, transparent 1px),
                linear-gradient(to bottom, rgba(0,0,0,0.08) 1px, transparent 1px);
            background-size: 20% 25%;
            pointer-events: none;
        }

        .target-point {
            position: absolute;
            width: 150px;
            min-height: 76px;
            border-radius: 12px;
            background: rgba(255,255,255,0.94);
            border: 3px solid #1a73e8;
            box-shadow: 0 3px 10px rgba(0,0,0,0.25);
            padding: 8px;
            text-align: center;
            font-size: 13px;
            box-sizing: border-box;
            z-index: 5;
        }

        .target-id {
            font-weight: bold;
            font-size: 15px;
            color: #1a73e8;
        }

        .router-point {
            position: absolute;
            width: 140px;
            min-height: 68px;
            border-radius: 14px;
            background: rgba(255,255,255,0.96);
            border: 3px solid #8e24aa;
            box-shadow: 0 3px 10px rgba(0,0,0,0.25);
            padding: 8px;
            text-align: center;
            font-size: 13px;
            box-sizing: border-box;
            z-index: 6;
            color: #6a1b9a;
        }

        .router-icon {
            font-size: 24px;
            line-height: 24px;
            margin-bottom: 3px;
        }

        .trail-point {
            position: absolute;
            width: 12px;
            height: 12px;
            border-radius: 50%;
            background: black;
            border: 2px solid rgba(255,255,255,0.95);
            box-shadow: 0 1px 5px rgba(0,0,0,0.45);
            transform: translate(-50%, -50%);
            z-index: 7;
            pointer-events: none;
        }

        .rssi {
            font-size: 22px;
            font-weight: bold;
            margin: 4px 0;
        }

        .device-point {
            position: absolute;
            width: 94px;
            min-height: 48px;
            border-radius: 10px;
            background: rgba(255,255,255,0.88);
            border: 2px solid #444;
            padding: 5px;
            text-align: center;
            font-size: 12px;
            box-sizing: border-box;
            z-index: 4;
        }

        .small {
            color: #666;
            font-size: 12px;
        }

        .legend {
            margin-top: 15px;
            display: flex;
            gap: 15px;
            flex-wrap: wrap;
            font-size: 14px;
        }

        .legend-item {
            background: white;
            border-radius: 8px;
            padding: 8px 10px;
            border: 1px solid #ddd;
        }

        .legend-green { border-left: 8px solid #00c853; }
        .legend-yellow { border-left: 8px solid #ffd600; }
        .legend-orange { border-left: 8px solid #ff9800; }
        .legend-red { border-left: 8px solid #d50000; }
        .legend-purple { border-left: 8px solid #8e24aa; }
        .legend-black { border-left: 8px solid #111; }

        .admin-controls input,
        .admin-controls select {
            padding: 9px 10px;
            border-radius: 8px;
            border: 1px solid #ccc;
            min-width: 190px;
            margin-top: 8px;
            margin-right: 8px;
            background: white;
        }

        .admin-controls input[type="number"] {
            min-width: 90px;
            width: 90px;
        }

        .admin-controls select {
            min-width: 230px;
        }

        .admin-controls button {
            padding: 9px 12px;
            border-radius: 8px;
            border: 1px solid #ccc;
            background: #f8f9fa;
            cursor: pointer;
            margin-top: 8px;
            margin-right: 6px;
        }

        .admin-controls button:hover {
            background: #e8eaed;
        }

        .admin-controls .danger {
            background: #fce8e6;
            border-color: #d93025;
            color: #a50e0e;
        }

        .admin-controls .danger:hover {
            background: #fad2cf;
        }

        .device-position-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
            gap: 10px;
            margin-top: 8px;
        }

        .device-position-row {
            background: #f8f9fa;
            border: 1px solid #ddd;
            border-radius: 10px;
            padding: 8px;
        }

        .device-position-row strong {
            display: inline-block;
            min-width: 52px;
        }

        .payload-example {
            background: #202124;
            color: #e8eaed;
            padding: 14px;
            border-radius: 10px;
            overflow-x: auto;
            font-size: 13px;
            line-height: 1.45;
        }

        code {
            background: #f1f3f4;
            padding: 2px 5px;
            border-radius: 5px;
        }

        a {
            color: #1a73e8;
            text-decoration: none;
        }
    </style>
</head>

<body>
    <h1>IoT WiFi Heatmap</h1>
    <div class="subtitle">Heatmap aus x/y-Position des ePapers und dort gemessenem WLAN-RSSI</div>

    <div class="status">
        <strong>Status:</strong> <span id="status">Lade Daten...</span><br>
        <span class="small">
            <a href="/dashboard">Dashboard</a> |
            <a href="/room">Raumansicht</a> |
            <a href="/heatmap-samples">Heatmap-Samples</a>
        </span>
    </div>

    <div class="room-wrapper">
        <div id="room" class="room">
            <canvas id="heatmapCanvas"></canvas>
            <div class="grid"></div>
        </div>

        <div class="legend">
            <div class="legend-item legend-green">Grün: stark/gut, ≥ -60 dBm</div>
            <div class="legend-item legend-yellow">Gelb: brauchbar, -61 bis -70 dBm</div>
            <div class="legend-item legend-orange">Orange: schwächer, -71 bis -79 dBm</div>
            <div class="legend-item legend-red">Rot: schwach, ≤ -80 dBm</div>
            <div class="legend-item legend-purple">Lila: Router / Access Point</div>
            <div class="legend-item legend-black">Schwarze Punkte: letzte 5 ePaper-Positionen</div>
        </div>
    </div>

    <div class="admin-controls">
        <strong>Demo-Steuerung:</strong><br>

        <input id="adminToken" type="password" placeholder="Admin-/WebSocket-Token">
        <button onclick="saveAdminToken()">Token speichern</button>

        <br><br>

        <span class="small">Raumgröße / Heat-Feld:</span><br>
        <input id="roomWidthInput" type="number" min="0.1" step="0.1" value="5.0" placeholder="Breite in m">
        <input id="roomHeightInput" type="number" min="0.1" step="0.1" value="4.0" placeholder="Höhe in m">
        <button onclick="saveRoomSize()">Raumgröße übernehmen</button>
        <button onclick="resetRoomSize()">Standardgröße</button>

        <br><br>

        <span class="small">ePaper-Sample:</span><br>
        <input id="sampleX" type="number" min="0" step="0.1" value="2.7" placeholder="x in m">
        <input id="sampleY" type="number" min="0" step="0.1" value="1.4" placeholder="y in m">
        <input id="sampleRssi" type="number" step="1" value="-63" placeholder="RSSI">
        <button onclick="addCustomSample()">Sample hinzufügen</button>
        <button onclick="addDemoSamples()">Demo-Samples erzeugen</button>
        <button class="danger" onclick="resetSamples()">Heatmap zurücksetzen</button>

        <br><br>

        <span class="small">Router-Position:</span><br>
        <input id="routerName" type="text" value="WLAN-Router" placeholder="Router-Name">
        <input id="routerX" type="number" min="0" step="0.1" value="0.0" placeholder="x in m">
        <input id="routerY" type="number" min="0" step="0.1" value="0.0" placeholder="y in m">
        <button onclick="setRouter()">Router einzeichnen</button>
        <button onclick="clearRouter()">Router ausblenden</button>

        <br><br>

        <span class="small">ESP-Positionen:</span><br>
        <div class="device-position-grid">
            <div class="device-position-row">
                <strong>esp01</strong>
                <input id="esp01X" type="number" min="0" step="0.1" placeholder="x in m">
                <input id="esp01Y" type="number" min="0" step="0.1" placeholder="y in m">
                <button onclick="setDevicePosition('esp01')">Speichern</button>
            </div>

            <div class="device-position-row">
                <strong>esp02</strong>
                <input id="esp02X" type="number" min="0" step="0.1" placeholder="x in m">
                <input id="esp02Y" type="number" min="0" step="0.1" placeholder="y in m">
                <button onclick="setDevicePosition('esp02')">Speichern</button>
            </div>

            <div class="device-position-row">
                <strong>esp03</strong>
                <input id="esp03X" type="number" min="0" step="0.1" placeholder="x in m">
                <input id="esp03Y" type="number" min="0" step="0.1" placeholder="y in m">
                <button onclick="setDevicePosition('esp03')">Speichern</button>
            </div>

            <div class="device-position-row">
                <strong>esp04</strong>
                <input id="esp04X" type="number" min="0" step="0.1" placeholder="x in m">
                <input id="esp04Y" type="number" min="0" step="0.1" placeholder="y in m">
                <button onclick="setDevicePosition('esp04')">Speichern</button>
            </div>
        </div>

        <button onclick="alignDevicesToRoom()">ESPs an aktuelle Raumgröße anpassen</button>
        <button onclick="resetDevicePositions()">ESP-Standardpositionen 5×4 wiederherstellen</button>

        <br><br>

        <span class="small">Heatmap-Darstellung:</span><br>
        <select id="heatmapMode" onchange="saveHeatmapMode(); refresh();">
            <option value="smooth">Glatt / Verlauf</option>
            <option value="classified">Klassen / Schwellenwerte</option>
        </select>

        <br><br>

        <div id="adminStatus" class="small"></div>
    </div>

    <div class="info-box">
        <strong>Sample-Payload für den PythonCalcServer:</strong>
        <p class="small">
            WebSocket-Ziel:
            <code>wss://iot.politzer.mywire.org/ws/heatmap-samples?token=DEIN_TOKEN</code>
        </p>

        <pre class="payload-example">{
  "target": "ePaperBLE_Sender",
  "x": 2.7,
  "y": 1.4,
  "wifi_rssi": -63,
  "ssid": "Test-WLAN",
  "bssid": "AA:BB:CC:DD:EE:FF"
}</pre>

        <p class="small">
            Minimal reichen <code>target</code>, <code>x</code>, <code>y</code> und <code>wifi_rssi</code>.
            Alternativ wird auch <code>rssi</code> statt <code>wifi_rssi</code> akzeptiert.
            <code>ssid</code> und <code>bssid</code> sind optional.
        </p>
    </div>

    <script>
        const FALLBACK_ROOM_WIDTH = 5.0;
        const FALLBACK_ROOM_HEIGHT = 4.0;

        let baseRoomWidth = FALLBACK_ROOM_WIDTH;
        let baseRoomHeight = FALLBACK_ROOM_HEIGHT;

        let mapWidth = FALLBACK_ROOM_WIDTH;
        let mapHeight = FALLBACK_ROOM_HEIGHT;

        function esc(value) {
            if (value === null || value === undefined) return "";

            return String(value)
                .replaceAll("&", "&amp;")
                .replaceAll("<", "&lt;")
                .replaceAll(">", "&gt;")
                .replaceAll('"', "&quot;")
                .replaceAll("'", "&#039;");
        }

        function formatMeters(value) {
            if (value === null || value === undefined || value === "") return "";
            return Number(value).toFixed(1);
        }

        function roundUpHalf(value) {
            return Math.ceil(value * 2) / 2;
        }

        function applyRoomGeometry() {
            const room = document.getElementById("room");

            if (!room) {
                return;
            }

            room.style.aspectRatio = `${mapWidth} / ${mapHeight}`;

            // Ein Rasterfeld entspricht 1 Meter.
            // Bei 5 m × 4 m ergibt das 20% × 25%.
            const grid = room.querySelector(".grid");

            if (grid) {
                grid.style.backgroundSize = `${100 / mapWidth}% ${100 / mapHeight}%`;
            }
        }

        function updateCoordinateInputLimits() {
            const xInputs = [
                "sampleX",
                "routerX",
                "esp01X",
                "esp02X",
                "esp03X",
                "esp04X",
            ];

            const yInputs = [
                "sampleY",
                "routerY",
                "esp01Y",
                "esp02Y",
                "esp03Y",
                "esp04Y",
            ];

            for (const id of xInputs) {
                const input = document.getElementById(id);

                if (input) {
                    input.max = baseRoomWidth.toFixed(1);
                }
            }

            for (const id of yInputs) {
                const input = document.getElementById(id);

                if (input) {
                    input.max = baseRoomHeight.toFixed(1);
                }
            }
        }

        function validateInsideRoom(x, y, label) {
            if (x > baseRoomWidth || y > baseRoomHeight) {
                document.getElementById("adminStatus").textContent =
                    label +
                    " liegt außerhalb der aktuellen Raumgröße (" +
                    formatMeters(baseRoomWidth) +
                    " m × " +
                    formatMeters(baseRoomHeight) +
                    " m). Bitte zuerst die Raumgröße erhöhen oder die Koordinaten anpassen.";

                return false;
            }

            return true;
        }

        function isPointInsideMap(point) {
            const x = Number(point.x);
            const y = Number(point.y);

            return (
                Number.isFinite(x) &&
                Number.isFinite(y) &&
                x >= 0 &&
                y >= 0 &&
                x <= mapWidth &&
                y <= mapHeight
            );
        }

        function clamp(value, min, max) {
            return Math.max(min, Math.min(max, value));
        }

        function loadStoredRoomSize() {
            const storedWidth = Number(localStorage.getItem("iotRoomWidth") || FALLBACK_ROOM_WIDTH);
            const storedHeight = Number(localStorage.getItem("iotRoomHeight") || FALLBACK_ROOM_HEIGHT);

            baseRoomWidth = Number.isFinite(storedWidth) && storedWidth > 0 ? storedWidth : FALLBACK_ROOM_WIDTH;
            baseRoomHeight = Number.isFinite(storedHeight) && storedHeight > 0 ? storedHeight : FALLBACK_ROOM_HEIGHT;

            mapWidth = baseRoomWidth;
            mapHeight = baseRoomHeight;

            document.getElementById("roomWidthInput").value = baseRoomWidth.toFixed(1);
            document.getElementById("roomHeightInput").value = baseRoomHeight.toFixed(1);

            updateCoordinateInputLimits();
            applyRoomGeometry();
        }

        function saveRoomSize() {
            const width = Number(document.getElementById("roomWidthInput").value);
            const height = Number(document.getElementById("roomHeightInput").value);

            if (!Number.isFinite(width) || width <= 0 || !Number.isFinite(height) || height <= 0) {
                document.getElementById("adminStatus").textContent =
                    "Ungültige Raumgröße. Breite und Höhe müssen größer als 0 sein.";
                return;
            }

            baseRoomWidth = Number(width.toFixed(1));
            baseRoomHeight = Number(height.toFixed(1));

            localStorage.setItem("iotRoomWidth", baseRoomWidth);
            localStorage.setItem("iotRoomHeight", baseRoomHeight);

            mapWidth = baseRoomWidth;
            mapHeight = baseRoomHeight;

            document.getElementById("roomWidthInput").value = baseRoomWidth.toFixed(1);
            document.getElementById("roomHeightInput").value = baseRoomHeight.toFixed(1);

            updateCoordinateInputLimits();
            applyRoomGeometry();

            document.getElementById("adminStatus").textContent =
                "Raumgröße wurde übernommen. Die Heatmap verwendet jetzt exakt " +
                formatMeters(baseRoomWidth) +
                " m × " +
                formatMeters(baseRoomHeight) +
                " m.";

            refresh();
        }

        function resetRoomSize() {
            baseRoomWidth = FALLBACK_ROOM_WIDTH;
            baseRoomHeight = FALLBACK_ROOM_HEIGHT;

            localStorage.setItem("iotRoomWidth", baseRoomWidth);
            localStorage.setItem("iotRoomHeight", baseRoomHeight);

            mapWidth = baseRoomWidth;
            mapHeight = baseRoomHeight;

            document.getElementById("roomWidthInput").value = baseRoomWidth.toFixed(1);
            document.getElementById("roomHeightInput").value = baseRoomHeight.toFixed(1);

            updateCoordinateInputLimits();
            applyRoomGeometry();

            document.getElementById("adminStatus").textContent =
                "Standardgröße 5,0 m × 4,0 m wurde wiederhergestellt.";

            refresh();
        }

        function computeMapSize(samples, router) {
            // Die sichtbare Heatmap darf NICHT automatisch durch Samples,
            // Router oder ESP-Positionen wachsen.
            //
            // Vorher wurde durch maxX + 0.2 und roundUpHalf() aus 5.0 × 4.0
            // optisch 5.5 × 4.5. Dadurch passten die ESP-Koordinaten und das
            // Heat-Feld nicht mehr zusammen.
            //
            // Ab jetzt ist die Eingabe "Raumgröße / Heat-Feld" die einzige
            // Quelle für die sichtbare Koordinatenfläche.
            mapWidth = baseRoomWidth;
            mapHeight = baseRoomHeight;

            applyRoomGeometry();
        }

        function getHeatmapMode() {
            const select = document.getElementById("heatmapMode");

            if (select && select.value) {
                return select.value;
            }

            return localStorage.getItem("iotHeatmapMode") || "smooth";
        }

        function saveHeatmapMode() {
            const select = document.getElementById("heatmapMode");

            if (!select) {
                return;
            }

            localStorage.setItem("iotHeatmapMode", select.value);
        }

        function loadStoredHeatmapMode() {
            const select = document.getElementById("heatmapMode");

            if (!select) {
                return;
            }

            select.value = localStorage.getItem("iotHeatmapMode") || "smooth";
        }

        function rssiCategory(rssi) {
            if (rssi >= -60) return "strong";
            if (rssi >= -70) return "good";
            if (rssi >= -79) return "fair";
            return "weak";
        }

        function rssiToRgbClassified(rssi) {
            const category = rssiCategory(rssi);

            if (category === "strong") {
                return { red: 0, green: 200, blue: 83 };
            }

            if (category === "good") {
                return { red: 255, green: 214, blue: 0 };
            }

            if (category === "fair") {
                return { red: 255, green: 152, blue: 0 };
            }

            return { red: 213, green: 0, blue: 0 };
        }

        function rssiToRgbSmooth(rssi) {
            const min = -90;
            const max = -40;

            let value = (rssi - min) / (max - min);
            value = Math.max(0, Math.min(1, value));

            let red;
            let green;

            if (value < 0.5) {
                red = 255;
                green = Math.round(510 * value);
            } else {
                red = Math.round(510 * (1 - value));
                green = 255;
            }

            return { red, green, blue: 0 };
        }

        function rssiToRgb(rssi) {
            if (getHeatmapMode() === "classified") {
                return rssiToRgbClassified(rssi);
            }

            return rssiToRgbSmooth(rssi);
        }

        function rssiToColor(rssi, alpha = 0.75) {
            const color = rssiToRgb(rssi);
            return `rgba(${color.red}, ${color.green}, ${color.blue}, ${alpha})`;
        }

        function getHeatmapCellSize() {
            if (getHeatmapMode() === "classified") {
                return 8;
            }

            return 4;
        }

        function estimateRssi(x, y, points) {
            let numerator = 0;
            let denominator = 0;

            for (const point of points) {
                const dx = x - point.x;
                const dy = y - point.y;
                const distance = Math.sqrt(dx * dx + dy * dy);

                if (distance < 0.001) {
                    return point.wifi_rssi;
                }

                const weight = 1 / Math.pow(distance, 2);
                numerator += point.wifi_rssi * weight;
                denominator += weight;
            }

            return numerator / denominator;
        }

        function drawHeatmap(points) {
            const canvas = document.getElementById("heatmapCanvas");
            const room = document.getElementById("room");

            canvas.width = room.clientWidth;
            canvas.height = room.clientHeight;

            const ctx = canvas.getContext("2d");
            ctx.clearRect(0, 0, canvas.width, canvas.height);

            if (points.length === 0) {
                return;
            }

            if (points.length === 1) {
                const point = points[0];

                const px = (point.x / mapWidth) * canvas.width;
                const py = canvas.height - ((point.y / mapHeight) * canvas.height);

                const radius = Math.min(canvas.width, canvas.height) * 0.28;
                const color = rssiToRgb(point.wifi_rssi);

                const gradient = ctx.createRadialGradient(px, py, 0, px, py, radius);
                gradient.addColorStop(0, `rgba(${color.red}, ${color.green}, ${color.blue}, 0.85)`);
                gradient.addColorStop(0.6, `rgba(${color.red}, ${color.green}, ${color.blue}, 0.35)`);
                gradient.addColorStop(1, `rgba(${color.red}, ${color.green}, ${color.blue}, 0)`);

                ctx.fillStyle = gradient;
                ctx.fillRect(0, 0, canvas.width, canvas.height);
                return;
            }

            const cellSize = getHeatmapCellSize();

            for (let py = 0; py < canvas.height; py += cellSize) {
                for (let px = 0; px < canvas.width; px += cellSize) {
                    const roomX = (px / canvas.width) * mapWidth;
                    const roomY = mapHeight - ((py / canvas.height) * mapHeight);

                    const estimatedRssi = estimateRssi(roomX, roomY, points);

                    ctx.fillStyle = rssiToColor(estimatedRssi, 0.82);
                    ctx.fillRect(px, py, cellSize + 1, cellSize + 1);
                }
            }
        }

        function setPosition(element, x, y) {
            const originalX = Number(x);
            const originalY = Number(y);

            // Bestehende gespeicherte Punkte, die außerhalb der aktuellen Raumgröße
            // liegen, werden am Rand angezeigt statt die Heatmap zu vergrößern.
            const visibleX = clamp(originalX, 0, mapWidth);
            const visibleY = clamp(originalY, 0, mapHeight);

            const left = (visibleX / mapWidth) * 100;
            const top = 100 - ((visibleY / mapHeight) * 100);

            element.style.left = left + "%";
            element.style.top = top + "%";

            let translateX = -50;
            let translateY = -50;

            if (visibleX <= 0) translateX = 0;
            if (visibleX >= mapWidth - 0.1) translateX = -100;
            if (visibleY <= 0) translateY = -100;
            if (visibleY >= mapHeight - 0.1) translateY = 0;

            element.style.transform = `translate(${translateX}%, ${translateY}%)`;
        }

        function setDotPosition(element, x, y) {
            const visibleX = clamp(Number(x), 0, mapWidth);
            const visibleY = clamp(Number(y), 0, mapHeight);

            const left = (visibleX / mapWidth) * 100;
            const top = 100 - ((visibleY / mapHeight) * 100);

            element.style.left = left + "%";
            element.style.top = top + "%";
        }

        function renderDevices(devices) {
            const room = document.getElementById("room");
            document.querySelectorAll(".device-point").forEach(el => el.remove());

            for (const device of devices) {
                const point = document.createElement("div");
                point.className = "device-point";
                setPosition(point, Number(device.x), Number(device.y));

                point.innerHTML = `
                    <strong>${esc(device.device_id)}</strong><br>
                    <span class="small">x=${esc(formatMeters(device.x))} m<br>y=${esc(formatMeters(device.y))} m</span>
                `;

                room.appendChild(point);
            }
        }

        function updateInputIfNotFocused(id, value) {
            const input = document.getElementById(id);

            if (!input) {
                return;
            }

            if (document.activeElement !== input) {
                input.value = Number(value).toFixed(1);
            }
        }

        function fillDevicePositionInputs(devices) {
            for (const device of devices || []) {
                updateInputIfNotFocused(device.device_id + "X", device.x);
                updateInputIfNotFocused(device.device_id + "Y", device.y);
            }
        }

        function renderRouter(router) {
            const room = document.getElementById("room");
            document.querySelectorAll(".router-point").forEach(el => el.remove());

            if (!router || !router.enabled) {
                return;
            }

            const point = document.createElement("div");
            point.className = "router-point";
            setPosition(point, Number(router.x), Number(router.y));

            point.innerHTML = `
                <div class="router-icon">📡</div>
                <strong>${esc(router.name || "WLAN-Router")}</strong><br>
                <span class="small">x=${esc(formatMeters(router.x))} m, y=${esc(formatMeters(router.y))} m</span>
            `;

            room.appendChild(point);
        }

        function renderTrail(points) {
            const room = document.getElementById("room");
            document.querySelectorAll(".trail-point").forEach(el => el.remove());

            const trail = points.slice(0, 5);

            for (let index = 0; index < trail.length; index++) {
                const sample = trail[index];
                const dot = document.createElement("div");

                dot.className = "trail-point";

                const opacity = 1.0 - (index * 0.17);
                const size = 12 - (index * 1.2);

                dot.style.opacity = Math.max(opacity, 0.25).toString();
                dot.style.width = size + "px";
                dot.style.height = size + "px";
                dot.title =
                    "Messpunkt " + (index + 1) +
                    "\\nx=" + formatMeters(sample.x) + " m" +
                    "\\ny=" + formatMeters(sample.y) + " m" +
                    "\\nRSSI=" + sample.wifi_rssi + " dBm";

                setDotPosition(dot, Number(sample.x), Number(sample.y));

                room.appendChild(dot);
            }
        }

        function renderLatestTarget(sample) {
            const room = document.getElementById("room");
            document.querySelectorAll(".target-point").forEach(el => el.remove());

            if (!sample) {
                return;
            }

            const point = document.createElement("div");
            point.className = "target-point";
            setPosition(point, Number(sample.x), Number(sample.y));

            point.innerHTML = `
                <div class="target-id">${esc(sample.target)}</div>
                <div class="rssi">${esc(sample.wifi_rssi)} dBm</div>
                <div class="small">${esc(sample.ssid || "Keine SSID")}</div>
                <div class="small">x=${esc(formatMeters(sample.x))} m, y=${esc(formatMeters(sample.y))} m</div>
            `;

            room.appendChild(point);
        }

        async function loadHeatmap() {
            const cacheBust = Date.now();

            const samplesData = await (
                await fetch("/heatmap-samples?limit=500&_=" + cacheBust, {
                    cache: "no-store"
                })
            ).json();

            const devicesData = await (
                await fetch("/devices?_=" + cacheBust, {
                    cache: "no-store"
                })
            ).json();

            const routerData = await (
                await fetch("/router?_=" + cacheBust, {
                    cache: "no-store"
                })
            ).json();

            const samples = samplesData.samples || [];
            const devices = devicesData.devices || [];
            const router = routerData.router;

            const allPoints = samples
                .filter(sample => sample.x !== null && sample.y !== null && sample.wifi_rssi !== null)
                .map(sample => ({
                    x: Number(sample.x),
                    y: Number(sample.y),
                    wifi_rssi: Number(sample.wifi_rssi),
                    target: sample.target,
                    ssid: sample.ssid,
                    received_at: sample.received_at,
                }))
                .filter(sample =>
                    Number.isFinite(sample.x) &&
                    Number.isFinite(sample.y) &&
                    Number.isFinite(sample.wifi_rssi)
                );

            computeMapSize(allPoints, router);

            // Nur Samples innerhalb der aktuellen Raumgröße werden zur Heatmap-
            // Berechnung verwendet. So verschieben alte oder falsche Koordinaten
            // nicht mehr das komplette Koordinatensystem.
            const points = allPoints.filter(isPointInsideMap);
            const ignoredPoints = allPoints.length - points.length;

            drawHeatmap(points);
            renderDevices(devices);
            fillDevicePositionInputs(devices);
            renderRouter(router);
            renderTrail(points);
            renderLatestTarget(points.length > 0 ? points[0] : null);

            let statusText =
                "Verbunden, Samples: " + points.length +
                ", Raum/Heat-Feld: " + formatMeters(mapWidth) + " m × " + formatMeters(mapHeight) + " m" +
                ", Modus: " + (getHeatmapMode() === "classified" ? "Klassen" : "Glatt") +
                ", letzte Aktualisierung: " + new Date().toLocaleTimeString("de-AT");

            if (ignoredPoints > 0) {
                statusText += ", ignoriert außerhalb des Raums: " + ignoredPoints;
            }

            document.getElementById("status").textContent = statusText;
        }

        async function refresh() {
            try {
                await loadHeatmap();
            } catch (error) {
                document.getElementById("status").textContent =
                    "Fehler beim Laden der Heatmap: " + error;
            }
        }

        function getAdminToken() {
            const input = document.getElementById("adminToken");
            const inputValue = input ? input.value.trim() : "";

            if (inputValue) {
                return inputValue;
            }

            return localStorage.getItem("iotAdminToken") || "";
        }

        function saveAdminToken() {
            const token = document.getElementById("adminToken").value.trim();

            if (!token) {
                document.getElementById("adminStatus").textContent =
                    "Kein Token eingegeben.";
                return;
            }

            localStorage.setItem("iotAdminToken", token);

            document.getElementById("adminStatus").textContent =
                "Token wurde im Browser gespeichert.";
        }

        function loadStoredAdminToken() {
            const token = localStorage.getItem("iotAdminToken");

            if (token) {
                document.getElementById("adminToken").value = token;
                document.getElementById("adminStatus").textContent =
                    "Gespeicherter Token geladen.";
            }
        }

        async function adminPost(path, doRefresh = true) {
            const token = getAdminToken();

            if (!token) {
                document.getElementById("adminStatus").textContent =
                    "Bitte zuerst den Admin-/WebSocket-Token eingeben.";
                return null;
            }

            const separator = path.includes("?") ? "&" : "?";
            const url = path + separator + "token=" + encodeURIComponent(token);

            try {
                const response = await fetch(url, {
                    method: "POST",
                    cache: "no-store"
                });

                const responseText = await response.text();

                let data;

                try {
                    data = JSON.parse(responseText);
                } catch (parseError) {
                    throw new Error(
                        "Server hat kein gültiges JSON zurückgegeben. HTTP " +
                        response.status +
                        ": " +
                        responseText.substring(0, 200)
                    );
                }

                if (!response.ok) {
                    throw new Error(
                        "HTTP " +
                        response.status +
                        ": " +
                        (data.message || data.detail || JSON.stringify(data))
                    );
                }

                if (data.status === "ok") {
                    document.getElementById("adminStatus").textContent =
                        data.message || "Aktion erfolgreich ausgeführt.";
                } else {
                    document.getElementById("adminStatus").textContent =
                        "Fehler: " + (data.message || data.detail || "Unbekannter Fehler");
                }

                if (doRefresh) {
                    await refresh();
                }

                return data;

            } catch (error) {
                document.getElementById("adminStatus").textContent =
                    "Fehler beim Ausführen der Aktion: " + error.message;

                console.error(error);
                return null;
            }
        }

        async function resetSamples() {
            const confirmed = confirm("Wirklich alle Heatmap-Samples löschen?");

            if (!confirmed) {
                return;
            }

            const result = await adminPost("/admin/reset-samples", false);

            if (result && result.status === "ok") {
                const canvas = document.getElementById("heatmapCanvas");
                const ctx = canvas.getContext("2d");

                ctx.clearRect(0, 0, canvas.width, canvas.height);

                document.querySelectorAll(".target-point").forEach(el => el.remove());
                document.querySelectorAll(".trail-point").forEach(el => el.remove());

                await refresh();
            }
        }

        async function addCustomSample() {
            const xNumber = Number(document.getElementById("sampleX").value);
            const yNumber = Number(document.getElementById("sampleY").value);
            const rssiNumber = Number(document.getElementById("sampleRssi").value);

            if (!Number.isFinite(rssiNumber)) {
                document.getElementById("adminStatus").textContent =
                    "RSSI muss eine gültige Zahl sein.";
                return;
            }

            if (!Number.isFinite(xNumber) || xNumber < 0) {
                document.getElementById("adminStatus").textContent =
                    "x darf nicht negativ sein.";
                return;
            }

            if (!Number.isFinite(yNumber) || yNumber < 0) {
                document.getElementById("adminStatus").textContent =
                    "y darf nicht negativ sein.";
                return;
            }

            if (!validateInsideRoom(xNumber, yNumber, "Das ePaper-Sample")) {
                return;
            }

            const x = xNumber.toFixed(1);
            const y = yNumber.toFixed(1);

            await adminPost(
                "/admin/add-sample?x=" +
                encodeURIComponent(x) +
                "&y=" +
                encodeURIComponent(y) +
                "&wifi_rssi=" +
                encodeURIComponent(Math.round(rssiNumber))
            );
        }

        async function addDemoSamples() {
            await adminPost("/admin/demo-samples");
        }

        async function setRouter() {
            const name = document.getElementById("routerName").value || "WLAN-Router";
            const xNumber = Number(document.getElementById("routerX").value);
            const yNumber = Number(document.getElementById("routerY").value);

            if (!Number.isFinite(xNumber) || xNumber < 0) {
                document.getElementById("adminStatus").textContent =
                    "Router-x darf nicht negativ sein.";
                return;
            }

            if (!Number.isFinite(yNumber) || yNumber < 0) {
                document.getElementById("adminStatus").textContent =
                    "Router-y darf nicht negativ sein.";
                return;
            }

            if (!validateInsideRoom(xNumber, yNumber, "Der Router")) {
                return;
            }

            const x = xNumber.toFixed(1);
            const y = yNumber.toFixed(1);

            await adminPost(
                "/admin/set-router?name=" +
                encodeURIComponent(name) +
                "&x=" +
                encodeURIComponent(x) +
                "&y=" +
                encodeURIComponent(y)
            );
        }

        async function clearRouter() {
            await adminPost("/admin/clear-router");
        }

        async function setDevicePosition(deviceId, doRefresh = true) {
            const xNumber = Number(document.getElementById(deviceId + "X").value);
            const yNumber = Number(document.getElementById(deviceId + "Y").value);

            if (!Number.isFinite(xNumber) || xNumber < 0) {
                document.getElementById("adminStatus").textContent =
                    "ESP-x darf nicht negativ sein.";
                return;
            }

            if (!Number.isFinite(yNumber) || yNumber < 0) {
                document.getElementById("adminStatus").textContent =
                    "ESP-y darf nicht negativ sein.";
                return;
            }

            if (!validateInsideRoom(xNumber, yNumber, deviceId)) {
                return;
            }

            await adminPost(
                "/admin/set-device-position?device_id=" +
                encodeURIComponent(deviceId) +
                "&x=" +
                encodeURIComponent(xNumber.toFixed(1)) +
                "&y=" +
                encodeURIComponent(yNumber.toFixed(1)),
                doRefresh
            );
        }

        async function resetDevicePositions() {
            await adminPost("/admin/reset-device-positions");
        }

        async function alignDevicesToRoom() {
            document.getElementById("esp01X").value = "0.0";
            document.getElementById("esp01Y").value = "0.0";

            document.getElementById("esp02X").value = "0.0";
            document.getElementById("esp02Y").value = baseRoomHeight.toFixed(1);

            document.getElementById("esp03X").value = baseRoomWidth.toFixed(1);
            document.getElementById("esp03Y").value = baseRoomHeight.toFixed(1);

            document.getElementById("esp04X").value = baseRoomWidth.toFixed(1);
            document.getElementById("esp04Y").value = "0.0";

            await setDevicePosition("esp01", false);
            await setDevicePosition("esp02", false);
            await setDevicePosition("esp03", false);
            await setDevicePosition("esp04", false);

            document.getElementById("adminStatus").textContent =
                "ESP-Positionen wurden an die aktuelle Raumgröße angepasst.";

            await refresh();
        }

        loadStoredAdminToken();
        loadStoredHeatmapMode();
        loadStoredRoomSize();
        refresh();

        setInterval(refresh, 3000);
        window.addEventListener("resize", refresh);
    </script>
</body>
</html>
    """
