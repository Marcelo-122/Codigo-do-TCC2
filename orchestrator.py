"""
Orquestrador completo: imagem -> chunks -> envio -> confirmacao -> reenvio -> remontagem.

Fecha o loop que hoje era manual (rodar decode_lorawan.py, olhar faltando.txt,
digitar RESEND: no ESP32-CAM). Aqui o PC controla as duas pontas ao mesmo tempo:

- Abre a serial do ESP32-CAM (bridge para o Radioenge) e manda comandos
  "SEND:<id>:<indice>:<total>:<dados-hex>" para cada chunk (indice base 0; o id
  da leitura e sorteado aqui, uma vez por execucao).
- Abre a serial do Heltec (receptor) e decodifica cada pacote LoRaWAN que
  chegar, lendo o cabecalho binario (id + indice + total) do chunk (enlace.py).
- Repete rodadas mandando só o que ainda falta, ate ter todos os chunks.
- No final, junta os chunks na ordem certa e salva a imagem remontada.

Requisitos:
    pip install pyserial pycryptodome

Parametros do enlace (tamanho do chunk, cabecalho): enlace.py.
"""

import os
import random
import time

import serial

import config
import enlace

# ---------------------------------------------------------------------------
# Configuração: portas, chaves e imagem vêm do .env (veja .env.example)
# ---------------------------------------------------------------------------
# Caminho relativo é resolvido a partir da raiz do repositório
IMAGE_PATH = str(config.RAIZ / config.require("IMAGE_PATH"))   # imagem a enviar
TX_SERIAL_PORT = config.require("TX_SERIAL_PORT")   # ESP32-CAM (bridge para o Radioenge)
RX_SERIAL_PORT = config.require("RX_SERIAL_PORT")   # Heltec (receptor)
BAUD_RATE = 115200

SEND_INTERVAL_S = 7.0          # mesmo valor do SEND_INTERVAL_MS no .ino (em segundos);
                               # durante esse tempo o PC escuta o receptor

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

    chunks = carregar_chunks(IMAGE_PATH, enlace.CHUNK_DATA_SIZE)
    total = len(chunks)
    leitura_id = random.randrange(0x10000)   # identifica esta foto no cabecalho dos chunks
    print(f"Imagem dividida em {total} chunks de ate {enlace.CHUNK_DATA_SIZE} bytes (leitura id {leitura_id}).")

    recebidos = {}  # indice (base 0) -> bytes do chunk

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

            match = enlace.LINE_RE.search(linha_rx)
            if not match:
                continue

            hex_frame, rssi = match.groups()
            try:
                info = enlace.parse_uplink(bytes.fromhex(hex_frame), app_skey, dev_addr)
                id_rx, idx, total_rx, dados = enlace.parse_chunk(info["payload"])
            except ValueError as e:
                print(f"  [ignorado] {e}")
                continue

            if id_rx != leitura_id or total_rx != total:
                print(f"  [ignorado] chunk de outra leitura (id {id_rx}, total {total_rx}; "
                      f"esperado id {leitura_id}, total {total})")
                continue

            if idx not in recebidos:
                recebidos[idx] = dados
                print(f"  [recebido] chunk {idx}/{total - 1} (RSSI={rssi})")

    rodada = 0
    while len(recebidos) < total:
        rodada += 1
        faltando = [i for i in range(total) if i not in recebidos]
        print(f"\n--- Rodada {rodada}: faltam {len(faltando)}/{total} ---")

        for idx in faltando:
            if idx in recebidos:
                continue  # pode ter chegado durante a escuta de outro envio nesta rodada

            dados_hex = chunks[idx].hex().upper()
            cmd = f"SEND:{leitura_id}:{idx}:{total}:{dados_hex}\n"

            print(f"[enviando] chunk {idx}/{total - 1} ({len(dados_hex)} chars hex)")
            tx.write(cmd.encode())
            tx.flush()

            aguardar(SEND_INTERVAL_S)

    print("\nTodos os chunks recebidos! Remontando a imagem...")
    dados_completos = b"".join(recebidos[i] for i in range(total))

    extensao = os.path.splitext(IMAGE_PATH)[1] or ".bin"
    saida = "imagem_recebida" + extensao
    with open(saida, "wb") as f:
        f.write(dados_completos)

    print(f"Imagem remontada salva em: {saida}")


if __name__ == "__main__":
    main()
