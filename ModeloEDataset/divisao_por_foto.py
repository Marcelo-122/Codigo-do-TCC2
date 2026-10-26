"""Divisão treino/validação dos recortes de dígito feita POR FOTO, não por recorte.

Cada foto de origem gera 5 a 8 recortes (`<foto>_<i>.png`). O `validation_split` do Keras sorteia recorte a
recorte, então recortes da mesma foto caem nos dois lados e a validação fica otimista (a rede já viu o mesmo
medidor, com a mesma luz e o mesmo desgaste). Aqui o sorteio é pelo nome da foto (o nome do recorte sem o
`_<i>.png` final), com semente fixa, e a divisão é gravada em CSV para ser auditável.
"""
import csv
import os

import numpy as np


def dividir_por_foto(dir_digits, seed=42, fracao_val=0.15, caminho_csv=None):
    """Devolve (classes, treino, validacao); cada lista tem tuplas (caminho, indice_da_classe)."""
    classes = sorted(c for c in os.listdir(dir_digits) if os.path.isdir(os.path.join(dir_digits, c)))
    itens = []
    for indice, classe in enumerate(classes):
        pasta = os.path.join(dir_digits, classe)
        for nome in sorted(os.listdir(pasta)):
            if nome.lower().endswith(".png"):
                itens.append((os.path.join(pasta, nome), indice, nome.rsplit("_", 1)[0]))

    fotos = sorted({foto for _, _, foto in itens})
    np.random.default_rng(seed).shuffle(fotos)
    fotos_val = set(fotos[:int(len(fotos) * fracao_val)])

    treino = [(c, i) for c, i, f in itens if f not in fotos_val]
    validacao = [(c, i) for c, i, f in itens if f in fotos_val]

    if caminho_csv:
        with open(caminho_csv, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["foto", "particao"])
            w.writerows((foto, "validacao" if foto in fotos_val else "treino") for foto in sorted(fotos))
    return classes, treino, validacao
