"""Comparacao PAREADA do classificador em ponto flutuante (modelo_digito.h5) e em INT8
(modelo_digito.tflite) nos mesmos recortes de validacao (hipotese H1).

O gerar_relatorio_resultados.py mede as duas acuracias separadamente (95,46 % e 95,38 %).
Como os recortes sao os mesmos, a pergunta certa e se os DOIS modelos erram recortes
diferentes o bastante para a diferenca nao ser acaso: teste exato de McNemar sobre os pares
discordantes (b = so o float acerta, c = so o INT8 acerta).

- Divisao: a mesma do treino (divisao_por_foto, seed 42, 15 % das fotos na validacao).
- Float: inferencia em numpy com os pesos lidos do .h5 por h5py (a arquitetura e a da
  tabela do treinar_classificador_digitos.py), para nao depender do TensorFlow. Reproduz os
  7.043 acertos (95,46 %) do relatorio.
- INT8: LiteRT (ai-edge-litert) ou, se nao estiver instalado, tf.lite, com os kernels de
  referencia (BUILTIN_REF). Reproduz os 7.037 acertos (95,38 %). Com kernels otimizados
  (XNNPACK ligado ou, no ai-edge-litert 2.3.0, ate BUILTIN_WITHOUT_DEFAULT_DELEGATES) o mesmo
  arquivo acerta 7.040: a troca de kernels mexe no resultado na mesma escala que a quantizacao.

  python comparar_float_int8.py          (na pasta ModeloEDataset, com dataset/digits montado)

Resultado em 2026-11-08: predicoes iguais em 99,62 % dos recortes; b = 14, c = 8;
McNemar exato p = 0,286. Grava relatorios/comparacao_float_int8.json, com o F1 por digito e o
macro-F1 das duas versoes (f1_por_classe, acrescentado em 2026-11-20).
"""
import json
import os
from math import comb

import cv2
import h5py
import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

from divisao_por_foto import dividir_por_foto

AQUI = os.path.dirname(os.path.abspath(__file__))
DIR_DIGITS = os.path.join(AQUI, "dataset", "digits")
DIR_MODELOS = os.path.join(AQUI, "modelos")
SAIDA = os.path.join(AQUI, "relatorios", "comparacao_float_int8.json")


def interpretador_sem_xnnpack(caminho):
    try:
        from ai_edge_litert.interpreter import Interpreter, OpResolverType
    except ImportError:
        import tensorflow as tf
        Interpreter, OpResolverType = tf.lite.Interpreter, tf.lite.experimental.OpResolverType
    # Kernels de referência (BUILTIN_REF): dão os 7.037 acertos em qualquer versão. No ai-edge-litert 2.3.0 o
    # BUILTIN_WITHOUT_DEFAULT_DELEGATES ainda usa kernels otimizados e dá 7.040 (o mesmo que com o XNNPACK);
    # o resultado de 2026-11-08 foi obtido com uma versão em que essa opção caía nos kernels de referência.
    it = Interpreter(model_path=caminho,
                     experimental_op_resolver_type=OpResolverType.BUILTIN_REF)
    it.allocate_tensors()
    return it


def rede_float(pesos):
    w = lambda n: (pesos[n][n]["kernel"][()], pesos[n][n]["bias"][()])

    def conv(x, nome):  # 3x3, padding same, stride 1, ReLU
        k, b = w(nome)
        janelas = sliding_window_view(np.pad(x, ((0, 0), (1, 1), (1, 1), (0, 0))), (3, 3), axis=(1, 2))
        return np.maximum(np.einsum("nhwcij,ijco->nhwo", janelas, k, optimize=True) + b, 0)

    def pool(x):  # max pooling 2x2, padding valid
        n, h, l, c = x.shape
        return x[:, :h // 2 * 2, :l // 2 * 2].reshape(n, h // 2, 2, l // 2, 2, c).max(axis=(2, 4))

    def prever(x):
        x = pool(conv(conv(x, "conv2d"), "conv2d_1"))
        x = pool(conv(conv(x, "conv2d_2"), "conv2d_3"))
        x = pool(conv(x, "conv2d_4")).reshape(len(x), -1)
        k, b = w("dense")
        x = np.maximum(x @ k + b, 0)
        k, b = w("dense_1")
        return (x @ k + b).argmax(1)  # softmax nao muda o argmax
    return prever


def mcnemar_exato(b, c):
    n = b + c
    return min(1.0, 2 * sum(comb(n, i) for i in range(min(b, c) + 1)) / 2 ** n) if n else 1.0


def f1_por_classe(y, p):
    """F1 de cada dígito (um contra os outros) e as médias, como na Metodologia:
    F1 = 2*VP / (2*VP + FP + FN). A macro-média usa as classes que aparecem no gabarito OU nas
    predições (convenção do scikit-learn): um dígito previsto que nunca aparece entra com F1 = 0.
    A média ponderada pesa cada classe pelo seu suporte (quantos recortes reais ela tem)."""
    y, p = np.asarray(y), np.asarray(p)
    classes = sorted(set(y.tolist()) | set(p.tolist()))
    por_classe, f1s, pesos = {}, [], []
    for c in classes:
        vp = int(np.sum((p == c) & (y == c)))
        fp = int(np.sum((p == c) & (y != c)))
        fn = int(np.sum((p != c) & (y == c)))
        f1 = 2 * vp / (2 * vp + fp + fn)
        por_classe[str(c)] = {"suporte": vp + fn, "vp": vp, "fp": fp, "fn": fn, "f1": round(f1, 4)}
        f1s.append(f1)
        pesos.append(vp + fn)
    return {"f1_macro": round(float(np.mean(f1s)), 4),
            "f1_ponderado": round(float(np.average(f1s, weights=pesos)), 4) if sum(pesos) else None,
            "classes": len(classes), "por_classe": por_classe}


def main():
    _, _, validacao = dividir_por_foto(DIR_DIGITS, seed=42, fracao_val=0.15)
    x = np.stack([cv2.imread(c, cv2.IMREAD_GRAYSCALE) for c, _ in validacao]).astype(np.float32)[..., None] / 255.0
    y = np.array([r for _, r in validacao])
    print(f"-> {len(y)} recortes de validacao")

    with h5py.File(os.path.join(DIR_MODELOS, "modelo_digito.h5"), "r") as f:
        prever = rede_float(f["model_weights"])
        p_float = np.concatenate([prever(x[i:i + 512]) for i in range(0, len(x), 512)])

    it = interpretador_sem_xnnpack(os.path.join(DIR_MODELOS, "modelo_digito.tflite"))
    entrada, saida = it.get_input_details()[0], it.get_output_details()[0]
    escala, zero = entrada["quantization"]
    p_int8 = []
    for img in x:
        it.set_tensor(entrada["index"], np.round(img[None] / escala + zero).astype(np.int8))
        it.invoke()
        p_int8.append(int(np.argmax(it.get_tensor(saida["index"])[0])))
    p_int8 = np.array(p_int8)

    certo_f, certo_q = p_float == y, p_int8 == y
    b, c = int(np.sum(certo_f & ~certo_q)), int(np.sum(~certo_f & certo_q))
    r = {
        "recortes": int(len(y)),
        "acertos_float": int(certo_f.sum()), "acuracia_float": round(float(certo_f.mean()), 6),
        "acertos_int8": int(certo_q.sum()), "acuracia_int8": round(float(certo_q.mean()), 6),
        "predicoes_iguais": round(float(np.mean(p_float == p_int8)), 6),
        "so_float_acerta": b, "so_int8_acerta": c,
        "mcnemar_exato_p": round(mcnemar_exato(b, c), 4),
        "f1_float": f1_por_classe(y, p_float),
        "f1_int8": f1_por_classe(y, p_int8),
    }
    for k, v in r.items():
        if k.startswith("f1_"):
            v = {c: d["f1"] for c, d in v["por_classe"].items()} | {"macro": v["f1_macro"]}
        print(f"   {k}: {v}")
    with open(SAIDA, "w", encoding="utf-8") as f:
        json.dump(r, f, indent=2)
    print(f"-> {SAIDA}")


if __name__ == "__main__":
    main()
