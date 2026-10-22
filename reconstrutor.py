"""
reconstrutor.py
Lê a serial do Heltec, descriptografa o LoRaWAN e reconstrói a imagem JPEG.

Parâmetros do enlace (tamanho do chunk, cabeçalho, parser): enlace.py.

Chunks que não chegarem: mande RESEND:<índices> no transmissor enquanto este script
está rodando. O RESEND reenvia a MESMA foto. Não use CAPTURE para completar: ele tira
outra foto e os chunks dela não podem ser misturados com os da primeira.

Requisitos:  pip install pyserial pycryptodome
"""

import sys
import serial

import config
import enlace

# ---------------------------------------------------------------------------
# Configuração: porta e chaves vêm do .env (veja .env.example), nunca do código
# ---------------------------------------------------------------------------
RX_SERIAL_PORT = config.require("RX_SERIAL_PORT")   # porta do Heltec
BAUD_RATE      = 115200
OUTPUT_FILE    = "imagem_recebida.jpg"

DEV_ADDR_HEX = config.get("LORA_DEV_ADDR", "")
APP_SKEY_HEX = config.get("LORA_APP_SKEY", "")

# ---------------------------------------------------------------------------

# --- Main -----------------------------------------------------------------
def main():
    if not APP_SKEY_HEX:
        sys.exit("APP_SKEY não configurada: defina LORA_APP_SKEY no .env (veja .env.example).")
    app_skey = bytes.fromhex(APP_SKEY_HEX)
    # Se LORA_DEV_ADDR estiver no .env, ignora frames de outros dispositivos
    dev_addr = bytes.fromhex(DEV_ADDR_HEX) if DEV_ADDR_HEX else None

    chunks: dict[int, bytes] = {}
    total: int | None = None
    leitura: int | None = None   # id da foto em andamento (sorteado pelo transmissor a cada CAPTURE)

    print(f"Abrindo {RX_SERIAL_PORT} @ {BAUD_RATE}...")
    with serial.Serial(RX_SERIAL_PORT, BAUD_RATE, timeout=1) as ser:
        # Descarta qualquer dado antigo que ficou no buffer do sistema operacional
        # (remanescente de sessões anteriores ou do boot do Heltec)
        ser.reset_input_buffer()
        print("Buffer limpo.")
        print(">>> Mande CAPTURE no transmissor agora. <<<")
        print("Se faltar algum chunk, mande RESEND:<índices base 0> SEM fechar este script.\n")
        try:
            while True:
                linha = ser.readline().decode(errors="ignore").strip()
                if not linha:
                    continue

                m = enlace.LINE_RE.search(linha)
                if not m:
                    print(linha)           # log normal do ESP32 (boot, debug)
                    continue

                hex_frame, rssi = m.groups()
                try:
                    info = enlace.parse_uplink(bytes.fromhex(hex_frame), app_skey, dev_addr)
                    leitura_id, chunk_idx, chunk_total, chunk_data = enlace.parse_chunk(info["payload"])
                except ValueError as e:
                    print(f"[ignorado] {e}")
                    continue

                if leitura is None:
                    leitura = leitura_id
                    total = chunk_total
                    print(f"[info] leitura {leitura} detectada: {total} chunks de até {enlace.CHUNK_DATA_SIZE} bytes")
                elif leitura_id != leitura or chunk_total != total:
                    # Nova foto (CAPTURE enviado de novo) - reseta tudo
                    print(f"\n[info] nova leitura {leitura_id} ({chunk_total} chunks) - descartando a anterior ({leitura})")
                    chunks = {}
                    leitura = leitura_id
                    total = chunk_total

                if chunk_idx not in chunks:
                    chunks[chunk_idx] = chunk_data
                    faltam = total - len(chunks)
                    print(f"  [chunk {chunk_idx:>3}/{total - 1}]  "
                          f"{len(chunk_data):>3} bytes  RSSI={rssi}  "
                          f"faltam {faltam}")
                else:
                    print(f"  [chunk {chunk_idx:>3}/{total - 1}] duplicado, ignorado")

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
        # Índices base 0, os mesmos que o RESEND do transmissor usa
        print(f"Chunks faltando (base 0): {faltando}")
        print(f"Para completar, mande no transmissor ENQUANTO este script está rodando:  RESEND:{','.join(map(str, faltando))}")
        print("(se já saiu do script, os chunks recebidos se perderam: rode de novo e mande CAPTURE)\n")
        # Salva versão parcial com zeros nos buracos (pode abrir como JPEG parcial)
        partes = b"".join(chunks.get(i, b"\x00" * enlace.CHUNK_DATA_SIZE) for i in range(total_real))
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
