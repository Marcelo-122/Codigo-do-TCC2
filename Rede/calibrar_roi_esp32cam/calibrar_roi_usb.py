"""Calibra a ROI (caixa dos dígitos) pela USB, sem Wi-Fi.

Precisa do calibrar_roi_esp32cam.ino gravado com USAR_WIFI 0 (o padrão). O script pede
quadros 160x120 crus pela serial (comando QUADRO), mostra numa janela com a caixa, as
fatias, a entrada 28x28 de cada fatia e o dígito que o classificador lê nela (o mesmo
modelo e o mesmo pré-processamento do transmissor_ocr_esp32cam), e grava a ROI, a face e o
realce na NVS da placa (comando SALVAR), além de um JSON e um PNG no PC.

    python Rede/calibrar_roi_esp32cam/calibrar_roi_usb.py --nome roi_fisico_1

Mouse: arraste para desenhar a caixa; arraste dentro dela para mover.
Teclado (com a janela em foco):
    setas      move a caixa 1 px
    a / d      borda direita -1 / +1 px      w / s   borda de baixo -1 / +1 px
    j / l      borda esquerda -1 / +1 px     i / k   borda de cima -1 / +1 px
    + / -      número de dígitos (fatias)
    z / x      início da face da roda -2 / +2 % da fatia   c / v   fim da face -2 / +2 %
               (a face é a parte da fatia em que fica o número; deixe a barra escura entre
               as rodas e os dois-pontos fora das linhas azuis)
    e          liga / desliga o realce (equalização de histograma na face)
    r          alterna a orientação: normal, 180°, invertida na vertical, espelhada;
               fica gravada na placa e vale para todos os firmwares
    espaço     congela / volta ao vivo
    g          grava na placa (NVS) e salva JSON + PNG no PC
    q / Esc    sai

Cada quadro leva ~1,7 s para chegar (19.200 bytes a 115200 baud).
Dependências: opencv-python (com janelas; a -headless não abre a janela), numpy, pyserial e
ai-edge-litert, para a leitura ao vivo (o .venv de experimentos/hibrido_a_b tem todos).
"""
import argparse
import json
import queue
import re
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
import serial

W, H, D = 160, 120, 28          # quadro e entrada do classificador
ESC = 5                         # escala da imagem na janela
NBYTES = W * H
INICIO, FIM = b"<FRAME_START>", b"<FRAME_END>"
RAIZ = Path(__file__).resolve().parents[2]
RE_ROI = re.compile(rb"\[roi\] caixa=(\d+),(\d+),(\d+),(\d+) n_digitos=(\d+)(?: face=(\d+)-(\d+) realce=(\d))? \(quadro")
# (o " (quadro" no fim garante que a linha chegou inteira antes de ler os campos opcionais)
RE_GIRO = re.compile(rb"\[giro\] vflip=([01]) hmirror=([01])")
# Ordem da tecla r: (vflip, hmirror) e o nome mostrado na janela
ORIENTACOES = [((0, 0), "normal"), ((1, 1), "girada 180"), ((1, 0), "invertida na vertical"),
               ((0, 1), "espelhada")]

# Códigos de seta do cv2.waitKeyEx (Windows e Linux/GTK)
SETAS = {2424832: (-1, 0), 2555904: (1, 0), 2490368: (0, -1), 2621440: (0, 1),
         65361: (-1, 0), 65363: (1, 0), 65362: (0, -1), 65364: (0, 1)}


sys.path.insert(0, str(RAIZ / "ocr"))
import pipeline_nuvem as pn  # noqa: E402  (pré-processamento e classificador, iguais ao firmware)


def porta_padrao():
    sys.path.insert(0, str(RAIZ))
    import config  # config.py fica na raiz do repositório
    return config.require("TX_SERIAL_PORT")


def normalizar(r):
    x0, y0, x1, y1, n = (int(round(v)) for v in r)
    n = min(max(n, 1), 10)
    x0, x1 = sorted((x0, x1))
    y0, y1 = sorted((y0, y1))
    x0, x1 = min(max(x0, 0), W), min(max(x1, 0), W)
    y0, y1 = min(max(y0, 0), H), min(max(y1, 0), H)
    if x1 - x0 < n:
        x1 = min(W, x0 + n)
        x0 = x1 - n
    if y1 - y0 < 2:
        y1 = min(H, y0 + 2)
        y0 = y1 - 2
    return [x0, y0, x1, y1, n]


def fatias(r):
    """Mesmo fatiamento inteiro do lerDigitos() do firmware."""
    x0, _, x1, _, n = r
    larg = x1 - x0
    return [(x0 + larg * i // n, x0 + larg * (i + 1) // n) for i in range(n)]


def normalizar_pre(fa, fb, realce):
    """Face (fa, fb) em % da fatia, com pelo menos 10 % de largura; realce 0 ou 1."""
    fa = min(max(fa, 0), 90)
    fb = min(max(fb, fa + 10), 100)
    return [fa, fb, 1 if realce else 0]


class Placa(threading.Thread):
    """Único dono da serial: busca quadros ao vivo e executa os comandos da fila."""

    def __init__(self, porta):
        super().__init__(daemon=True)
        self.ser = serial.Serial(porta, 115200, timeout=0.2)
        # Na ESP32-CAM-MB, abrir a porta mexe em DTR/RTS e pode deixar a placa em modo de
        # gravação ("waiting for download"). Reset limpo: IO0 solto (DTR) e pulso no EN (RTS).
        self.ser.dtr = False
        self.ser.rts = True
        time.sleep(0.2)
        self.ser.rts = False
        self._ler_ate(b"[usb] pronto", 8)
        self.quadro, self.erro, self.ao_vivo, self.parar = None, "", True, False
        self.lock = threading.Lock()
        self.comandos = queue.Queue()

    def _ler_ate(self, marcador, limite_s):
        """Lê até `marcador`; devolve os bytes que já vieram DEPOIS dele (início do quadro)."""
        buf, fim = b"", time.time() + limite_s
        while time.time() < fim:
            buf += self.ser.read(self.ser.in_waiting or 1)
            if marcador in buf:
                return buf.split(marcador, 1)[1]
        raise TimeoutError(f"não apareceu {marcador!r} em {limite_s} s")

    def _quadro(self):
        self.ser.reset_input_buffer()
        self.ser.write(b"QUADRO\n")
        dados, fim = self._ler_ate(INICIO, 6), time.time() + 6
        while len(dados) < NBYTES + len(FIM) and time.time() < fim:
            dados += self.ser.read(NBYTES + len(FIM) - len(dados))
        if len(dados) < NBYTES + len(FIM) or dados[NBYTES:NBYTES + len(FIM)] != FIM:
            raise IOError("quadro incompleto")
        return np.frombuffer(dados[:NBYTES], dtype=np.uint8).reshape(H, W).copy()

    def comando(self, linha, espera=RE_ROI, limite_s=3):
        """Manda uma linha e devolve o primeiro match de `espera` (ou None)."""
        self.ser.reset_input_buffer()
        self.ser.write(linha.encode() + b"\n")
        buf, fim = b"", time.time() + limite_s
        while time.time() < fim:
            buf += self.ser.read(self.ser.in_waiting or 1)
            if (m := espera.search(buf)) or b"[erro]" in buf:
                return m
        return None

    def run(self):
        while not self.parar:
            try:
                linha, espera, resposta = self.comandos.get_nowait()
                resposta.put(self.comando(linha, espera))
                continue
            except queue.Empty:
                pass
            if not self.ao_vivo:
                time.sleep(0.05)
                continue
            try:
                q = self._quadro()
                with self.lock:
                    self.quadro, self.erro = q, ""
            except (TimeoutError, IOError) as e:
                with self.lock:
                    self.erro = str(e)

    def executar(self, linha, espera=RE_ROI):
        resposta = queue.Queue()
        self.comandos.put((linha, espera, resposta))
        return resposta.get()


def desenhar(quadro, r, pre, leitor, estado):
    """Quadro com a caixa, as fatias (amarelo) e a face de cada uma (azul); embaixo, a entrada 28x28 de
    cada fatia e o dígito lido. Devolve (imagem, leitura)."""
    img = cv2.cvtColor(cv2.resize(quadro, (W * ESC, H * ESC), interpolation=cv2.INTER_NEAREST),
                       cv2.COLOR_GRAY2BGR)
    x0, y0, x1, y1, _ = r
    face, realce = (pre[0], pre[1]), pre[2]
    for sx0, sx1 in fatias(r):
        if sx0 > x0:
            cv2.line(img, (sx0 * ESC, y0 * ESC), (sx0 * ESC, y1 * ESC), (0, 220, 255), 1)
        if face != pn.FACE_PADRAO:
            fx0, fx1 = pn.janela_face(sx0, sx1, face)
            for fx in (fx0 * ESC + 1, fx1 * ESC - 1):
                cv2.line(img, (fx, y0 * ESC + 3), (fx, y1 * ESC - 3), (255, 160, 0), 1)
    cv2.rectangle(img, (x0 * ESC, y0 * ESC), (x1 * ESC - 1, y1 * ESC - 1), (0, 255, 0), 1)

    # Painel de baixo: o que o classificador recebe em cada fatia (ampliado 2x) e o que ele lê
    painel = np.full((2 * D + 80, W * ESC, 3), 30, np.uint8)
    leitura = ""
    for i, (sx0, sx1) in enumerate(fatias(r)):
        entrada = pn.entrada_fatia(quadro, sx0, y0, sx1, y1, face, realce)
        dig = int(np.argmax(leitor.pontuacoes_entrada(entrada)))
        leitura += str(dig)
        x = 10 + i * (2 * D + 8)
        if x + 2 * D <= W * ESC:
            t = cv2.resize(entrada, (2 * D, 2 * D), interpolation=cv2.INTER_NEAREST)
            painel[10:10 + 2 * D, x:x + 2 * D] = cv2.cvtColor(t, cv2.COLOR_GRAY2BGR)
            cv2.putText(painel, str(dig), (x + D - 7, 2 * D + 32), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
    texto = (f"caixa {x0},{y0},{x1},{y1}  N={r[4]}  face {pre[0]}-{pre[1]}%  realce {pn.REALCES[realce]}"
             f"  |  leitura {leitura}")
    cv2.putText(painel, texto, (10, 2 * D + 55), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (230, 230, 230), 1)
    cv2.putText(painel, estado, (10, 2 * D + 74), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (230, 230, 230), 1)
    return np.vstack([img, painel]), leitura


def main():
    # Saída redirecionada num Windows em japonês (cp932) não aceita acentos: troca em vez de quebrar
    sys.stdout.reconfigure(errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--porta", help="porta da ESP32-CAM (padrão: TX_SERIAL_PORT do .env)")
    ap.add_argument("--nome", default="", help="nome dos arquivos salvos (padrão: roi_<data_hora>)")
    ap.add_argument("--saida", default=str(RAIZ / "experimentos" / "hibrido_a_b"),
                    help="pasta do JSON e do PNG (padrão: experimentos/hibrido_a_b)")
    a = ap.parse_args()

    placa = Placa(a.porta or porta_padrao())
    print("Placa pronta.")
    m = placa.comando("ROI")
    roi = [int(v) for v in m.groups()[:5]] if m else [20, 45, 140, 75, 6]
    pre = [int(v) for v in m.groups()[5:]] if m and m.group(6) else [0, 100, 0]
    salva = roi + pre if m else None
    print("ROI na placa:", f"{roi}, face {pre[0]}-{pre[1]} %, realce {pre[2]}" if m
          else "nenhuma (começando com uma caixa padrão)")
    leitor = pn.LeitorB()
    m = placa.comando("GIRO", espera=RE_GIRO)
    giro = (int(m.group(1)), int(m.group(2))) if m else (0, 0)
    nome_giro = dict(ORIENTACOES)
    print("Orientação do quadro:", nome_giro[giro])
    placa.start()

    janela = "Calibrar ROI (USB)"
    cv2.namedWindow(janela)
    arrasto = {}

    def mouse(ev, x, y, flags, _):
        nonlocal roi
        px, py = x // ESC, y // ESC
        if y >= H * ESC:
            return
        if ev == cv2.EVENT_LBUTTONDOWN:
            dentro = roi[0] <= px < roi[2] and roi[1] <= py < roi[3]
            arrasto.update(modo="mover" if dentro else "desenhar", p0=(px, py), r0=list(roi))
        elif ev == cv2.EVENT_MOUSEMOVE and arrasto:
            (ax, ay), r0 = arrasto["p0"], arrasto["r0"]
            if arrasto["modo"] == "mover":
                dx = min(max(px - ax, -r0[0]), W - r0[2])
                dy = min(max(py - ay, -r0[1]), H - r0[3])
                roi = [r0[0] + dx, r0[1] + dy, r0[2] + dx, r0[3] + dy, r0[4]]
            else:
                roi = normalizar([ax, ay, px + 1, py + 1, r0[4]])
        elif ev == cv2.EVENT_LBUTTONUP:
            arrasto.clear()

    cv2.setMouseCallback(janela, mouse)
    ultimo = np.zeros((H, W), np.uint8)
    aviso, aviso_ate = "", 0.0

    while True:
        with placa.lock:
            if placa.quadro is not None:
                ultimo = placa.quadro
            erro = placa.erro
        if time.time() < aviso_ate:
            estado = aviso
        elif erro:
            estado = "erro: " + erro
        else:
            estado = ("AO VIVO" if placa.ao_vivo else "CONGELADO") + "  " + nome_giro[giro] + \
                     ("  (salva na placa)" if roi + pre == salva else "  (nao salva)")
        img, leitura = desenhar(ultimo, roi, pre, leitor, estado)
        cv2.imshow(janela, img)

        k = cv2.waitKeyEx(30)
        if cv2.getWindowProperty(janela, cv2.WND_PROP_VISIBLE) < 1:   # fechou no X
            break
        if k == -1:
            continue
        c = chr(k & 0xFF) if k < 256 else ""
        if k in SETAS:
            dx, dy = SETAS[k]
            dx = min(max(dx, -roi[0]), W - roi[2])
            dy = min(max(dy, -roi[1]), H - roi[3])
            roi = [roi[0] + dx, roi[1] + dy, roi[2] + dx, roi[3] + dy, roi[4]]
        elif c in "adjlwsik":
            i, d = {"a": (2, -1), "d": (2, 1), "j": (0, -1), "l": (0, 1),
                    "w": (3, -1), "s": (3, 1), "i": (1, -1), "k": (1, 1)}[c]
            nova = list(roi)
            nova[i] += d
            roi = normalizar(nova)
        elif c in "+=-_":
            roi = normalizar(roi[:4] + [roi[4] + (1 if c in "+=" else -1)])
        elif c in "zxcv":
            i, d = {"z": (0, -2), "x": (0, 2), "c": (1, -2), "v": (1, 2)}[c]
            novo = list(pre)
            novo[i] += d
            if novo[0] <= novo[1] - 10:          # não deixa a face sumir
                pre = normalizar_pre(*novo)
        elif c == "e":
            pre = normalizar_pre(pre[0], pre[1], not pre[2])
        elif c == " ":
            placa.ao_vivo = not placa.ao_vivo
        elif c == "r":
            seguintes = [o for o, _ in ORIENTACOES]
            novo = seguintes[(seguintes.index(giro) + 1) % len(seguintes)]
            m = placa.executar(f"GIRAR {novo[0]} {novo[1]}", RE_GIRO)
            if m and (int(m.group(1)), int(m.group(2))) == novo:
                # Os dígitos não saíram do lugar: leva a caixa para a posição no quadro novo
                x0, y0, x1, y1, n = roi
                if novo[0] != giro[0]:
                    y0, y1 = H - y1, H - y0
                if novo[1] != giro[1]:
                    x0, x1 = W - x1, W - x0
                roi, giro = normalizar([x0, y0, x1, y1, n]), novo
                salva = None    # a ROI gravada era de outra orientação
                aviso = f"quadro {nome_giro[giro]}: espere o proximo quadro e confira"
            else:
                aviso = "FALHA ao mudar a orientacao na placa"
            aviso_ate = time.time() + 4
        elif c == "g":
            m = placa.executar("SALVAR " + " ".join(map(str, roi + pre)))
            if m and m.group(6) and [int(v) for v in m.groups()] == roi + pre:
                salva = roi + pre
                nome = a.nome or "roi_" + datetime.now().strftime("%Y%m%d_%H%M%S")
                pasta = Path(a.saida)
                pasta.mkdir(parents=True, exist_ok=True)
                dados = {"caixa": roi[:4], "n_digitos": roi[4], "quadro": [W, H], "formato": "GRAYSCALE QQVGA",
                         "fatias": [list(f) for f in fatias(roi)], "face_pct": pre[:2], "realce": pre[2],
                         "vflip": giro[0], "hmirror": giro[1], "leitura_no_pc": leitura, "salva_no_esp32": True,
                         "gerado_em": datetime.now().astimezone().isoformat(timespec="seconds")}
                (pasta / f"{nome}.json").write_text(json.dumps(dados, indent=1), encoding="utf-8")
                cv2.imwrite(str(pasta / f"{nome}.png"), ultimo)
                aviso = f"gravada na placa e salva em {pasta.name}/{nome}.json/.png"
                print(f"ROI {roi}, face {pre[0]}-{pre[1]} %, realce {pre[2]} gravada na placa "
                      f"(leitura no PC: {leitura}); arquivos: {pasta / nome}.json e .png")
            else:
                aviso = "FALHA ao gravar na placa (veja o terminal)"
                print("A placa não confirmou o SALVAR.")
            aviso_ate = time.time() + 4
        elif c == "q" or k == 27:
            break

    placa.parar = True
    placa.join(timeout=8)
    placa.ser.close()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
