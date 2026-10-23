import sys
from pathlib import Path

import serial
import json
import base64
import time
import paho.mqtt.client as mqtt

# config.py fica na raiz do repositório (uma pasta acima desta)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config

# --- Configuration (valores no .env, veja .env.example) ---
SERIAL_PORT = config.require("TX_SERIAL_PORT")
BAUD_RATE = 115200
MQTT_BROKER = config.get("MQTT_BROKER", "127.0.0.1")
MQTT_PORT = int(config.get("MQTT_PORT", "1883"))

# --- ChirpStack Identifiers ---
APPLICATION_ID = config.require("CHIRPSTACK_APPLICATION_ID")
DEV_EUI = config.require("CHIRPSTACK_DEV_EUI")

MQTT_TOPIC = f"application/{APPLICATION_ID}/device/{DEV_EUI}/event/up"

def connect_mqtt():
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    try:
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
        return client
    except Exception as e:
        print(f"Failed to connect to MQTT Broker: {e}")
        exit(1)

def run_bridge():
    client = connect_mqtt()
    client.loop_start() 
    
    while True:
        try:
            # Open port and explicitly manage DTR/RTS to mirror Arduino IDE behavior
            with serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1) as ser:
                ser.dtr = False
                ser.rts = False
                
                print(f"\nListening on {SERIAL_PORT}...")
                print(f"Publishing to MQTT topic: {MQTT_TOPIC}")
                print("Waiting for ESP32-CAM data (Press Reset on the board to start)...")
                
                while True:
                    line = ser.readline().decode('ascii', errors='ignore').strip()
                    if not line:
                        continue
                        
                    # Print raw lines to terminal so you can see if it's capturing anything at all
                    print(f"RAW: {line}")

                    if not line.startswith("CHUNK"):
                        continue

                    parts = line.split(',')
                    if len(parts) < 4:
                        continue
                        
                    chunk_index = int(parts[1])
                    hex_payload = parts[3]
                    raw_bytes = bytes.fromhex(hex_payload)
                    
                    uplink_data = {
                        "deviceInfo": {
                            "applicationId": APPLICATION_ID,
                            "devEui": DEV_EUI
                        },
                        "data": base64.b64encode(raw_bytes).decode('ascii'),
                        "fCnt": chunk_index,
                        "fPort": 10
                    }
                    
                    client.publish(MQTT_TOPIC, json.dumps(uplink_data))
                    print(f"Forwarded Chunk {chunk_index} to ChirpStack MQTT")
                    
        except serial.SerialException:
            print("\n[!] USB Connection lost. Reconnecting in 3 seconds...")
            time.sleep(3)
        except KeyboardInterrupt:
            print("\nBridge stopped manually.")
            break
            
    client.loop_stop()
    client.disconnect()

if __name__ == '__main__':
    run_bridge()