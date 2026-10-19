"""
Decodificador de uplinks LoRaWAN (modo ABP) vindos do Radioenge RD49C.

O que ele faz:
1. Le a serial do ESP32 (linhas no formato "HEX:<bytes em hex>|RSSI:<valor>",
   produzidas pelo receptor_lora32.ino).
2. Separa o frame LoRaWAN em MHDR, DevAddr, FCtrl, FCnt, FPort, FRMPayload e MIC.
3. Descriptografa o FRMPayload com o AppSKey, usando o esquema AES-CTR do LoRaWAN.

Requisitos:
    pip install pyserial pycryptodome

Antes de usar, preencha LORA_DEV_ADDR e LORA_APP_SKEY no .env (veja
.env.example) com os valores reais do seu Radioenge (pegue via AT+DADDR=? e
AT+APPSKEY=? no módulo).
"""

import re
import sys
from Crypto.Cipher import AES

import config

# ---------------------------------------------------------------------------
# Configuração: porta e chaves vêm do .env (veja .env.example), nunca do código
# ---------------------------------------------------------------------------
SERIAL_PORT = config.require("RX_SERIAL_PORT")   # porta serial do Heltec (receptor)
BAUD_RATE = 115200

DEV_ADDR_HEX = config.require("LORA_DEV_ADDR")   # AT+DADDR=?   (4 bytes / 8 hex chars)
APP_SKEY_HEX = config.require("LORA_APP_SKEY")   # AT+APPSKEY=? (16 bytes / 32 hex chars)
# ---------------------------------------------------------------------------

LINE_RE = re.compile(r"HEX:([0-9A-Fa-f]+)\|RSSI:(-?\d+)")
CHUNK_RE = re.compile(r"CHUNK,\s*(\d+),\s*(\d+),")


def aes128_encrypt_block(key: bytes, block: bytes) -> bytes:
    cipher = AES.new(key, AES.MODE_ECB)
    return cipher.encrypt(block)


def decrypt_frmpayload(frmpayload: bytes, key: bytes, dev_addr: bytes, fcnt: int, direction: int) -> bytes:
    """Implementa o esquema de "criptografia" do LoRaWAN (AES-CTR customizado)."""
    result = bytearray()
    num_blocks = (len(frmpayload) + 15) // 16
    for i in range(1, num_blocks + 1):
        a_block = bytes([
            0x01,
            0x00, 0x00, 0x00, 0x00,
            direction,
            dev_addr[0], dev_addr[1], dev_addr[2], dev_addr[3],
            fcnt & 0xFF, (fcnt >> 8) & 0xFF, (fcnt >> 16) & 0xFF, (fcnt >> 24) & 0xFF,
            0x00,
            i,
        ])
        s_block = aes128_encrypt_block(key, a_block)
        chunk = frmpayload[(i - 1) * 16: i * 16]
        result.extend(bytes(b ^ s for b, s in zip(chunk, s_block)))
    return bytes(result)


def parse_and_decrypt(raw: bytes, app_skey: bytes, dev_addr_expected: bytes):
    mhdr = raw[0]
    dev_addr = raw[1:5][::-1]  # DevAddr vem little-endian no frame
    fctrl = raw[5]
    fcnt = raw[6] | (raw[7] << 8)
    fopts_len = fctrl & 0x0F
    idx = 8 + fopts_len

    if dev_addr != dev_addr_expected:
        print(f"[aviso] DevAddr do pacote ({dev_addr.hex()}) diferente do configurado ({dev_addr_expected.hex()})")

    fport = raw[idx]
    idx += 1
    frmpayload_cifrado = raw[idx:-4]  # exclui os 4 bytes finais do MIC
    mic = raw[-4:]

    # direction: 0 = uplink, 1 = downlink
    plaintext = decrypt_frmpayload(frmpayload_cifrado, app_skey, dev_addr, fcnt, direction=0)

    return {
        "mhdr": mhdr,
        "dev_addr": dev_addr.hex().upper(),
        "fcnt": fcnt,
        "fport": fport,
        "mic": mic.hex().upper(),
        "plaintext": plaintext,
    }


def main():
    dev_addr = bytes.fromhex(DEV_ADDR_HEX)
    app_skey = bytes.fromhex(APP_SKEY_HEX)

    try:
        import serial
    except ImportError:
        print("Precisa instalar pyserial: pip install pyserial")
        sys.exit(1)

    # Rastreio de chunks recebidos, para saber o que precisa ser reenviado
    # (essencial já que um gateway single-channel só pega uma fração das
    # transmissões de um transmissor com hopping habilitado).
    received_indices = set()
    total_chunks = None

    def print_status():
        if total_chunks is None:
            return
        faltando = sorted(set(range(1, total_chunks + 1)) - received_indices)
        print(f"[status] recebidos {len(received_indices)}/{total_chunks}")
        if faltando:
            print(f"[status] faltando: {','.join(str(i) for i in faltando)}")
        else:
            print("[status] lote completo! nada faltando.")

    print(f"Abrindo {SERIAL_PORT} @ {BAUD_RATE}...")
    with serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1) as ser:
        print("Escutando... (Ctrl+C para ver o status e sair)")
        try:
            while True:
                line = ser.readline().decode(errors="ignore").strip()
                if not line:
                    continue

                match = LINE_RE.search(line)
                if not match:
                    print(line)  # imprime qualquer outra linha de log do ESP32 normalmente
                    continue

                hex_payload, rssi = match.groups()
                raw = bytes.fromhex(hex_payload)

                try:
                    info = parse_and_decrypt(raw, app_skey, dev_addr)
                except Exception as e:
                    print(f"[erro ao decodificar] {e} | frame bruto: {hex_payload}")
                    continue

                texto = info["plaintext"].decode(errors="replace")
                print(f"RSSI={rssi} | FCnt={info['fcnt']} | FPort={info['fport']} | Mensagem: {texto}")

                chunk_match = CHUNK_RE.search(texto)
                if chunk_match:
                    idx, total = int(chunk_match.group(1)), int(chunk_match.group(2))
                    total_chunks = total
                    if idx in received_indices:
                        print(f"[status] chunk {idx} repetido (já tinha sido recebido)")
                    received_indices.add(idx)
                    print_status()
        except KeyboardInterrupt:
            print("\nEncerrando...")
            print_status()
            if total_chunks is not None:
                faltando = sorted(set(range(1, total_chunks + 1)) - received_indices)
                if faltando:
                    with open("faltando.txt", "w") as f:
                        f.write(",".join(str(i) for i in faltando))
                    print("Lista de faltantes salva em faltando.txt (pronta pra colar num comando RESEND).")


if __name__ == "__main__":
    main()
