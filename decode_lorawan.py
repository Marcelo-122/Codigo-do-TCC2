"""
Decodificador de uplinks LoRaWAN (modo ABP) vindos do Radioenge RD49C.

O que ele faz:
1. Le a serial do ESP32 (linhas no formato "HEX:<bytes em hex>|RSSI:<valor>",
   produzidas pelo receptor_lora32.ino).
2. Separa o frame LoRaWAN e descriptografa o FRMPayload com o AppSKey (enlace.py).
3. Le o cabecalho binario do chunk (indice base 0 + total) e mostra o que falta.
   Ao sair (Ctrl+C), grava faltando.txt com os indices prontos para um RESEND.

Requisitos:
    pip install pyserial pycryptodome

Antes de usar, preencha LORA_DEV_ADDR e LORA_APP_SKEY no .env (veja
.env.example) com os valores reais do seu Radioenge (pegue via AT+DADDR=? e
AT+APPSKEY=? no módulo).
"""

import sys

import config
import enlace

# ---------------------------------------------------------------------------
# Configuração: porta e chaves vêm do .env (veja .env.example), nunca do código
# ---------------------------------------------------------------------------
SERIAL_PORT = config.require("RX_SERIAL_PORT")   # porta serial do Heltec (receptor)
BAUD_RATE = 115200

DEV_ADDR_HEX = config.require("LORA_DEV_ADDR")   # AT+DADDR=?   (4 bytes / 8 hex chars)
APP_SKEY_HEX = config.require("LORA_APP_SKEY")   # AT+APPSKEY=? (16 bytes / 32 hex chars)
# ---------------------------------------------------------------------------


def main():
    dev_addr = bytes.fromhex(DEV_ADDR_HEX)
    app_skey = bytes.fromhex(APP_SKEY_HEX)

    try:
        import serial
    except ImportError:
        print("Precisa instalar pyserial: pip install pyserial")
        sys.exit(1)

    # Rastreio de chunks recebidos (indices base 0, como no RESEND do transmissor)
    received_indices = set()
    total_chunks = None

    def faltando():
        return sorted(set(range(total_chunks)) - received_indices)

    def print_status():
        if total_chunks is None:
            return
        falta = faltando()
        print(f"[status] recebidos {len(received_indices)}/{total_chunks}")
        if falta:
            print(f"[status] faltando: {','.join(str(i) for i in falta)}")
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

                match = enlace.LINE_RE.search(line)
                if not match:
                    print(line)  # imprime qualquer outra linha de log do ESP32 normalmente
                    continue

                hex_payload, rssi = match.groups()
                try:
                    info = enlace.parse_uplink(bytes.fromhex(hex_payload), app_skey, dev_addr)
                    idx, total, dados = enlace.parse_chunk(info["payload"])
                except ValueError as e:
                    print(f"[ignorado] {e} | frame bruto: {hex_payload}")
                    continue

                print(f"RSSI={rssi} | FCnt={info['fcnt']} | FPort={info['fport']} | "
                      f"chunk {idx}/{total - 1} ({len(dados)} bytes)")

                if total_chunks is not None and total != total_chunks:
                    print(f"[status] novo lote detectado ({total} chunks) - zerando o rastreio")
                    received_indices.clear()
                total_chunks = total
                if idx in received_indices:
                    print(f"[status] chunk {idx} repetido (já tinha sido recebido)")
                received_indices.add(idx)
                print_status()
        except KeyboardInterrupt:
            print("\nEncerrando...")
            print_status()
            if total_chunks is not None and faltando():
                with open("faltando.txt", "w") as f:
                    f.write(",".join(str(i) for i in faltando()))
                print("Lista de faltantes salva em faltando.txt (pronta pra colar num comando RESEND:).")


if __name__ == "__main__":
    main()
