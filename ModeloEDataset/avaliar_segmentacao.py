"""Dice/IoU de um modelo de segmentação .tflite (INT8) no conjunto de teste de `pipeline.py`.

O teste é o mesmo de `relatorios/split_segmentacao.csv` (semente 42, 15 % das fotos do Kaggle). Serve para medir
outro modelo no mesmo teste, por exemplo o anterior: `git show <commit>:ModeloEDataset/modelos/modelo_esp32.tflite > antigo.tflite`.
Atenção: modelos treinados antes de existir esse split podem ter visto parte do teste no treino.

    python avaliar_segmentacao.py [modelo.tflite]      (padrão: modelos/modelo_esp32.tflite)
"""
import os
import sys

import numpy as np
import tensorflow as tf
from tensorflow.keras.utils import img_to_array, load_img

DIRETORIO_ATUAL = os.path.dirname(os.path.abspath(__file__))
DIR_DADOS = os.path.join(DIRETORIO_ATUAL, "dataset")
IMG_SIZE = (192, 192)
SEED = 42
FRACAO_TESTE = 0.15  # igual a pipeline.py

caminho = sys.argv[1] if len(sys.argv) > 1 else os.path.join(DIRETORIO_ATUAL, "modelos", "modelo_esp32.tflite")
nomes = [f for f in sorted(os.listdir(os.path.join(DIR_DADOS, "images"))) if f.endswith((".png", ".jpg", ".jpeg"))]
idx_teste = np.random.default_rng(SEED).permutation(len(nomes))[:int(len(nomes) * FRACAO_TESTE)]

interp = tf.lite.Interpreter(model_path=caminho)
interp.allocate_tensors()
entrada, saida = interp.get_input_details()[0], interp.get_output_details()[0]
escala, zp = entrada["quantization"]

dices, ious, vazias = [], [], 0
for i in idx_teste:
    x = img_to_array(load_img(os.path.join(DIR_DADOS, "images", nomes[i]), color_mode="grayscale", target_size=IMG_SIZE)) / 255.0
    y = img_to_array(load_img(os.path.join(DIR_DADOS, "masks", nomes[i]), color_mode="grayscale", target_size=IMG_SIZE)) / 255.0 > 0.5
    interp.set_tensor(entrada["index"], np.clip(np.round(x / escala + zp), -128, 127).astype(np.int8)[np.newaxis])
    interp.invoke()
    p = interp.get_tensor(saida["index"])[0] > 0  # mesmo limiar do firmware
    vazias += int(not p.any())
    inter = np.logical_and(p, y).sum()
    soma = p.sum() + y.sum()
    dices.append(2 * inter / soma if soma else 1.0)
    ious.append(inter / (soma - inter) if soma - inter else 1.0)

print(f"{os.path.basename(caminho)}: {len(idx_teste)} fotos de teste, Dice {np.mean(dices):.4f}, IoU {np.mean(ious):.4f}, "
      f"máscaras vazias {vazias}")
