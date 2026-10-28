"""
Leitura de hidrometro no PC com a janela dos digitos marcada a mao (caixa manual),
sem ESP32 e sem modelo de segmentacao. Usado na conferencia com a calibracao
manual do autor (calibracao_manual/caixas_esp32_exemplo.json; ver ocr/README.md).

Informa-se ONDE estao os digitos (caixa x0,y0,x1,y1 na foto, e uma rotacao
se a foto estiver girada); o script recorta, fatia em N celulas de largura
igual e o classificador (modelos/modelo_digito.h5) le cada digito:

    foto + caixa  ->  recorte (+ rotacao)  ->  N celulas  ->  "00282"

Autocontido: so depende de numpy, opencv e do modelo em modelos/; o .h5 pede
tensorflow e o .tflite roda com tensorflow ou com ai-edge-litert (ocr/requirements.txt). Nao importa nenhum outro script do projeto.

Exemplos:
    python ler_com_caixa_manual.py foto.jpg --caixa 355,180,415,340 --rotacao 90 --n-digitos 5
    python ler_com_caixa_manual.py recorte.png --n-digitos 6            # ja e so a janela de digitos
    python ler_com_caixa_manual.py calibracao_manual --caixas calibracao_manual/caixas_esp32_exemplo.json --modelo-digito modelos/modelo_digito.tflite

caixas.json (uma entrada por nome de arquivo; "real" e opcional e so serve
para conferir o acerto):
    {"foto1.jpg": {"caixa": [355,180,415,340], "rotacao": 90, "n_digitos": 5, "real": "00282"}}
("caixa_final" tambem e opcional: recorte extra, em coordenadas da imagem ja girada,
para apertar em volta dos digitos)

Como biblioteca:
    from ler_com_caixa_manual import LeitorDigitos
    r = LeitorDigitos().ler(imagem_bgr, n_digitos=5, caixa=(355,180,415,340), rotacao=90)
    r["leitura"], r["confianca_min"]
"""
import argparse
import json
import os
import sys

import cv2
import numpy as np

DIRETORIO_ATUAL = os.path.dirname(os.path.abspath(__file__))
MODELO_DIGITO_PADRAO = os.path.join(DIRETORIO_ATUAL, "modelos", "modelo_digito.h5")

DIGITO_SIZE = (28, 28)
EXTENSOES = (".png", ".jpg", ".jpeg", ".bmp")


def imread_unicode(caminho):
    """cv2.imread falha com acentos no Windows; decodifica os bytes na mao."""
    dados = np.fromfile(caminho, dtype=np.uint8)
    if dados.size == 0:
        return None
    return cv2.imdecode(dados, cv2.IMREAD_COLOR)


def rotacionar(img, graus):
    """Gira `graus` no sentido anti-horario, ampliando a tela pra nao cortar."""
    graus = graus % 360
    if graus == 0:
        return img
    if graus == 90:
        return cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)
    if graus == 180:
        return cv2.rotate(img, cv2.ROTATE_180)
    if graus == 270:
        return cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
    h, w = img.shape[:2]
    M = cv2.getRotationMatrix2D((w / 2, h / 2), graus, 1.0)
    cos, sin = abs(M[0, 0]), abs(M[0, 1])
    nw, nh = int(h * sin + w * cos), int(h * cos + w * sin)
    M[0, 2] += nw / 2 - w / 2
    M[1, 2] += nh / 2 - h / 2
    return cv2.warpAffine(img, M, (nw, nh), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)


def _cortar(img, caixa):
    x0, y0, x1, y1 = (int(v) for v in caixa)
    h, w = img.shape[:2]
    x0, y0, x1, y1 = max(0, x0), max(0, y0), min(w, x1), min(h, y1)
    if x1 <= x0 or y1 <= y0:
        raise ValueError(f"caixa fora da imagem ({w}x{h}): {caixa}")
    return img[y0:y1, x0:x1]


def recortar(img, caixa=None, rotacao=0, caixa_final=None):
    """Recorta `caixa` (x0,y0,x1,y1, na foto original), gira `rotacao` graus e,
    se informado, recorta `caixa_final` (coordenadas da imagem ja girada) pra
    apertar em volta dos digitos. Sem nada disso, usa a imagem toda."""
    if caixa is not None:
        img = _cortar(img, caixa)
    img = rotacionar(img, rotacao)
    if caixa_final is not None:
        img = _cortar(img, caixa_final)
    return img


def fatiar_igual(tira, n):
    cinza = cv2.cvtColor(tira, cv2.COLOR_BGR2GRAY) if tira.ndim == 3 else tira
    w = cinza.shape[1]
    return [cinza[:, int(w * i / n):int(w * (i + 1) / n)] for i in range(n)]


class LeitorDigitos:
    """Classificador de digito (.h5 float, ou .tflite INT8 igual ao do ESP32)."""

    def __init__(self, caminho=MODELO_DIGITO_PADRAO):
        if not os.path.exists(caminho):
            raise FileNotFoundError(f"Modelo nao encontrado: {caminho}")
        self._tflite = caminho.lower().endswith(".tflite")
        if self._tflite:
            try:
                from ai_edge_litert.interpreter import Interpreter
            except ImportError:
                import tensorflow as tf
                Interpreter = tf.lite.Interpreter
            self._interp = Interpreter(model_path=caminho)
            self._interp.allocate_tensors()
            self._in = self._interp.get_input_details()[0]
            self._out = self._interp.get_output_details()[0]
        else:
            import tensorflow as tf
            self._keras = tf.keras.models.load_model(caminho, compile=False)

    def _prever(self, lote):
        if not self._tflite:
            return self._keras.predict(lote, verbose=0)
        esc_in, zp_in = self._in["quantization"]
        esc_out, zp_out = self._out["quantization"]
        info = np.iinfo(self._in["dtype"])
        saidas = []
        for amostra in lote:
            x = np.clip(np.round(amostra[np.newaxis] / esc_in + zp_in), info.min, info.max).astype(self._in["dtype"])
            self._interp.set_tensor(self._in["index"], x)
            self._interp.invoke()
            y = self._interp.get_tensor(self._out["index"])[0].astype(np.float32)
            saidas.append((y - zp_out) * esc_out)
        return np.stack(saidas)

    def ler(self, imagem_bgr, n_digitos, caixa=None, rotacao=0, caixa_final=None):
        """dict com: leitura (str), confianca_por_digito, confianca_min, tira (BGR recortada)."""
        tira = recortar(imagem_bgr, caixa, rotacao, caixa_final)
        celulas = fatiar_igual(tira, n_digitos)
        lote = np.stack([
            cv2.resize(c, DIGITO_SIZE, interpolation=cv2.INTER_AREA).astype(np.float32)[..., np.newaxis] / 255.0
            for c in celulas
        ])
        probs = self._prever(lote)
        confs = probs.max(axis=1)
        return {
            "leitura": "".join(str(int(d)) for d in probs.argmax(axis=1)),
            "confianca_por_digito": [round(float(c), 4) for c in confs],
            "confianca_min": round(float(confs.min()), 4),
            "tira": tira,
            "celulas": celulas,
        }


def salvar_debug(r, nome, real, destino_png):
    """Recorte + cada celula com o digito previsto embaixo (verde = certo, vermelho = errado)."""
    lado = 96
    previsto = r["leitura"]
    colunas = []
    for i, cel in enumerate(r["celulas"]):
        tile = cv2.cvtColor(cv2.resize(cel, (lado, lado), interpolation=cv2.INTER_AREA), cv2.COLOR_GRAY2BGR)
        cor = (60, 60, 60)
        if real is not None:
            cor = (0, 150, 0) if previsto[i] == real[i] else (0, 0, 220)
        tile = cv2.copyMakeBorder(tile, 3, 3, 3, 3, cv2.BORDER_CONSTANT, value=cor)
        rodape = np.full((30, tile.shape[1], 3), 255, np.uint8)
        cv2.putText(rodape, previsto[i], (tile.shape[1] // 2 - 8, 23), cv2.FONT_HERSHEY_SIMPLEX, 0.8, cor, 2)
        colunas.append(np.vstack([tile, rodape]))
    faixa = np.hstack(colunas)

    tira = r["tira"]
    esc = min(3.0, faixa.shape[1] / tira.shape[1])
    tira = cv2.resize(tira, None, fx=esc, fy=esc, interpolation=cv2.INTER_CUBIC)
    larg = max(faixa.shape[1], tira.shape[1], 420)
    titulo = np.full((34, larg, 3), 255, np.uint8)
    txt = f"{nome}  previsto: {previsto}" + (f"  real: {real}" if real else "")
    cv2.putText(titulo, txt, (6, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 1)

    def pad(a):
        return cv2.copyMakeBorder(a, 0, 0, 0, larg - a.shape[1], cv2.BORDER_CONSTANT, value=(255, 255, 255))

    cv2.imencode(".png", np.vstack([pad(titulo), pad(tira), pad(faixa)]))[1].tofile(destino_png)


def main():
    ap = argparse.ArgumentParser(description="Le o valor de um hidrometro, sem ESP32 (caixa dos digitos informada por voce).")
    ap.add_argument("entrada", help="arquivo de imagem ou pasta com imagens")
    ap.add_argument("--n-digitos", type=int, default=None, help="quantas rodinhas de digito o medidor tem")
    ap.add_argument("--caixa", help="x0,y0,x1,y1 da janela de digitos na foto (sem isso, usa a imagem toda)")
    ap.add_argument("--rotacao", type=float, default=0, help="graus anti-horarios aplicados ao recorte (padrao 0)")
    ap.add_argument("--caixas", help="JSON com caixa/rotacao/n_digitos/real por arquivo (ver cabecalho do script)")
    ap.add_argument("--modelo-digito", default=MODELO_DIGITO_PADRAO,
                    help=".h5 (float, mais preciso) ou .tflite (INT8, igual ao do ESP32)")
    ap.add_argument("--json", help="grava os resultados neste arquivo JSON")
    ap.add_argument("--debug-dir", help="salva uma imagem anotada por foto nesta pasta")
    ap.add_argument("--confianca-minima", type=float, default=0.80,
                    help="abaixo disso a leitura e marcada como duvidosa (padrao: 0.80)")
    args = ap.parse_args()

    manifesto = {}
    if args.caixas:
        with open(args.caixas, encoding="utf-8") as f:
            manifesto = json.load(f)

    if os.path.isdir(args.entrada):
        arquivos = sorted(os.path.join(args.entrada, f) for f in os.listdir(args.entrada)
                          if f.lower().endswith(EXTENSOES))
        if manifesto:
            arquivos = [a for a in arquivos if os.path.basename(a) in manifesto]
    else:
        arquivos = [args.entrada]
    if not arquivos:
        sys.exit(f"Nenhuma imagem para processar em {args.entrada}")
    if args.debug_dir:
        os.makedirs(args.debug_dir, exist_ok=True)

    caixa_global = [float(v) for v in args.caixa.split(",")] if args.caixa else None
    leitor = LeitorDigitos(args.modelo_digito)

    saida, certas, total_dig, dig_certos, com_real = [], 0, 0, 0, 0
    for caminho in arquivos:
        nome = os.path.basename(caminho)
        cfg = manifesto.get(nome, {})
        n = cfg.get("n_digitos", args.n_digitos)
        if n is None:
            sys.exit(f"{nome}: informe --n-digitos (ou n_digitos no JSON)")
        img = imread_unicode(caminho)
        if img is None:
            print(f"{nome}: nao consegui abrir a imagem")
            continue

        r = leitor.ler(img, n, cfg.get("caixa", caixa_global), cfg.get("rotacao", args.rotacao),
                       cfg.get("caixa_final"))
        real = cfg.get("real")
        duvidosa = r["confianca_min"] < args.confianca_minima
        linha = f"{nome}: {r['leitura']}  (confianca minima {r['confianca_min']:.2f})"
        if real:
            com_real += 1
            ok = r["leitura"] == real
            certas += ok
            acertos = sum(a == b for a, b in zip(r["leitura"], real))
            dig_certos, total_dig = dig_certos + acertos, total_dig + len(real)
            linha += f"  real {real}  {'OK' if ok else f'ERRO ({acertos}/{len(real)} digitos)'}"
        print(linha + ("  <- DUVIDOSA" if duvidosa else ""))

        if args.debug_dir:
            salvar_debug(r, nome, real, os.path.join(args.debug_dir, os.path.splitext(nome)[0] + "_leitura.png"))
        saida.append({"arquivo": nome, "leitura": r["leitura"], "real": real,
                      "confianca_por_digito": r["confianca_por_digito"],
                      "confianca_min": r["confianca_min"], "duvidosa": duvidosa})

    if com_real:
        print(f"\nResumo: {certas}/{com_real} leituras completas certas | {dig_certos}/{total_dig} digitos certos")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(saida, f, ensure_ascii=False, indent=2)
        print(f"-> {args.json}")


if __name__ == "__main__":
    main()
