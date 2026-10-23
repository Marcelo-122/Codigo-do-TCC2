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

Tudo e registrado como no reconstrutor.py (registro.py): logs completos em
medicoes/logs/<execucao>/, uma linha em medicoes/transmissao.csv e a imagem em
medicoes/imagens/. Aqui o "disparo" da latencia e o primeiro SEND, e a latencia inclui
as rodadas de reenvio. O PDR vem da contagem de tentativas que o no imprime.

Requisitos:
    pip install pyserial pycryptodome

Parametros do enlace (tamanho do chunk, cabecalho): enlace.py.
"""

import argparse
import random
import sys
import time

import serial

import config
import enlace
import registro

# ---------------------------------------------------------------------------
# Configuração: portas, chaves e imagem vêm do .env (veja .env.example)
# ---------------------------------------------------------------------------
# Caminho relativo é resolvido a partir da raiz do repositório
IMAGE_PATH = str(config.RAIZ / config.require("IMAGE_PATH"))   # imagem a enviar
TX_SERIAL_PORT = config.require("TX_SERIAL_PORT")   # ESP32-CAM (bridge para o Radioenge)
RX_SERIAL_PORT = config.require("RX_SERIAL_PORT")   # Heltec (receptor)

SEND_INTERVAL_S = enlace.INTERVALO_ENVIO_S   # mesmo valor do SEND_INTERVAL_MS no .ino;
                                             # durante esse tempo o PC escuta o receptor
LIMITE_DE_TEMPO_S = 6 * 3600                 # a leitura so e abandonada depois de 6 h

DEV_ADDR_HEX = config.require("LORA_DEV_ADDR")   # AT+DADDR=? no Radioenge
APP_SKEY_HEX = config.require("LORA_APP_SKEY")   # AT+APPSKEY=? no Radioenge
# ---------------------------------------------------------------------------


def carregar_chunks(path: str, tamanho: int):
    with open(path, "rb") as f:
        dados = f.read()
    return [dados[i:i + tamanho] for i in range(0, len(dados), tamanho)]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--distancia", type=float, default=None, metavar="M",
                    help="distancia entre no e receptor em metros (vai no CSV)")
    ap.add_argument("--rotulo", default="", help="texto livre que vai no CSV")
    ap.add_argument("--pasta-medicoes", default=str(registro.PASTA_MEDICOES), help=argparse.SUPPRESS)
    args = ap.parse_args()

    dev_addr = bytes.fromhex(DEV_ADDR_HEX)
    app_skey = bytes.fromhex(APP_SKEY_HEX)

    chunks = carregar_chunks(IMAGE_PATH, enlace.CHUNK_DATA_SIZE)
    total = len(chunks)
    leitura_id = random.randrange(0x10000)   # identifica esta foto no cabecalho dos chunks
    print(f"Imagem dividida em {total} chunks de ate {enlace.CHUNK_DATA_SIZE} bytes (leitura id {leitura_id}).")

    ex = registro.Execucao(
        modo="orquestrador", rotulo=args.rotulo, distancia_m=args.distancia,
        pasta_medicoes=args.pasta_medicoes,
        extras={"portas": {"tx": TX_SERIAL_PORT, "rx": RX_SERIAL_PORT},
                "imagem_origem": IMAGE_PATH, "leitura_id": leitura_id})
    # grace 0: o SEND nao imprime "[envio] concluido", entao a leitura fecha ao completar
    sessao = registro.Sessao(ex, app_skey, dev_addr, timeout_leitura_s=LIMITE_DE_TEMPO_S)
    print(f"Registro desta execucao: {ex.pasta}")

    motivo_fim, erro = "fim_da_execucao", None
    tx = rx = None
    rodada = 0
    try:
        tx = registro.abrir_serial(TX_SERIAL_PORT)
        rx = registro.abrir_serial(RX_SERIAL_PORT)
        leitor_tx, leitor_rx = registro.LinhasSerial(tx), registro.LinhasSerial(rx)
        print("Aguardando as seriais estabilizarem...")
        time.sleep(2)
        leitor_tx.ler(), leitor_rx.ler()      # descarta o que ja estava no buffer

        def aguardar(segundos: float):
            """Durante essa janela: (1) drena a serial do ESP32-CAM e imprime,
            essencial para NAO travar o buffer serial dele (se ninguem le o que
            ele imprime, o Serial.print() do firmware pode bloquear e travar
            o pipeline inteiro); (2) escuta o Heltec e decodifica o que chegar.
            Cada linha vai para o registro com o instante em que foi lida."""
            fim = time.perf_counter() + segundos
            while time.perf_counter() < fim:
                for t, linha in leitor_tx.ler():
                    print(f"  [esp32-cam] {linha}")
                    sessao.linha_tx(linha, t)
                for t, linha in leitor_rx.ler():
                    sessao.linha_rx(linha, t)
                sessao.verificar(time.perf_counter())
                if leitura.completa:
                    return
                time.sleep(0.005)

        leitura = sessao.disparar(time.perf_counter(), leitura_id)   # disparo = primeiro SEND
        while not leitura.completa:
            rodada += 1
            faltando = [i for i in range(total) if i not in leitura.chunks]
            print(f"\n--- Rodada {rodada}: faltam {len(faltando)}/{total} ---")
            ex.evento("rodada", n=rodada, faltando=faltando)

            for idx in faltando:
                if idx in leitura.chunks:
                    continue  # pode ter chegado durante a escuta de outro envio nesta rodada

                dados_hex = chunks[idx].hex().upper()
                cmd = f"SEND:{leitura_id}:{idx}:{total}:{dados_hex}\n"

                print(f"[enviando] chunk {idx}/{total - 1} ({len(dados_hex)} chars hex)")
                tx.write(cmd.encode())
                ex.evento("send", indice=idx, rodada=rodada)

                aguardar(SEND_INTERVAL_S)
                if leitura.completa:
                    break

        print("\nTodos os chunks recebidos! Imagem remontada.")
    except KeyboardInterrupt:
        motivo_fim = "interrompido"
        print("\nInterrompido pelo usuario.")
    except (serial.SerialException, OSError) as e:
        motivo_fim, erro = "erro_serial", str(e)
        print(f"\n[ERRO] serial: {e}")
    finally:
        sessao.encerrar(motivo_fim, time.perf_counter())
        print()
        for linha in registro.estatisticas(sessao.resumos):
            print(linha)
        if sessao.resumos and sessao.resumos[-1]["imagem_arquivo"]:
            print(f"Imagem salva em: {ex.pasta_medicoes / sessao.resumos[-1]['imagem_arquivo']}")
        print(f"Logs em {ex.pasta}")
        ex.fechar(motivo_fim=motivo_fim, erro=erro, leituras=len(sessao.resumos), rodadas=rodada)
        for s in (tx, rx):
            if s is not None:
                try:
                    s.close()
                except (serial.SerialException, OSError):
                    pass
    if erro:
        sys.exit(1)


if __name__ == "__main__":
    main()
