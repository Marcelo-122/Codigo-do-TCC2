import serial
import base64
import json
import socket
import time
import os
import threading
from Crypto.Cipher import AES
from Crypto.Hash import CMAC

import config

# --- Gateway UDP Configuration (valores no .env, veja .env.example) ---
UDP_IP = config.require("GATEWAY_UDP_IP")
UDP_PORT = int(config.get("GATEWAY_UDP_PORT", "1700"))
GATEWAY_MAC = config.require_hex("GATEWAY_MAC", 8)

# --- ABP Session Keys (valores no .env, nunca no código) ---
DEV_ADDR = config.require_hex("LORA_DEV_ADDR", 4)[::-1]  # LoRaWAN expects DevAddr in Little-Endian
NWK_S_KEY = config.require_hex("LORA_NWK_SKEY", 16)
APP_S_KEY = config.require_hex("LORA_APP_SKEY", 16)

SERIAL_PORT = config.require("TX_SERIAL_PORT")
BAUD_RATE = 115200

# --- AU915 sub-band 2 (channels 8-15), SF8 for ANATEL compliance ---
# This MUST match the region_config_id / [[regions.gateway.channels]] you configured
# on the ChirpStack side (chirpstack.toml or MQTT/UDP forwarder). If your server is
# set up for a different AU915 sub-band, swap this frequency accordingly.
FREQ = 868.1          # channel 8 of AU915 sub-band 2
DATARATE = "SF7BW125"
CODING_RATE = "4/5"

STATS_INTERVAL = 30    # keep in sync with "Stats interval (secs)" in the gateway config

# --- Shared counters for periodic stat push ---
stats_lock = threading.Lock()
stats = {"rxnb": 0, "rxok": 0, "txnb": 0}


def encrypt_frmpayload(payload, fcnt):
    """Encrypts the raw chunk data using AES-128 CTR mode (LoRaWAN standard)"""
    fcnt_bytes = fcnt.to_bytes(4, 'little')
    cipher = AES.new(APP_S_KEY, AES.MODE_ECB)
    encrypted = bytearray()

    for i in range(len(payload)):
        if i % 16 == 0:
            block_num = int(i / 16) + 1
            # A-Block format: 0x01 | 0x00 (x4) | Dir (0) | DevAddr | FCnt | 0x00 | BlockNum
            a_block = b'\x01\x00\x00\x00\x00\x00' + DEV_ADDR + fcnt_bytes + b'\x00' + bytes([block_num])
            s_block = cipher.encrypt(a_block)
        encrypted.append(payload[i] ^ s_block[i % 16])

    return bytes(encrypted)


def calculate_mic(msg, fcnt):
    """Calculates the AES-CMAC over the payload using the Network Session Key"""
    fcnt_bytes = fcnt.to_bytes(4, 'little')
    # B0-Block format: 0x49 | 0x00 (x4) | Dir (0) | DevAddr | FCnt | 0x00 | MsgLen
    b0 = b'\x49\x00\x00\x00\x00\x00' + DEV_ADDR + fcnt_bytes + b'\x00' + bytes([len(msg)])

    cmac = CMAC.new(NWK_S_KEY, ciphermod=AES)
    cmac.update(b0 + msg)
    return cmac.digest()[:4]


def send_push_data(sock, payload_dict):
    """Wraps a JSON payload in a Semtech PUSH_DATA packet and sends it."""
    token = os.urandom(2)
    packet = b'\x02' + token + b'\x00' + GATEWAY_MAC + json.dumps(payload_dict).encode('utf-8')
    sock.sendto(packet, (UDP_IP, UDP_PORT))


def keepalive_loop(sock):
    """
    Sends PULL_DATA periodically so ChirpStack keeps the downlink path open,
    and pushes a stat object so the gateway shows as online / populates the
    dashboard graphs between uplinks.
    """
    while True:
        token = os.urandom(2)
        # PULL_DATA: version + token + identifier(0x02) + gateway EUI, no JSON payload
        pull_packet = b'\x02' + token + b'\x02' + GATEWAY_MAC
        sock.sendto(pull_packet, (UDP_IP, UDP_PORT))

        with stats_lock:
            rxnb, rxok, txnb = stats["rxnb"], stats["rxok"], stats["txnb"]

        stat_payload = {
            "stat": {
                "time": time.strftime("%Y-%m-%d %H:%M:%S GMT", time.gmtime()),
                "rxnb": rxnb,
                "rxok": rxok,
                "rxfw": rxok,
                "ackr": 100.0,
                "dwnb": 0,
                "txnb": txnb
            }
        }
        send_push_data(sock, stat_payload)
        time.sleep(STATS_INTERVAL)


def run_mac_simulator():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    # Background thread: keeps the gateway marked online + downlink path open
    threading.Thread(target=keepalive_loop, args=(sock,), daemon=True).start()

    print("Spoofing LoRaWAN MAC layer. Press Reset on ESP32-CAM.")

    while True:
        try:
            with serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1) as ser:
                ser.dtr = False
                ser.rts = False
                print(f"Listening on {SERIAL_PORT}...")

                while True:
                    line = ser.readline().decode('ascii', errors='ignore').strip()
                    if not line or not line.startswith("CHUNK"):
                        continue

                    parts = line.split(',')
                    if len(parts) < 4:
                        continue

                    fcnt = int(parts[1])
                    raw_payload = bytes.fromhex(parts[3])

                    # NOTE: if the ESP32-CAM resets and restarts fcnt at 0, ChirpStack's
                    # replay protection will reject subsequent frames unless you either
                    # persist the counter on the device or enable "Disable frame counter
                    # validation" on the ABP device profile.

                    # 1. Build MAC Header (MHDR) - Unconfirmed Data Up (0x40)
                    mhdr = b'\x40'

                    # 2. Build Frame Header (FHDR)
                    fctrl = b'\x00'
                    fcnt_bytes_16 = fcnt.to_bytes(2, 'little')
                    fhdr = DEV_ADDR + fctrl + fcnt_bytes_16

                    # 3. FPort
                    fport = b'\x0A'  # Port 10

                    # 4. Encrypt FRMPayload
                    enc_payload = encrypt_frmpayload(raw_payload, fcnt)

                    # 5. Calculate MIC
                    msg_no_mic = mhdr + fhdr + fport + enc_payload
                    mic = calculate_mic(msg_no_mic, fcnt)

                    # 6. Complete PHYPayload
                    phy_payload = msg_no_mic + mic
                    b64_phy = base64.b64encode(phy_payload).decode('ascii')

                    # 7. Wrap in Semtech UDP Packet Forwarder JSON (AU915 / SF8)
                    rxpk_data = {
                        "rxpk": [{
                            "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                            "tmst": int(time.time() * 1000) & 0xFFFFFFFF,
                            "freq": FREQ,
                            "chan": 0,
                            "rfch": 0,
                            "stat": 1,
                            "modu": "LORA",
                            "datr": DATARATE,
                            "codr": CODING_RATE,
                            "rssi": -45,
                            "lsnr": 10.0,
                            "size": len(phy_payload),
                            "data": b64_phy
                        }]
                    }

                    send_push_data(sock, rxpk_data)

                    with stats_lock:
                        stats["rxnb"] += 1
                        stats["rxok"] += 1

                    print(f"Sent PHYPayload for Chunk {fcnt} on {FREQ} MHz / {DATARATE}")

        except serial.SerialException:
            print("\n[!] USB Connection lost. Reconnecting in 3 seconds...")
            time.sleep(3)
        except KeyboardInterrupt:
            print("\nSimulator stopped.")
            break


if __name__ == '__main__':
    run_mac_simulator()