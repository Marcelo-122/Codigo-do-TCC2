"""Captura quadros crus 160x120 da ESP32-CAM e já os rotula, para o teste híbrido.

Fluxo de cada quadro: você posiciona o medidor, digita a leitura que está vendo nas rodas pretas
(zeros à esquerda incluídos; `?` se a última roda estiver entre dois números), e o script manda o
comando de captura, grava o quadro como PNG sem perdas e acrescenta uma linha ao manifesto
`quadros_160x120.csv`, pronto para `teste_hibrido.py --manifesto quadros_160x120.csv`.

Firmware: captura_quadros/captura_quadros.ino (não o debug_ocr_esp32cam: ele desenha sobre o quadro
e o comprime em JPEG).

Uso:
    python capturar_quadros.py --medidor tianjin_6 --luz dia
    python capturar_quadros.py --porta COM5 --medidor shanghai_4 --luz lampada

Ao digitar: `q` encerra, Enter em branco não captura nada, `d` descarta o último quadro salvo.
"""
import argparse
import csv
import os
import re
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import serial

W, H = 160, 120
NBYTES = W * H
INICIO, FIM = b"<FRAME_START>", b"<FRAME_END>"
PASTA = Path(__file__).resolve().parent
PASTA_QUADROS = PASTA / "quadros_160x120"
MANIFESTO = PASTA / "quadros_160x120.csv"
COLUNAS = ["arquivo", "rotulo", "x0", "y0", "x1", "y1", "rot", "rot_foto", "medidor", "luz"]


def porta_padrao():
    sys.path.insert(0, str(PASTA.parents[1]))
    import config  # noqa: WPS433  (config.py fica na raiz do repositório)
    return config.require("TX_SERIAL_PORT")


def ler_ate(ser, marcador, limite_s):
    """Lê da serial até aparecer `marcador`; devolve os bytes que já vieram depois dele."""
    buf = b""
    fim = time.time() + limite_s
    while time.time() < fim:
        buf += ser.read(ser.in_waiting or 1)
        if marcador in buf:
            _, depois = buf.split(marcador, 1)
            return depois
    raise TimeoutError(f"não apareceu {marcador!r} em {limite_s} s")


def ler_quadro(ser, limite_s=15):
    """Pede um quadro e o devolve como array HxW uint8. Lê exatamente W*H bytes depois do início."""
    ser.reset_input_buffer()
    ser.write(b"C")
    # O read que achou o marcador já pode ter trazido o começo do quadro
    dados = ler_ate(ser, INICIO, limite_s)
    fim = time.time() + limite_s
    while len(dados) < NBYTES + len(FIM) and time.time() < fim:
        dados += ser.read(NBYTES + len(FIM) - len(dados))
    if len(dados) < NBYTES:
        raise IOError(f"quadro incompleto: {len(dados)} de {NBYTES} bytes")
    dados, resto = dados[:NBYTES], dados[NBYTES:NBYTES + len(FIM)]
    if resto != FIM:
        raise IOError(f"fim de quadro inesperado: {resto!r}")
    return np.frombuffer(dados, dtype=np.uint8).reshape(H, W)


def proximo_indice():
    PASTA_QUADROS.mkdir(exist_ok=True)
    usados = [int(m.group(1)) for p in PASTA_QUADROS.glob("q_*.png") if (m := re.fullmatch(r"q_(\d+)\.png", p.name))]
    return max(usados, default=0) + 1


def gravar_linha(linha):
    novo = not MANIFESTO.exists()
    with open(MANIFESTO, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUNAS)
        if novo:
            w.writeheader()
        w.writerow(linha)


def remover_ultima_linha():
    with open(MANIFESTO, newline="", encoding="utf-8") as f:
        linhas = list(csv.DictReader(f))
    if not linhas:
        return None
    ultima = linhas.pop()
    with open(MANIFESTO, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUNAS)
        w.writeheader()
        w.writerows(linhas)
    return ultima


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--porta", help="porta serial da ESP32-CAM (padrão: TX_SERIAL_PORT do .env)")
    ap.add_argument("--medidor", default="", help="nome do medidor (ex.: tianjin_6), para analisar por medidor")
    ap.add_argument("--luz", default="", help="condição de luz (ex.: dia, noite, lampada)")
    a = ap.parse_args()

    porta = a.porta or porta_padrao()
    ser = serial.Serial(porta, 115200, timeout=1)
    # Na ESP32-CAM-MB, abrir a porta com DTR/RTS desligados deixa a placa em modo de gravação
    # ("waiting for download"). Reset limpo: IO0 solto (DTR) e pulso no EN (RTS).
    ser.dtr = False
    ser.rts = True
    time.sleep(0.2)
    ser.rts = False
    print(f"Conectado em {porta}. Aperte RESET na placa se não aparecer [pronto].")
    try:
        ler_ate(ser, b"[pronto]", 8)
        print("Placa pronta.")
    except TimeoutError:
        ser.write(b"P")
        try:
            ler_ate(ser, b"[pong]", 3)
            print("Placa pronta (já estava ligada).")
        except TimeoutError:
            print("A placa não respondeu. Confira o firmware e a porta.")
            return

    n = proximo_indice()
    ultimo = None
    while True:
        entrada = input(f"[{n}] leitura (rodas pretas, ? se ambígua, d descarta o último, q sai): ").strip()
        if entrada.lower() == "q":
            break
        if entrada.lower() == "d":
            if ultimo and ultimo.exists():
                ultimo.unlink()
                remover_ultima_linha()
                n -= 1
                print(f"   descartado {ultimo.name}")
                ultimo = None
            else:
                print("   nada para descartar")
            continue
        if not entrada:
            continue
        if not re.fullmatch(r"[0-9?]+", entrada):
            print("   só dígitos ou ?")
            continue
        try:
            quadro = ler_quadro(ser)
        except (TimeoutError, IOError) as e:
            print(f"   falha na captura: {e}")
            continue
        nome = f"q_{n:04d}.png"
        cv2.imwrite(str(PASTA_QUADROS / nome), quadro)
        gravar_linha(dict(arquivo=f"{PASTA_QUADROS.name}/{nome}", rotulo=entrada, x0="", y0="", x1="",
                          y1="", rot="", rot_foto="", medidor=a.medidor, luz=a.luz))
        ultimo = PASTA_QUADROS / nome
        print(f"   salvo {nome}  (média de brilho {quadro.mean():.0f})")
        n += 1
    ser.close()


if __name__ == "__main__":
    main()
