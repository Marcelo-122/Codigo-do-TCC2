"""Gráficos de épocas do treino, a partir dos históricos que os scripts de treino gravam em relatorios/.

    python gerar_graficos_treino.py

Lê (os que existirem):
  relatorios/historico_treino_classificador.csv  (treinar_classificador_digitos.py, Fase A)
  relatorios/historico_treino_segmentacao.csv    (pipeline.py)
e grava relatorios/grafico_treino_classificador.png e relatorios/grafico_treino_segmentacao.png.
A Fase B do classificador (5 épocas de fine-tuning) não entra no CSV; ela está em relatorios/treino_classificador.log.
"""
import csv
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

DIRETORIO_ATUAL = os.path.dirname(os.path.abspath(__file__))
DIR_RELATORIOS = os.path.join(DIRETORIO_ATUAL, "relatorios")

COR_TREINO, COR_VAL = "#4C78A8", "#E45756"


def ler(nome):
    caminho = os.path.join(DIR_RELATORIOS, nome)
    if not os.path.exists(caminho):
        return None
    with open(caminho, newline="", encoding="utf-8") as f:
        linhas = list(csv.DictReader(f))
    return {k: [float(l[k]) for l in linhas] for k in linhas[0]} if linhas else None


def painel(ax, epocas, series, titulo, ylabel, melhor=None, ylim=None):
    for rotulo, valores, cor, estilo in series:
        ax.plot(epocas, valores, color=cor, linestyle=estilo, label=rotulo, linewidth=1.6)
    if melhor is not None:
        ax.axvline(melhor, color="#888888", linestyle=":", linewidth=1)
        ax.annotate(f"melhor época: {melhor}", (melhor, ax.get_ylim()[0]), xytext=(-4, 6),
                    textcoords="offset points", color="#555555", fontsize=8, ha="right")
    ax.set_title(titulo, fontsize=10)
    ax.set_xlabel("época")
    ax.set_ylabel(ylabel)
    if ylim:
        ax.set_ylim(*ylim)
    ax.grid(alpha=0.25)
    ax.legend(fontsize=8, frameon=False)


def classificador():
    h = ler("historico_treino_classificador.csv")
    if not h:
        return
    ep = [int(e) + 1 for e in h["epoch"]]
    melhor = min(range(len(ep)), key=lambda i: h["val_loss"][i]) + 1  # EarlyStopping monitora val_loss
    fig, (a, b) = plt.subplots(1, 2, figsize=(11, 4))
    painel(a, ep, [("treino", h["loss"], COR_TREINO, "-"), ("validação (por foto)", h["val_loss"], COR_VAL, "-")],
           "Perda", "loss", melhor)
    painel(b, ep, [("treino (com augmentação)", h["accuracy"], COR_TREINO, "-"),
                   ("validação (por foto)", h["val_accuracy"], COR_VAL, "-")],
           "Acurácia por dígito", "acurácia", melhor, ylim=(0.5, 1.0))
    fig.suptitle("Classificador de dígito: Fase A", fontsize=12)
    fig.tight_layout()
    fig.savefig(os.path.join(DIR_RELATORIOS, "grafico_treino_classificador.png"), dpi=150)
    print("grafico_treino_classificador.png")


def segmentacao():
    h = ler("historico_treino_segmentacao.csv")
    if not h:
        return
    ep = [int(e) + 1 for e in h["epoch"]]
    melhor = max(range(len(ep)), key=lambda i: h["val_dice"][i]) + 1  # EarlyStopping monitora val_dice
    fig, (a, b, c) = plt.subplots(1, 3, figsize=(15, 4))
    painel(a, ep, [("treino", h["loss"], COR_TREINO, "-"), ("validação", h["val_loss"], COR_VAL, "-")],
           "Perda (entropia cruzada + Dice suave)", "loss", melhor)
    painel(b, ep, [("treino", h["dice"], COR_TREINO, "-"), ("validação", h["val_dice"], COR_VAL, "-")],
           "Dice da janela de dígitos", "Dice", melhor, ylim=(0, 1))
    painel(c, ep, [("Dice (validação)", h["val_dice"], COR_VAL, "-"), ("IoU (validação)", h["val_iou"], "#54A24B", "-"),
                   ("acurácia por pixel (validação)", h["val_accuracy"], "#888888", "--")],
           "Por que a acurácia não serve", "valor", melhor, ylim=(0, 1))
    fig.suptitle("Segmentação da janela de dígitos (192×192)", fontsize=12)
    fig.tight_layout()
    fig.savefig(os.path.join(DIR_RELATORIOS, "grafico_treino_segmentacao.png"), dpi=150)
    print("grafico_treino_segmentacao.png")


if __name__ == "__main__":
    classificador()
    segmentacao()
