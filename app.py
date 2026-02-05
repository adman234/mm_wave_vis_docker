
"""
Inovelli mmWave Visualizer Backend
Standalone / Docker-friendly version
"""

import json
import os
import traceback
import time
import threading
import gc
from flask import Flask, render_template, request
from flask_socketio import SocketIO
import paho.mqtt.client as mqtt
import logging

# Suppress the Werkzeug development server warning
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

# --- STANDALONE CONFIGURATION (ENV BASED) ---
MQTT_BROKER = os.getenv('MQTT_BROKER', 'localhost')
MQTT_PORT = int(os.getenv('MQTT_PORT', 1883))
MQTT_USERNAME = os.getenv('MQTT_USERNAME', '')
MQTT_PASSWORD = os.getenv('MQTT_PASSWORD', '')
MQTT_BASE_TOPIC = os.getenv('Z2M_BASE_TOPIC', 'zigbee2mqtt')

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

current_topic = None

# Device registry
device_list = {}

def on_connect(client, userdata, flags, rc):
    print(f"Connected to MQTT Broker with code {rc}", flush=True)
    client.subscribe(f"{MQTT_BASE_TOPIC}/#")

def on_message(client, userdata, msg):
    try:
        topic = msg.topic
        payload_str = msg.payload.decode().strip()
        if not payload_str or not payload_str.startswith('{'):
            return

        payload = json.loads(payload_str)

        # --- DEVICE DISCOVERY ---
        if topic.startswith(MQTT_BASE_TOPIC) and "mmWaveVersion" in payload:
            parts = topic.split('/')
            if len(parts) >= 2:
                fname = parts[1]
                if fname not in device_list:
                    device_list[fname] = {
                        "friendly_name": fname,
                        "topic": f"{MQTT_BASE_TOPIC}/{fname}",
                        "interference_zones": [],
                        "detection_zones": [],
                        "stay_zones": [],
                        "zone_config": {"x_min": -400, "x_max": 400, "y_min": 0, "y_max": 600},
                        "last_update": 0,
                        "last_seen": time.time()
                    }
                    print(f"Discovered Inovelli mmWave Switch: {fname}", flush=True)
                    socketio.emit("device_list", list(device_list.values()))
                else:
                    device_list[fname]["last_seen"] = time.time()

        fname = next((n for n, d in device_list.items() if topic.startswith(d["topic"])), None)
        if not fname:
            return

        device_topic = device_list[fname]["topic"]

        # --- RAW PACKET HANDLING ---
        is_raw = payload.get("0") == 29 and payload.get("1") == 47 and payload.get("2") == 18
        if is_raw:
            cmd_id = payload.get("4")

            def parse_bytes(idx):
                low = int(payload.get(str(idx)) or 0)
                high = int(payload.get(str(idx+1)) or 0)
                return int.from_bytes([low, high], "little", signed=True)

            # Target data
            if cmd_id == 1:
                now = time.time()
                if now - device_list[fname]["last_update"] >= 0.1:
                    device_list[fname]["last_update"] = now
                    targets = []
                    offset = 6
                    for _ in range(payload.get("5", 0)):
                        if str(offset+8) not in payload:
                            break
                        targets.append({
                            "id": int(payload.get(str(offset+8)) or 0),
                            "x": parse_bytes(offset),
                            "y": parse_bytes(offset+2),
                            "z": parse_bytes(offset+4),
                            "dop": parse_bytes(offset+6)
                        })
                        offset += 9
                    socketio.emit("new_data", {
                        "topic": device_topic,
                        "payload": {"seq": payload.get("3"), "targets": targets}
                    })

            # Zone packets
            elif cmd_id in (2, 3, 4):
                zones = []
                offset = 6
                for _ in range(payload.get("5", 0)):
                    if str(offset+11) not in payload:
                        break
                    zones.append({
                        "x_min": parse_bytes(offset),
                        "x_max": parse_bytes(offset+2),
                        "y_min": parse_bytes(offset+4),
                        "y_max": parse_bytes(offset+6),
                        "z_min": parse_bytes(offset+8),
                        "z_max": parse_bytes(offset+10),
                    })
                    offset += 12

                if cmd_id == 2:
                    device_list[fname]["interference_zones"] = zones
                    socketio.emit("interference_zones", {"topic": device_topic, "payload": zones})
                elif cmd_id == 3:
                    device_list[fname]["detection_zones"] = zones
                    socketio.emit("detection_zones", {"topic": device_topic, "payload": zones})
                elif cmd_id == 4:
                    device_list[fname]["stay_zones"] = zones
                    socketio.emit("stay_zones", {"topic": device_topic, "payload": zones})

        # --- STANDARD CONFIG UPDATE ---
        config_payload = {k: v for k, v in payload.items() if not k.isdigit()}
        if config_payload:
            socketio.emit("device_config", {"topic": device_topic, "payload": config_payload})
            zone = device_list[fname]["zone_config"]
            changed = False
            if "mmWaveWidthMin" in config_payload:
                zone["x_min"] = int(config_payload["mmWaveWidthMin"]); changed = True
            if "mmWaveWidthMax" in config_payload:
                zone["x_max"] = int(config_payload["mmWaveWidthMax"]); changed = True
            if "mmWaveDepthMin" in config_payload:
                zone["y_min"] = int(config_payload["mmWaveDepthMin"]); changed = True
            if "mmWaveDepthMax" in config_payload:
                zone["y_max"] = int(config_payload["mmWaveDepthMax"]); changed = True
            if changed:
                socketio.emit("zone_config", {"topic": device_topic, "payload": zone})

    except Exception as e:
        print(f"MQTT parse error: {e}", flush=True)
        traceback.print_exc()

mqtt_client = mqtt.Client()
if MQTT_USERNAME and MQTT_PASSWORD:
    mqtt_client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)

mqtt_client.on_connect = on_connect
mqtt_client.on_message = on_message
mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
mqtt_client.loop_start()

# --- SOCKET HANDLERS ---
@socketio.on("request_devices")
def request_devices():
    socketio.emit("device_list", list(device_list.values()))

@socketio.on("change_device")
def change_device(topic):
    global current_topic
    current_topic = topic

@socketio.on("update_parameter")
def update_param(data):
    if current_topic:
        mqtt_client.publish(f"{current_topic}/set", json.dumps({data["param"]: data["value"]}))

@socketio.on("force_sync")
def force_sync():
    if current_topic:
        mqtt_client.publish(f"{current_topic}/get", json.dumps({}))
        mqtt_client.publish(f"{current_topic}/set",
            json.dumps({"mmwave_control_commands": {"controlID": "query_areas"}}))

@socketio.on("send_command")
def send_cmd(cmd):
    actions = {
        0: "reset_mmwave_module",
        1: "set_interference",
        2: "query_areas",
        3: "clear_interference",
        4: "reset_detection_area",
        5: "clear_stay_areas"
    }
    if current_topic and int(cmd) in actions:
        mqtt_client.publish(
            f"{current_topic}/set",
            json.dumps({"mmwave_control_commands": {"controlID": actions[int(cmd)]}})
        )

def cleanup():
    while True:
        time.sleep(60)
        now = time.time()
        for k in list(device_list):
            if now - device_list[k].get("last_seen", 0) > 3600:
                del device_list[k]
        gc.collect()

threading.Thread(target=cleanup, daemon=True).start()

@app.route("/")
def index():
    return render_template("index.html", ingress_path="")

if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=5000, allow_unsafe_werkzeug=True)
