import binascii
from pathlib import Path

# Arquivos ao lado deste script (legado/), não no diretório de onde você o chamou
INPUT_FILE = str(Path(__file__).resolve().with_name('raw_data.txt'))
OUTPUT_FILE = str(Path(__file__).resolve().with_name('image.jpg'))

def decode_image():
    image_bytes = bytearray()
    expected_crc = ""
    received_chunks = 0

    print(f"Reading from {INPUT_FILE}...")
    
    try:
        with open(INPUT_FILE, 'r') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue

                parts = line.split(',')
                tag = parts[0]

                if tag == "BEGIN":
                    print(f"Frame started. Expecting {parts[1]} bytes across {parts[2]} chunks.")
                
                elif tag == "CHUNK":
                    # Structure: CHUNK,<index>,<len>,<hex_payload>
                    if len(parts) == 4:
                        hex_payload = parts[3]
                        # Convert the hex string back to raw bytes
                        image_bytes.extend(bytes.fromhex(hex_payload))
                        received_chunks += 1
                
                elif tag == "END":
                    if len(parts) == 2:
                        expected_crc = parts[1]
                    break

        print(f"Processed {received_chunks} chunks. Total size: {len(image_bytes)} bytes.")

        # Verify the CRC32 checksum
        # We use & 0xFFFFFFFF to ensure it's a 32-bit unsigned integer across all Python versions
        actual_crc = binascii.crc32(image_bytes) & 0xFFFFFFFF
        actual_crc_hex = f"{actual_crc:08X}"

        print(f"Expected CRC: {expected_crc}")
        print(f"Actual CRC:   {actual_crc_hex}")

        if expected_crc == actual_crc_hex:
            print("[SUCCESS] Checksum matches! Image data is perfectly intact.")
        else:
            print("[WARNING] Checksum mismatch! The image might be corrupted or missing chunks.")

        # Save the final binary data as a JPG
        with open(OUTPUT_FILE, 'wb') as img_file:
            img_file.write(image_bytes)
            
        print(f"Image successfully saved as '{OUTPUT_FILE}'")

    except FileNotFoundError:
        print(f"Error: Could not find '{INPUT_FILE}'. Make sure you saved the raw data correctly.")
    except Exception as e:
        print(f"An error occurred during decoding: {e}")

if __name__ == '__main__':
    decode_image()