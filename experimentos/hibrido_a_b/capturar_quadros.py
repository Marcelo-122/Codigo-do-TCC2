"""Captura quadros crus 160x120 da ESP32-CAM e já os rotula, para o teste híbrido.

Fluxo de cada quadro: você posiciona o medidor, digita a leitura que está vendo nas rodas pretas
(zeros à esquerda incluídos; `?` se a última roda estiver entre dois números), e o script manda o
comando de captura, grava o quadro como PNG sem perdas e acrescenta uma linha ao manifesto
`quadros_160x120.csv`, pronto para `teste_hibrido.py --manifesto quadros_160x120.csv`.

Firmware: captura_quadros/captura_quadros.ino ou o do calibrador (Rede/calibrar_roi_esp32cam), que mandam o mesmo
quadro cru; com o do calibrador, dá para calibrar a ROI e capturar sem trocar de firmware. Não use o
debug_ocr_esp32cam: ele desenha sobre o quadro e o comprime em JPEG.

Uso:
    python capturar_quadros.py --medidor tianjin_6 --luz dia
    python capturar_quadros.py --porta COM5 --medidor shanghai_4 --luz lampada

Ao digitar: `q` encerra, Enter em branco não captura nada, `d` descarta o último quadro salvo.

Uma janela mostra o quadro ao vivo (~1,8 s por quadro), com a caixa da ROI do calibrador (`--roi`, padrão
`roi_fisico_1.json`) e a leitura que o classificador faria; depois de cada captura, mostra a foto salva por 1,5 s.
O que vai para o disco é sempre o quadro cru, sem desenho. `--sem-janela` volta ao modo só de terminal.
"""
import argparse
import csv
import json
import os
import queue
import re
import sys
import threading
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


# Comando que pede um quadro: "C" no captura_quadros.ino, "QUADRO\n" no calibrar_roi_esp32cam.ino (os dois mandam o
# mesmo formato). main() troca para o do calibrador se for ele que responder.
PEDIR_QUADRO = [b"C"]


def ler_quadro(ser, limite_s=15):
    """Pede um quadro e o devolve como array HxW uint8. Lê exatamente W*H bytes depois do início."""
    ser.reset_input_buffer()
    ser.write(PEDIR_QUADRO[0])
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


def carregar_roi(caminho):
    """ROI do calibrar_roi_esp32cam (JSON) ou None. Só serve para a janela: o quadro salvo é sempre o cru."""
    if not caminho or not Path(caminho).exists():
        return None
    d = json.loads(Path(caminho).read_text(encoding="utf-8"))
    face = tuple(d.get("face_pct", (0, 100)))
    return {"caixa": tuple(d["caixa"]), "n": int(d["n_digitos"]), "face": face, "realce": int(d.get("realce", 0)),
            "nome": Path(caminho).name}


def criar_leitor():
    """Classificador do pipeline (o mesmo do firmware), ou None se faltar o ai-edge-litert/tensorflow."""
    try:
        sys.path.insert(0, str(PASTA.parents[1] / "ocr"))
        import pipeline_nuvem as pn  # noqa: WPS433
        return pn.LeitorB()
    except Exception as e:  # noqa: BLE001  (a janela funciona sem a leitura)
        print(f"(sem leitura na janela: {e})")
        return None


def ler_roi(quadro, roi, leitor):
    if not (roi and leitor):
        return ""
    return leitor.ler(quadro, roi["n"], caixa=roi["caixa"], face=roi["face"], realce=roi["realce"])["leitura"]


def mostrar(janela, quadro, roi, leitor, estado, aviso, esc=4):
    """Quadro ampliado com a caixa e as fatias da ROI; embaixo, a leitura do classificador e o último aviso."""
    img = cv2.cvtColor(cv2.resize(quadro, (W * esc, H * esc), interpolation=cv2.INTER_NEAREST), cv2.COLOR_GRAY2BGR)
    linha1 = f"{estado}   brilho medio {quadro.mean():.0f}"
    if roi:
        x0, y0, x1, y1 = roi["caixa"]
        larg = x1 - x0
        for i in range(1, roi["n"]):
            sx = x0 + larg * i // roi["n"]
            cv2.line(img, (sx * esc, y0 * esc), (sx * esc, y1 * esc), (0, 220, 255), 1)
        cv2.rectangle(img, (x0 * esc, y0 * esc), (x1 * esc - 1, y1 * esc - 1), (0, 255, 0), 1)
        lido = ler_roi(quadro, roi, leitor)
        if lido:
            linha1 += f"   leitura {lido}  ({roi['nome']})"
    painel = np.full((50, W * esc, 3), 30, np.uint8)
    cv2.putText(painel, linha1, (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
    cv2.putText(painel, aviso, (8, 42), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (230, 230, 230), 1)
    cv2.imshow(janela, np.vstack([img, painel]))
    cv2.waitKey(1)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--porta", help="porta serial da ESP32-CAM (padrão: TX_SERIAL_PORT do .env)")
    ap.add_argument("--medidor", default="", help="nome do medidor (ex.: tianjin_6), para analisar por medidor")
    ap.add_argument("--luz", default="", help="condição de luz (ex.: dia, noite, lampada)")
    ap.add_argument("--roi", default=str(PASTA / "roi_fisico_1.json"),
                    help="JSON do calibrador, só para desenhar a caixa e mostrar a leitura na janela "
                         "(padrão: roi_fisico_1.json desta pasta)")
    ap.add_argument("--sem-janela", action="store_true", help="não abre a janela (só o terminal, como antes)")
    a = ap.parse_args()
    sys.stdout.reconfigure(errors="replace")

    porta = a.porta or porta_padrao()
    ser = serial.Serial(porta, 115200, timeout=1)
    # Na ESP32-CAM-MB, abrir a porta com DTR/RTS desligados deixa a placa em modo de gravação
    # ("waiting for download"). Reset limpo: IO0 solto (DTR) e pulso no EN (RTS).
    ser.dtr = False
    ser.rts = True
    time.sleep(0.2)
    ser.rts = False
    print(f"Conectado em {porta}. Aperte RESET na placa se não aparecer [pronto].")
    # Serve o captura_quadros.ino ("[pronto]") ou o calibrar_roi_esp32cam.ino ("[usb] pronto"): com o
    # calibrador gravado, dá para calibrar a ROI e capturar sem trocar de firmware.
    buf, fim = b"", time.time() + 8
    while time.time() < fim and b"[pronto]" not in buf and b"[usb] pronto" not in buf:
        buf += ser.read(ser.in_waiting or 1)
    if b"[usb] pronto" in buf:
        PEDIR_QUADRO[0] = b"QUADRO\n"
        print("Placa pronta (firmware do calibrador).")
    elif b"[pronto]" in buf:
        print("Placa pronta.")
    else:
        ser.write(b"P")
        try:
            ler_ate(ser, b"[pong]", 3)
            print("Placa pronta (já estava ligada).")
        except TimeoutError:
            print("A placa não respondeu: grave o captura_quadros.ino ou o calibrar_roi_esp32cam.ino e confira a porta.")
            return

    roi = carregar_roi(a.roi)
    leitor = criar_leitor() if (roi and not a.sem_janela) else None
    janela = None if a.sem_janela else "Captura (ao vivo)"
    if janela:
        cv2.namedWindow(janela)
        print("Janela aberta: mostra o quadro ao vivo" + (", a ROI e a leitura do classificador." if roi else ".")
              + " Digite as leituras AQUI no terminal.")

    # O input() fica numa thread: a janela continua atualizando enquanto você olha o medidor e digita.
    linhas, pode_perguntar, prompt = queue.Queue(), threading.Event(), ["" ]

    def ler_teclado():
        while True:
            pode_perguntar.wait()
            pode_perguntar.clear()
            try:
                linhas.put(input(prompt[0]).strip())
            except EOFError:
                linhas.put("q")
                return

    threading.Thread(target=ler_teclado, daemon=True).start()
    n = proximo_indice()
    ultimo, aviso = None, ""
    prompt[0] = f"[{n}] leitura (rodas pretas, ? se ambígua, d descarta o último, q sai): "
    pode_perguntar.set()
    while True:
        try:
            entrada = linhas.get_nowait()
        except queue.Empty:
            entrada = None
        if entrada is None:
            if janela:   # sem comando: atualiza a janela com um quadro novo (~1,8 s cada)
                try:
                    mostrar(janela, ler_quadro(ser), roi, leitor, "AO VIVO", aviso)
                except (TimeoutError, IOError):
                    pass
                if cv2.getWindowProperty(janela, cv2.WND_PROP_VISIBLE) < 1:
                    janela = None
            else:
                time.sleep(0.05)
            continue
        if entrada.lower() == "q":
            break
        if entrada.lower() == "d":
            if ultimo and ultimo.exists():
                ultimo.unlink()
                remover_ultima_linha()
                n -= 1
                print(f"   descartado {ultimo.name}")
                aviso = f"descartado {ultimo.name}"
                ultimo = None
            else:
                print("   nada para descartar")
        elif entrada and not re.fullmatch(r"[0-9?]+", entrada):
            print("   só dígitos ou ?")
        elif entrada:
            try:
                quadro = ler_quadro(ser)
            except (TimeoutError, IOError) as e:
                print(f"   falha na captura: {e}")
                quadro = None
            if quadro is not None:
                nome = f"q_{n:04d}.png"
                cv2.imwrite(str(PASTA_QUADROS / nome), quadro)
                gravar_linha(dict(arquivo=f"{PASTA_QUADROS.name}/{nome}", rotulo=entrada, x0="", y0="", x1="",
                                  y1="", rot="", rot_foto="", medidor=a.medidor, luz=a.luz))
                ultimo = PASTA_QUADROS / nome
                lido = ler_roi(quadro, roi, leitor)
                confere = "" if not lido else ("  leu " + lido + ("  OK" if lido == entrada else "  (diferente)"))
                print(f"   salvo {nome}  (brilho médio {quadro.mean():.0f}){confere}")
                aviso = f"salvo {nome}: rotulo {entrada}" + confere
                if janela:
                    mostrar(janela, quadro, roi, leitor, f"SALVO {nome}", aviso)
                    cv2.waitKey(1500)   # mostra a foto salva antes de voltar ao vivo
                n += 1
        prompt[0] = f"[{n}] leitura (rodas pretas, ? se ambígua, d descarta o último, q sai): "
        pode_perguntar.set()
    ser.close()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
