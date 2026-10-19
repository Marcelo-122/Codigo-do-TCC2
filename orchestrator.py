"""
Orquestrador completo: imagem -> chunks -> envio -> confirmacao -> reenvio -> remontagem.

Fecha o loop que hoje era manual (rodar decode_lorawan.py, olhar faltando.txt,
digitar RESEND: no ESP32-CAM). Aqui o PC controla as duas pontas ao mesmo tempo:

- Abre a serial do ESP32-CAM (bridge para o Radioenge) e manda comandos
  "SEND:<indice>:<total>:<dados-hex>" para cada chunk.
- Abre a serial do Heltec (receptor) e decodifica cada pacote LoRaWAN que
  chegar, reconhecendo o indice do chunk dentro do texto "CHUNK, idx, total, dados".
- Repete rodadas mandando só o que ainda falta, ate ter todos os chunks.
- No final, junta os chunks na ordem certa e salva a imagem remontada.

Requisitos:
    pip install pyserial pycryptodome

Reaproveita a logica de decodificacao de decode_lorawan.py (mesma pasta).
"""

import os
import time

import serial

import config
from decode_lorawan import LINE_RE, CHUNK_RE, parse_and_decrypt

# ---------------------------------------------------------------------------
# Configuração: portas, chaves e imagem vêm do .env (veja .env.example)
# ---------------------------------------------------------------------------
# Caminho relativo é resolvido a partir da raiz do repositório
IMAGE_PATH = str(config.RAIZ / config.require("IMAGE_PATH"))   # imagem a enviar
TX_SERIAL_PORT = config.require("TX_SERIAL_PORT")   # ESP32-CAM (bridge para o Radioenge)
RX_SERIAL_PORT = config.require("RX_SERIAL_PORT")   # Heltec (receptor)
BAUD_RATE = 115200

CHUNK_SIZE_BYTES = 50          # bytes crus de imagem por chunk (ajustavel)
SEND_INTERVAL_S = 2.0          # mesmo valor do SAFE_INTERVAL_MS no .ino (em segundos)
LISTEN_WINDOW_S = 3.0          # quanto tempo escutar o receptor logo apos cada envio

DEV_ADDR_HEX = config.require("LORA_DEV_ADDR")   # AT+DADDR=? no Radioenge
APP_SKEY_HEX = config.require("LORA_APP_SKEY")   # AT+APPSKEY=? no Radioenge
# ---------------------------------------------------------------------------


def carregar_chunks(path: str, tamanho: int):
    with open(path, "rb") as f:
        dados = f.read()
    return [dados[i:i + tamanho] for i in range(0, len(dados), tamanho)]


def main():
    dev_addr = bytes.fromhex(DEV_ADDR_HEX)
    app_skey = bytes.fromhex(APP_SKEY_HEX)

    chunks = carregar_chunks(IMAGE_PATH, CHUNK_SIZE_BYTES)
    total = len(chunks)
    print(f"Imagem dividida em {total} chunks de ate {CHUNK_SIZE_BYTES} bytes.")

    recebidos = {}  # indice (1-based) -> bytes do chunk

    tx = serial.Serial(TX_SERIAL_PORT, BAUD_RATE, timeout=0.2)
    rx = serial.Serial(RX_SERIAL_PORT, BAUD_RATE, timeout=0.2)
    print("Aguardando as placas resetarem apos abrir a serial...")
    time.sleep(3)  # tempo para as placas resetarem ao abrir a serial

    def aguardar(segundos: float):
        """Durante essa janela: (1) drena a serial do ESP32-CAM e imprime,
        essencial para NAO travar o buffer serial dele (se ninguem le o que
        ele imprime, o Serial.print() do firmware pode bloquear e travar
        o pipeline inteiro); (2) escuta o Heltec e decodifica o que chegar."""
        fim = time.time() + segundos
        while time.time() < fim:
            linha_tx = tx.readline().decode(errors="ignore").strip()
            if linha_tx:
                print(f"  [esp32-cam] {linha_tx}")

            linha_rx = rx.readline().decode(errors="ignore").strip()
            if not linha_rx:
                continue

            match = LINE_RE.search(linha_rx)
            if not match:
                continue

            hex_payload, rssi = match.groups()
            try:
                raw = bytes.fromhex(hex_payload)
                info = parse_and_decrypt(raw, app_skey, dev_addr)
            except Exception as e:
                print(f"  [aviso] pacote recebido mas falhou ao decodificar: {e}")
                continue

            texto = info["plaintext"].decode(errors="replace")
            chunk_match = CHUNK_RE.search(texto)
            if not chunk_match:
                print(f"  [aviso] pacote decodificado mas sem formato CHUNK reconhecido: {texto[:50]!r}")
                continue

            idx = int(chunk_match.group(1))
            dados_hex = texto[chunk_match.end():].strip()
            try:
                dados_bytes = bytes.fromhex(dados_hex)
            except ValueError:
                continue

            if idx not in recebidos:
                recebidos[idx] = dados_bytes
                print(f"  [recebido] chunk {idx}/{total} (RSSI={rssi})")

    rodada = 0
    while len(recebidos) < total:
        rodada += 1
        faltando = [i for i in range(1, total + 1) if i not in recebidos]
        print(f"\n--- Rodada {rodada}: faltam {len(faltando)}/{total} ---")

        for idx in faltando:
            if idx in recebidos:
                continue  # pode ter chegado durante a escuta de outro envio nesta rodada

            dados_hex = chunks[idx - 1].hex().upper()
            cmd = f"SEND:{idx}:{total}:{dados_hex}\n"

            print(f"[enviando] chunk {idx}/{total} ({len(dados_hex)} chars hex)")
            tx.write(cmd.encode())
            tx.flush()

            aguardar(SEND_INTERVAL_S + LISTEN_WINDOW_S)

    print("\nTodos os chunks recebidos! Remontando a imagem...")
    dados_completos = b"".join(recebidos[i] for i in range(1, total + 1))

    extensao = os.path.splitext(IMAGE_PATH)[1] or ".bin"
    saida = "imagem_recebida" + extensao
    with open(saida, "wb") as f:
        f.write(dados_completos)

    print(f"Imagem remontada salva em: {saida}")


if __name__ == "__main__":
    main()