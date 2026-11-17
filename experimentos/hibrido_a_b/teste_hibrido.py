"""Teste híbrido no PC: leitor CTC do Pipeline A sobre os recortes do Pipeline B.

Compara, nos MESMOS recortes da janela de dígitos, estes leitores:
  B_Nverd fatiamento em N partes iguais, com N = nº real de dígitos do gabarito (como o teste
          de imagens novas de B) + classificador de dígito 28x28 (ModeloEDataset). É B no melhor caso.
  B_proj  como B_Nverd, mas cortando pelos vãos da projeção vertical (segment_cells, usado por B
          para montar o dataset); se não achar N células, volta ao fatiamento igual
  B_N8    fatiamento em 8 partes iguais (N fixo, hipótese 5+3 de B)
  B_N6    idem com 6 partes (o N_FATIAS fixo do firmware de B)
  A_orig  CRNN+CTC original (TreinoEModelosOCRNaBorda/Modelos), pré-processamento de treino
  A_sint  CRNN+CTC treinado com visores sintéticos, pré-processamento de treino
  A_sint_sim  o mesmo modelo com o pré-processamento do simulador_extracao_dual.py (preenche com
              a cor do fundo e normaliza o contraste), que difere do usado no treino

e quatro origens de recorte:
  manual      caixa desenhada à mão (só nas fotos do ESP32/Imagens_2)
  gt_blackout o recorte com fundo apagado que o A usou no treino (só Kaggle)
  gt_rect     recorte retificado pela máscara de gabarito, sem apagar o fundo (só Kaggle)
  seg_rect    máscara prevista pela segmentação de B, retificada com minAreaRect
  seg_dev     caixa alinhada aos eixos sobre o quadro 160x120, como no firmware de B

Os conjuntos de fotos são:
  kaggle_heldout_ambos   Kaggle, fora do treino do CTC de A e fora das 195 fotos aceitas por B
  kaggle_heldout_A_viu_B Kaggle, fora do treino do CTC de A mas com dígitos que B viu no treino
  kaggle_treino_A        Kaggle, no treino do CTC de A (só para calibrar o harness)
  novas                  6 fotos de Imagens_2 (4 de referência + 2 do ESP32-CAM)
  dominio_B              3 fotos de campo que B usou no fine-tuning (contaminadas para B)
  manifesto              fotos novas rotuladas por você (--manifesto), ver abaixo

O gabarito do Kaggle vem do nome do arquivo (`value_<inteiro>_<fracao>`). A fração perde zeros à
direita (273.470 vira `273_47`), então o gabarito de 8 dígitos é inteiro com 5 casas + fração
completada à direita com zeros. As comparações são numéricas (zeros à esquerda ignorados), porque
o número de rodas varia entre medidores.

Fotos novas (o que falta para uma comparação justa):
    1. python teste_hibrido.py --gerar-manifesto ../../test_images fotos_para_rotular.csv
       cria uma lista em ordem aleatória, com a coluna `rotulo` vazia;
    2. preencha `rotulo` com os dígitos das rodas pretas como aparecem no medidor, zeros à esquerda
       incluídos (ex.: 046663; use ? no lugar de uma roda parada entre dois números, e a foto fica fora). Rotule do início da lista para baixo: qualquer prefixo é uma amostra
       aleatória. Deixe em branco as que não conseguir ler. `rot_foto` (graus) gira a foto inteira antes de
    tudo, para medidores fotografados de cabeça para baixo: vale quando a orientação da câmera é fixa. As colunas x0,y0,x1,y1 (frações 0-1 da
       foto) e rot (graus) são opcionais e só servem para medir o leitor sem depender da segmentação;
    3. python teste_hibrido.py --manifesto fotos_para_rotular.csv

Uso (Python 3.10 com o ambiente de ModeloEDataset/requirements.txt):
    python teste_hibrido.py [--max-kaggle 250] [--saida resultados]
"""
import argparse
import csv
import math
import os
import random
import re
import sys
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np
import tensorflow as tf

RAIZ = Path(__file__).resolve().parents[2]
DIR_B = RAIZ / "ModeloEDataset"
DIR_A = RAIZ / "TreinoEModelosOCRNaBorda"
sys.path.insert(0, str(DIR_B))
from digitos_comum import rectify_from_mask, segment_cells  # noqa: E402

BLANK = 10
CTC_H, CTC_W = 48, 224
SEG_TAM = 192
CAM_W, CAM_H = 160, 120


# ----------------------------------------------------------------------------
# Modelos TFLite (todos INT8)
# ----------------------------------------------------------------------------
class Tflite:
    def __init__(self, caminho):
        self.it = tf.lite.Interpreter(model_path=str(caminho))
        self.it.allocate_tensors()
        self.i = self.it.get_input_details()[0]
        self.o = self.it.get_output_details()[0]

    def rodar(self, x01):
        """x01: float em [0,1] sem o eixo do lote. Devolve a saída desquantizada."""
        s, z = self.i["quantization"]
        q = np.clip(np.round(x01 / s + z), -128, 127).astype(np.int8)
        self.it.set_tensor(self.i["index"], q[None])
        self.it.invoke()
        bruto = self.it.get_tensor(self.o["index"])[0].astype(np.float32)
        so, zo = self.o["quantization"]
        return (bruto - zo) * so


def carregar_modelos():
    return {
        "seg": Tflite(DIR_B / "modelos" / "modelo_esp32.tflite"),
        "dig": Tflite(DIR_B / "modelos" / "modelo_digito.tflite"),
        "ctc_orig": Tflite(DIR_A / "Modelos" / "modelo_digitos_ctc.tflite"),
        "ctc_sint": Tflite(DIR_A / "Modelos" / "modelo_digitos_ctc_sint.tflite"),
    }


# ----------------------------------------------------------------------------
# Segmentação de B
# ----------------------------------------------------------------------------
def mascara_b(modelos, gray):
    """Máscara 192x192 (bool) prevista pela segmentação de B."""
    pequena = cv2.resize(gray, (SEG_TAM, SEG_TAM), interpolation=cv2.INTER_NEAREST)
    p = modelos["seg"].rodar(pequena.astype(np.float32)[..., None] / 255.0)
    return p[..., 0] > 0.5


def recorte_seg_rect(modelos, bgr):
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    m = mascara_b(modelos, gray)
    if not m.any():
        return None
    grande = cv2.resize(m.astype(np.uint8) * 255, (bgr.shape[1], bgr.shape[0]), interpolation=cv2.INTER_NEAREST)
    tira = rectify_from_mask(bgr, grande)
    return None if tira is None else cv2.cvtColor(tira, cv2.COLOR_BGR2GRAY)


def recorte_seg_dev(modelos, bgr):
    """Reproduz o firmware: quadro 160x120 em cinza, máscara 192x192, caixa alinhada aos eixos."""
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    quadro = cv2.resize(gray, (CAM_W, CAM_H), interpolation=cv2.INTER_AREA)
    m = mascara_b(modelos, quadro)
    ys, xs = np.nonzero(m)
    if xs.size == 0:
        return None
    x0, x1 = xs.min() * CAM_W // SEG_TAM, xs.max() * CAM_W // SEG_TAM
    y0, y1 = ys.min() * CAM_H // SEG_TAM, ys.max() * CAM_H // SEG_TAM
    if x1 - x0 < 4 or y1 - y0 < 4:
        return None
    return quadro[y0:y1 + 1, x0:x1 + 1]


# ----------------------------------------------------------------------------
# Leitores
# ----------------------------------------------------------------------------
def ler_b(modelos, tira, n, projecao=False):
    """Fatiamento em n partes + classificador de dígito (mesmo pré-processamento de B).
    Com projecao=True tenta cortar pelos vãos entre rodas; se não achar n células, usa partes iguais."""
    h, w = tira.shape
    celulas = segment_cells(tira, n) if projecao else None
    if celulas is None:
        celulas = [tira[:, int(w * i / n):int(w * (i + 1) / n)] for i in range(n)]
    saida = []
    for celula in celulas:
        if celula.shape[1] == 0:
            saida.append("?")
            continue
        c28 = cv2.resize(celula, (28, 28), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0
        saida.append(str(int(np.argmax(modelos["dig"].rodar(c28[..., None])))))
    return "".join(saida)


def preparar_treino(tira):
    """Pré-processamento do treinamento-digitos-ctc.py: ajusta à altura 48 e preenche com 0."""
    h, w = tira.shape
    escala = min(CTC_H / h, CTC_W / w)
    nh, nw = max(1, round(h * escala)), max(1, round(w * escala))
    img = cv2.resize(tira.astype(np.float32), (nw, nh), interpolation=cv2.INTER_LINEAR)
    tela = np.zeros((CTC_H, CTC_W), np.float32)
    tela[:nh, :nw] = np.clip(np.round(img), 0, 255)
    return tela / 255.0


def preparar_simulador(tira):
    """Pré-processamento do simulador_extracao_dual.py: preenche com o fundo e normaliza o contraste."""
    h, w = tira.shape
    escala = min(CTC_H / h, CTC_W / w)
    nh, nw = max(1, round(h * escala)), max(1, round(w * escala))
    img = cv2.resize(tira.astype(np.float32), (nw, nh), interpolation=cv2.INTER_LINEAR)
    fundo = float(img[:, -1:].mean())
    tela = np.full((CTC_H, CTC_W), fundo, np.float32)
    tela[:nh, :nw] = img
    tela = np.clip(np.round(tela), 0, 255).astype(np.uint8)
    tela = cv2.normalize(tela, None, 0, 255, cv2.NORM_MINMAX)
    return tela.astype(np.float32) / 255.0


def decodificar_ctc(logits):
    ids = logits.argmax(axis=-1)
    saida, anterior = [], BLANK
    for i in ids:
        if i != BLANK and i != anterior:
            saida.append(str(int(i)))
        anterior = i
    return "".join(saida)


def ler_a(modelos, qual, tira, preparar):
    return decodificar_ctc(modelos[qual].rodar(preparar(tira)[..., None]))


LEITORES = {
    "B_Nverd": lambda m, t, v: ler_b(m, t, len(v)),
    "B_proj": lambda m, t, v: ler_b(m, t, len(v), projecao=True),
    "B_N8": lambda m, t, v: ler_b(m, t, 8),
    "B_N6": lambda m, t, v: ler_b(m, t, 6),
    "A_orig": lambda m, t, v: ler_a(m, "ctc_orig", t, preparar_treino),
    "A_sint": lambda m, t, v: ler_a(m, "ctc_sint", t, preparar_treino),
    "A_sint_sim": lambda m, t, v: ler_a(m, "ctc_sint", t, preparar_simulador),
}


# ----------------------------------------------------------------------------
# Métricas
# ----------------------------------------------------------------------------
def numerico(s):
    return s.lstrip("0") or "0"


def levenshtein(a, b):
    ant = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        atual = [i]
        for j, cb in enumerate(b, 1):
            atual.append(min(ant[j] + 1, atual[j - 1] + 1, ant[j - 1] + (ca != cb)))
        ant = atual
    return ant[-1]


def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    centro = (p + z * z / (2 * n)) / d
    folga = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, centro - folga), min(1.0, centro + folga))


def gabarito_kaggle(nome):
    """Gabarito de 8 dígitos a partir de id_X_value_<inteiro>_<fracao>.jpg (fração completada à direita)."""
    m = re.search(r"value_(\d+)(?:_(\d+))?\.", nome)
    if not m:
        return None
    return m.group(1).zfill(5) + (m.group(2) or "").ljust(3, "0")


# ----------------------------------------------------------------------------
# Conjuntos de fotos
# ----------------------------------------------------------------------------
def ler_gray(caminho):
    dados = np.fromfile(str(caminho), dtype=np.uint8)
    return cv2.imdecode(dados, cv2.IMREAD_COLOR)


def conjuntos_kaggle(max_kaggle, semente):
    """Reproduz a divisão do treinamento-digitos-ctc.py (seed 42, 80/20 pelos rótulos das pastas)."""
    pasta = DIR_A / "dataset" / "visores_blackout"
    por_rotulo = {}
    for p in pasta.iterdir():
        if not p.is_dir():
            continue
        rot = p.name.strip().upper().rstrip("X")
        if not (1 <= len(rot) <= 8) or not rot.isdigit():
            continue
        por_rotulo.setdefault(rot, []).extend(sorted(q for q in p.iterdir() if q.suffix.lower() in (".jpg", ".jpeg", ".png")))
    chaves = sorted(por_rotulo)
    random.seed(42)
    random.shuffle(chaves)
    corte = int(len(chaves) * 0.8)
    treino = [f for r in chaves[:corte] for f in por_rotulo[r]]
    val = [f for r in chaves[corte:] for f in por_rotulo[r]]

    aceitas = set()
    with open(DIR_B / "dataset" / "digits_report.csv", encoding="utf-8") as f:
        for linha in csv.DictReader(f):
            if linha["status"] == "aceita":
                aceitas.add(linha["arquivo"])

    rng = random.Random(semente)

    def amostrar(lista):
        lista = list(lista)
        rng.shuffle(lista)
        return lista[:max_kaggle]

    return {
        "kaggle_heldout_ambos": amostrar(f for f in val if f.name not in aceitas),
        "kaggle_heldout_A_viu_B": amostrar(f for f in val if f.name in aceitas),
        "kaggle_treino_A": amostrar(treino),
    }


def fotos_manuais():
    """Fotos com caixa desenhada à mão. Devolve (grupo, id, rótulo, bgr_foto, tira_manual)."""
    from PIL import Image

    saida = []
    amostras = [
        ("Imagens_2/Imagens_teste_2/20220515025423_T1iyhTBjCi1RCvBVdK-000-00282.1296.jpg", "ref_00282", "00282", (0.28, 0.16, 0.63, 0.30), 0),
        ("Imagens_2/Imagens_teste_2/20221126_01576.jpg", "ref_00399", "00399", (0.26, 0.205, 0.685, 0.355), 0),
        ("Imagens_2/Imagens_teste_2/20221221_01143.jpg", "ref_027535", "027535", (0.255, 0.21, 0.78, 0.335), 0),
        ("Imagens_2/Imagens_teste_2/20221221_01471.jpg", "ref_021235", "021235", (0.255, 0.21, 0.78, 0.335), 0),
        ("Imagens_2/Imagens_teste_2_ESP32/imagem_capturada_144.jpg", "esp32_144", "01613", (395 / 640, 190 / 480, 440 / 640, 375 / 480), 90),
        ("Imagens_2/Imagens_teste_2_ESP32/imagem_capturada_145.jpg", "esp32_145", "01613", (395 / 640, 190 / 480, 440 / 640, 375 / 480), 90),
    ]
    for rel, apelido, rotulo, (fx0, fy0, fx1, fy1), rot in amostras:
        caminho = DIR_B / rel
        if not caminho.exists():
            print(f"[aviso] ausente: {caminho}")
            continue
        im = Image.open(caminho).convert("RGB")
        w, h = im.size
        tira = im.crop((int(fx0 * w), int(fy0 * h), int(fx1 * w), int(fy1 * h)))
        if rot:
            tira = tira.rotate(rot, expand=True)
        bgr = cv2.cvtColor(np.array(im), cv2.COLOR_RGB2BGR)
        saida.append(("novas", apelido, rotulo, bgr, cv2.cvtColor(np.array(tira), cv2.COLOR_RGB2GRAY)))

    campo = {
        "imagem_capturada_15.jpg": ((100, 120, 240, 445), 90, (0, 15, 325, 110), "01080933"),
        "imagem_capturada_16.jpg": ((100, 120, 240, 445), 90, (0, 15, 325, 110), "01080933"),
        "imagem_capturada_22.jpg": ((285, 100, 460, 460), 90, (0, 90, 360, 150), "00127201"),
    }
    for nome, (caixa, ang, fina, rotulo) in campo.items():
        caminho = DIR_B / "Imagens" / nome
        if not caminho.exists():
            print(f"[aviso] ausente: {caminho}")
            continue
        im = Image.open(caminho).convert("RGB")
        rec = im.crop(caixa)
        if ang:
            rec = rec.rotate(ang, expand=True)
        rec = rec.crop(fina)
        bgr = cv2.cvtColor(np.array(im), cv2.COLOR_RGB2BGR)
        saida.append(("dominio_B", nome, rotulo, bgr, cv2.cvtColor(np.array(rec), cv2.COLOR_RGB2GRAY)))
    return saida


def gerar_manifesto(pasta, saida, semente=7):
    arquivos = sorted(p for p in Path(pasta).iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png"))
    random.Random(semente).shuffle(arquivos)
    with open(saida, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["arquivo", "rotulo", "x0", "y0", "x1", "y1", "rot", "rot_foto"])
        for p in arquivos:
            w.writerow([os.path.relpath(p, Path(saida).resolve().parent).replace(os.sep, "/"), "", "", "", "", "", "", ""])
    print(f"{len(arquivos)} fotos em {saida}: preencha a coluna rotulo (do início da lista para baixo).")


def fotos_do_manifesto(caminho):
    """Lê o manifesto. Devolve (grupo, id, rótulo, bgr_foto, tira_manual_ou_None)."""
    from PIL import Image

    base = Path(caminho).resolve().parent
    saida = []
    ambiguas = 0
    with open(caminho, newline="", encoding="utf-8") as f:
        for linha in csv.DictReader(f):
            rotulo = (linha.get("rotulo") or "").strip()
            if not rotulo:
                continue
            if "?" in rotulo:
                ambiguas += 1  # roda no meio da troca: fora da avaliação, como o half-word de B
                continue
            if not rotulo.isdigit():
                print(f"[aviso] rótulo inválido em {linha['arquivo']}: {rotulo!r} (só dígitos, ou ? numa roda ambígua)")
                continue
            p = base / linha["arquivo"]
            if not p.exists():
                print(f"[aviso] ausente: {p}")
                continue
            im = Image.open(p).convert("RGB")
            if (linha.get("rot_foto") or "").strip():
                im = im.rotate(float(linha["rot_foto"]), expand=True)  # câmera de orientação conhecida
            manual = None
            if all((linha.get(k) or "").strip() for k in ("x0", "y0", "x1", "y1")):
                w, h = im.size
                x0, y0, x1, y1 = (float(linha[k]) for k in ("x0", "y0", "x1", "y1"))
                tira = im.crop((int(x0 * w), int(y0 * h), int(x1 * w), int(y1 * h)))
                if (linha.get("rot") or "").strip():
                    tira = tira.rotate(float(linha["rot"]), expand=True)
                manual = cv2.cvtColor(np.array(tira), cv2.COLOR_RGB2GRAY)
            bgr = cv2.cvtColor(np.array(im), cv2.COLOR_RGB2BGR)
            saida.append(("manifesto", Path(linha["arquivo"]).name, rotulo, bgr, manual))
    if ambiguas:
        print(f"   {ambiguas} fotos com ? no rótulo (roda ambígua) ficaram fora da avaliação")
    return saida


# ----------------------------------------------------------------------------
# Execução
# ----------------------------------------------------------------------------
def avaliar_recorte(modelos, grupo, ident, crop, verdade, tira, linhas):
    if tira is None:
        for nome in LEITORES:
            linhas.append(dict(grupo=grupo, id=ident, recorte=crop, leitor=nome, verdade=verdade,
                               previsto="", sem_recorte=1, exato=0, cer=1.0))
        return
    vn = numerico(verdade)
    for nome, ler in LEITORES.items():
        prev = ler(modelos, tira, verdade)
        pn = numerico(prev) if prev else ""
        linhas.append(dict(grupo=grupo, id=ident, recorte=crop, leitor=nome, verdade=verdade,
                           previsto=prev, sem_recorte=0, exato=int(pn == vn),
                           cer=levenshtein(pn, vn) / max(1, len(vn))))


def calibrar_a(modelos, val_files):
    """Sanidade: o CTC original nos recortes de validação reproduzidos deve ficar perto do val_seq_acc de A."""
    rotulo = lambda p: p.parent.name.strip().upper().rstrip("X")
    ok = 0
    for f in val_files:
        tira = cv2.imread(str(f), cv2.IMREAD_GRAYSCALE)
        ok += ler_a(modelos, "ctc_orig", tira, preparar_treino) == rotulo(f)
    return ok / max(1, len(val_files))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--max-kaggle", type=int, default=250, help="máximo de fotos por conjunto do Kaggle")
    ap.add_argument("--semente", type=int, default=1)
    ap.add_argument("--saida", default=str(Path(__file__).parent / "resultados"))
    ap.add_argument("--manifesto", help="CSV com fotos novas rotuladas (ver o início do arquivo)")
    ap.add_argument("--gerar-manifesto", nargs=2, metavar=("PASTA", "CSV"),
                    help="lista as fotos de PASTA em ordem aleatória num CSV para rotular, e sai")
    a = ap.parse_args()
    if a.gerar_manifesto:
        gerar_manifesto(*a.gerar_manifesto)
        return
    os.makedirs(a.saida, exist_ok=True)

    print("-> carregando modelos TFLite...")
    modelos = carregar_modelos()
    linhas = []
    ious = {}

    print("-> conjuntos do Kaggle (divisão de A reproduzida: seed 42, 80/20)...")
    kg = conjuntos_kaggle(a.max_kaggle, a.semente)
    pasta_img = DIR_A / "dataset" / "images"
    pasta_mask = DIR_A / "dataset" / "masks"
    for grupo, arquivos in kg.items():
        print(f"   {grupo}: {len(arquivos)} fotos")
        for k, f in enumerate(arquivos, 1):
            ident = f.name
            verdade = gabarito_kaggle(ident)
            if verdade is None:
                continue
            bgr = ler_gray(pasta_img / ident)
            mask = cv2.imread(str(pasta_mask / ident), cv2.IMREAD_GRAYSCALE)
            gt_bl = cv2.imread(str(f), cv2.IMREAD_GRAYSCALE)
            gt_rect = None
            if bgr is not None and mask is not None:
                t = rectify_from_mask(bgr, cv2.resize(mask, (bgr.shape[1], bgr.shape[0]), interpolation=cv2.INTER_NEAREST))
                gt_rect = None if t is None else cv2.cvtColor(t, cv2.COLOR_BGR2GRAY)
            if bgr is not None and mask is not None:
                g = cv2.resize(mask, (SEG_TAM, SEG_TAM), interpolation=cv2.INTER_AREA) > 127
                pm = mascara_b(modelos, cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY))
                ious.setdefault(grupo, []).append((pm & g).sum() / max(1, (pm | g).sum()))
            avaliar_recorte(modelos, grupo, ident, "gt_blackout", verdade, gt_bl, linhas)
            avaliar_recorte(modelos, grupo, ident, "gt_rect", verdade, gt_rect, linhas)
            avaliar_recorte(modelos, grupo, ident, "seg_rect", verdade,
                            recorte_seg_rect(modelos, bgr) if bgr is not None else None, linhas)
            if k % 50 == 0:
                print(f"      {k}/{len(arquivos)}")

    print("-> fotos manuais (Imagens_2 e domínio de B)...")
    for grupo, ident, verdade, bgr, manual in fotos_manuais():
        avaliar_recorte(modelos, grupo, ident, "manual", verdade, manual, linhas)
        avaliar_recorte(modelos, grupo, ident, "seg_rect", verdade, recorte_seg_rect(modelos, bgr), linhas)
        avaliar_recorte(modelos, grupo, ident, "seg_dev", verdade, recorte_seg_dev(modelos, bgr), linhas)

    if a.manifesto:
        print("-> fotos novas do manifesto...")
        for grupo, ident, verdade, bgr, manual in fotos_do_manifesto(a.manifesto):
            if manual is not None:
                avaliar_recorte(modelos, grupo, ident, "manual", verdade, manual, linhas)
            avaliar_recorte(modelos, grupo, ident, "seg_rect", verdade, recorte_seg_rect(modelos, bgr), linhas)
            avaliar_recorte(modelos, grupo, ident, "seg_dev", verdade, recorte_seg_dev(modelos, bgr), linhas)

    caminho_csv = Path(a.saida) / "leituras.csv"
    with open(caminho_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(linhas[0].keys()))
        w.writeheader()
        w.writerows(linhas)

    # --- resumo ---
    ag = defaultdict(list)
    for l in linhas:
        ag[(l["grupo"], l["recorte"], l["leitor"])].append(l)

    saida_md = ["# Resultado do teste híbrido (gerado por teste_hibrido.py)\n",
                "Leitura exata = número igual ao gabarito, ignorando zeros à esquerda. "
                "IC = intervalo de Wilson de 95%. CER = distância de edição / tamanho do gabarito.\n"]
    for (grupo, crop) in sorted({(g, c) for g, c, _ in ag}):
        extra = ""
        if grupo == "manifesto":
            vs = {x["verdade"] for x in ag[(grupo, crop, "A_orig")]}
            extra = f" ({len(vs)} leituras distintas)"
        saida_md.append(f"\n## {grupo} / recorte `{crop}`{extra}\n")
        saida_md.append("| Leitor | n | sem recorte | leitura exata | IC 95% | CER médio |")
        saida_md.append("|---|---|---|---|---|---|")
        for leitor in LEITORES:
            L = ag[(grupo, crop, leitor)]
            n = len(L)
            sem = sum(x["sem_recorte"] for x in L)
            k = sum(x["exato"] for x in L)
            lo, hi = wilson(k, n)
            cer = sum(x["cer"] for x in L) / max(1, n)
            saida_md.append(f"| {leitor} | {n} | {sem} | {k} ({k / max(1, n):.0%}) | {lo:.0%}–{hi:.0%} | {cer:.2f} |")
    saida_md.append("\n## IoU da máscara prevista pela segmentação de B contra a máscara de gabarito\n")
    saida_md.append("| Conjunto | n | IoU mediano | IoU médio | fotos com IoU > 0,5 |")
    saida_md.append("|---|---|---|---|---|")
    for grupo, v in ious.items():
        v = np.array(v)
        saida_md.append(f"| {grupo} | {len(v)} | {np.median(v):.2f} | {v.mean():.2f} | {(v > 0.5).sum()} ({(v > 0.5).mean():.0%}) |")
    texto = "\n".join(saida_md) + "\n"
    (Path(a.saida) / "resumo.md").write_text(texto, encoding="utf-8")
    print("\n" + texto)

    cal = calibrar_a(modelos, [f for f in kg["kaggle_heldout_ambos"] + kg["kaggle_heldout_A_viu_B"]][:200])
    print(f"[calibração] CTC original, string exata à maneira de A, validação reproduzida: {cal:.1%} "
          f"(val_seq_acc registrado por A no fim do QAT: 37,9%)")
    print(f"-> {caminho_csv}")


if __name__ == "__main__":
    main()
