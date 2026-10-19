"""
reconstrutor.py
Lê a serial do Heltec, descriptografa o LoRaWAN e reconstrói a imagem JPEG.

Requisitos:  pip install pyserial pycryptodome
"""

import sys
import re
import struct
import serial
from Crypto.Cipher import AES

import config

# ---------------------------------------------------------------------------
# Configuração: porta e chaves vêm do .env (veja .env.example), nunca do código
# ---------------------------------------------------------------------------
RX_SERIAL_PORT = config.require("RX_SERIAL_PORT")   # porta do Heltec
BAUD_RATE      = 115200
OUTPUT_FILE    = "imagem_recebida.jpg"

DEV_ADDR_HEX = config.get("LORA_DEV_ADDR", "")
APP_SKEY_HEX = config.get("LORA_APP_SKEY", "")

# ---------------------------------------------------------------------------

LINE_RE = re.compile(r"HEX:([0-9A-Fa-f]+)\|RSSI:(-?\d+)")

# --- Descriptografia LoRaWAN (AES-128 CTR) --------------------------------
def aes_block(key: bytes, block: bytes) -> bytes:
    return AES.new(key, AES.MODE_ECB).encrypt(block)

def decrypt_payload(frm: bytes, key: bytes, dev_addr: bytes, fcnt: int) -> bytes:
    out = bytearray()
    for i in range(1, (len(frm) + 15) // 16 + 1):
        a = bytes([0x01, 0,0,0,0, 0,
                   dev_addr[0], dev_addr[1], dev_addr[2], dev_addr[3],
                   fcnt & 0xFF, (fcnt>>8)&0xFF, (fcnt>>16)&0xFF, (fcnt>>24)&0xFF,
                   0x00, i])
        s = aes_block(key, a)
        chunk = frm[(i-1)*16 : i*16]
        out.extend(b ^ s_b for b, s_b in zip(chunk, s))
    return bytes(out)

def parse_lorawan(raw: bytes, app_skey: bytes) -> bytes:
    """Extrai e descriptografa o FRMPayload de um frame LoRaWAN de uplink."""
    fctrl     = raw[5]
    fcnt      = raw[6] | (raw[7] << 8)
    fopts_len = fctrl & 0x0F
    idx       = 8 + fopts_len
    # fport = raw[idx]  (ignorado — usamos fport 01 fixo)
    frm_enc   = raw[idx + 1 : -4]          # exclui MIC (4 bytes finais)
    dev_addr  = raw[1:5]             # DevAddr vem little-endian no frame
    return decrypt_payload(frm_enc, app_skey, dev_addr, fcnt)

# --- Main -----------------------------------------------------------------
def main():
    if not APP_SKEY_HEX:
        sys.exit("APP_SKEY não configurada: defina LORA_APP_SKEY no .env (veja .env.example).")
    app_skey = bytes.fromhex(APP_SKEY_HEX)
    dev_addr = bytes.fromhex(DEV_ADDR_HEX)   # usado só pra referência; parse usa o do frame

    chunks: dict[int, bytes] = {}
    total: int | None = None

    print(f"Abrindo {RX_SERIAL_PORT} @ {BAUD_RATE}...")
    with serial.Serial(RX_SERIAL_PORT, BAUD_RATE, timeout=1) as ser:
        # Descarta qualquer dado antigo que ficou no buffer do sistema operacional
        # (remanescente de sessões anteriores ou do boot do Heltec)
        ser.reset_input_buffer()
        print("Buffer limpo.")
        print(">>> Mande CAPTURE no transmissor agora. <<<\n")
        try:
            while True:
                linha = ser.readline().decode(errors="ignore").strip()
                if not linha:
                    continue

                m = LINE_RE.search(linha)
                if not m:
                    print(linha)           # log normal do ESP32 (boot, debug)
                    continue

                hex_frame, rssi = m.groups()
                try:
                    raw     = bytes.fromhex(hex_frame)
                    payload = parse_lorawan(raw, app_skey)
                except Exception as e:
                    print(f"[erro ao decodificar] {e}")
                    continue

                if len(payload) < 4:
                    print(f"[aviso] payload curto demais: {payload.hex()}")
                    continue

                # Header binário: uint16 index + uint16 total (big-endian)
                chunk_idx, chunk_total = struct.unpack(">HH", payload[:4])
                chunk_data = payload[4:]

                if total is None:
                    total = chunk_total
                    print(f"[info] sessão detectada: {total} chunks de até 100 bytes")
                elif chunk_total != total:
                    # Nova sessão começou (CAPTURE enviado de novo) - reseta tudo
                    print(f"\n[info] nova sessão detectada ({chunk_total} chunks) - descartando sessão anterior")
                    chunks = {}
                    total = chunk_total

                if chunk_idx not in chunks:
                    chunks[chunk_idx] = chunk_data
                    faltam = total - len(chunks)
                    print(f"  [chunk {chunk_idx+1:>3}/{total}]  "
                          f"{len(chunk_data):>3} bytes  RSSI={rssi}  "
                          f"faltam {faltam}")
                else:
                    print(f"  [chunk {chunk_idx+1:>3}/{total}] duplicado, ignorado")

                if total and len(chunks) == total:
                    print("\nTodos os chunks recebidos!")
                    break

        except KeyboardInterrupt:
            print("\nInterrompido pelo usuário.")

    if not chunks:
        print("Nenhum chunk recebido. Encerrando.")
        return

    recebidos = len(chunks)
    total_real = total or max(chunks.keys()) + 1
    faltando = [i for i in range(total_real) if i not in chunks]

    print(f"\nRecebidos: {recebidos}/{total_real}  |  Faltando: {len(faltando)}")

    if faltando:
        print(f"Chunks faltando (índices 1-based): {[i+1 for i in faltando]}")
        print("Para reenviar, mande CAPTURE no transmissor — o script manterá")
        print("os chunks que já chegaram e preencherá os que faltam.\n")
        # Salva versão parcial com zeros nos buracos (pode abrir como JPEG parcial)
        partes = b"".join(chunks.get(i, b"\x00" * 100) for i in range(total_real))
        nome_parcial = "imagem_parcial.jpg"
        with open(nome_parcial, "wb") as f:
            f.write(partes)
        print(f"Imagem parcial salva em: {nome_parcial}")
        return

    imagem = b"".join(chunks[i] for i in range(total_real))
    with open(OUTPUT_FILE, "wb") as f:
        f.write(imagem)
    print(f"Imagem completa salva em: {OUTPUT_FILE}  ({len(imagem)} bytes)")

if __name__ == "__main__":
    main()