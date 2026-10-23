import sys
from pathlib import Path

import serial

# config.py fica na raiz do repositório (uma pasta acima desta)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config

# Porta do ESP32-CAM: defina TX_SERIAL_PORT no .env (veja .env.example)
SERIAL_PORT = config.require("TX_SERIAL_PORT")
BAUD_RATE = 115200
OUTPUT_FILE = str(Path(__file__).resolve().with_name('raw_image_data.txt'))

def capture_frame():
    try:
        # Open the serial port and the output file
        with serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=2) as ser, \
             open(OUTPUT_FILE, 'w') as f:
            
            print(f"Listening on {SERIAL_PORT} at {BAUD_RATE} baud...")
            print("Waiting for a BEGIN statement...")
            
            capturing = False
            
            while True:
                # Read a line, decode it, and strip whitespace/newlines
                line = ser.readline().decode('ascii', errors='ignore').strip()
                
                if not line:
                    continue
                
                # Start logging when we see the BEGIN tag
                if line.startswith("BEGIN"):
                    capturing = True
                    print("Incoming frame detected. Saving chunks...")
                
                if capturing:
                    f.write(line + '\n')
                    # Print progress without spamming the whole hex string
                    if line.startswith("CHUNK"):
                        parts = line.split(',')
                        print(f"Received chunk {parts[1]}...")
                        
                # Stop logging when we see the END tag
                if line.startswith("END") and capturing:
                    print(f"Frame capture complete! Saved to {OUTPUT_FILE}")
                    break
                    
    except serial.SerialException as e:
        print(f"Serial Error: {e}")
        print("Tip: Check if the port is correct and if you have read/write permissions (e.g., dialout group).")
    except KeyboardInterrupt:
        print("\nCapture manually aborted.")

if __name__ == '__main__':
    capture_frame()