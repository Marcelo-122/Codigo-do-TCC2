"""Reavalia o modelo ja treinado (modelo_digito.h5 / .tflite) e grava um
relatorio verificavel (RESULTADOS.md + matriz de confusao) com os numeros
reais medidos, em vez de deixar isso so no console do treino."""
import os
import json
import numpy as np
import tensorflow as tf
from tensorflow.keras import layers

DIRETORIO_ATUAL = os.path.dirname(os.path.abspath(__file__))
DIR_DIGITS = os.path.join(DIRETORIO_ATUAL, "dataset", "digits")
DIR_DOMINIO = os.path.join(DIRETORIO_ATUAL, "dataset", "digits_domain")
IMG_SIZE = (28, 28)
SEED = 42
BATCH_SIZE = 128

NORM = layers.Rescaling(1.0 / 255)

print("-> Recarregando o mesmo split de validacao usado no treino (mesma seed)")
# shuffle=True aqui e obrigatorio -- tem que bater com o shuffle usado na
# chamada de "training" em treinar_classificador_digitos.py, senao os dois
# cortes deixam de ser complementares (ver comentario la).
ds_val_raw = tf.keras.utils.image_dataset_from_directory(
    DIR_DIGITS, labels="inferred", label_mode="int", color_mode="grayscale",
    image_size=IMG_SIZE, batch_size=BATCH_SIZE, validation_split=0.15, subset="validation",
    seed=SEED, shuffle=True,
)
classes = ds_val_raw.class_names
ds_val = ds_val_raw.map(lambda x, y: (NORM(x), y)).prefetch(tf.data.AUTOTUNE)

contagens_treino = {c: len(os.listdir(os.path.join(DIR_DIGITS, c))) for c in classes}

# ==========================================
# Avaliacao do modelo FLOAT (.h5)
# ==========================================
print("-> Avaliando modelo_digito.h5 (float)")
modelo_float = tf.keras.models.load_model(os.path.join(DIRETORIO_ATUAL, "modelo_digito.h5"))
loss_f, acc_f = modelo_float.evaluate(ds_val, verbose=0)

# ==========================================
# Avaliacao do modelo INT8 (.tflite) + matriz de confusao
# ==========================================
print("-> Avaliando modelo_digito.tflite (INT8) e montando matriz de confusao")
interpretador = tf.lite.Interpreter(model_path=os.path.join(DIRETORIO_ATUAL, "modelo_digito.tflite"))
interpretador.allocate_tensors()
entrada = interpretador.get_input_details()[0]
saida = interpretador.get_output_details()[0]
escala_in, zero_in = entrada["quantization"]

n_classes = len(classes)
matriz_confusao = np.zeros((n_classes, n_classes), dtype=int)


def prever_int8(imagem_float):
    imagem_int8 = np.round(imagem_float / escala_in + zero_in).astype(np.int8)
    interpretador.set_tensor(entrada["index"], imagem_int8)
    interpretador.invoke()
    return interpretador.get_tensor(saida["index"])[0]


acertos_val, totais_val = 0, 0
for xb, yb in ds_val:
    for img, rot in zip(xb.numpy(), yb.numpy()):
        pred = int(np.argmax(prever_int8(np.expand_dims(img, 0))))
        matriz_confusao[rot, pred] += 1
        acertos_val += int(pred == rot)
        totais_val += 1
acc_int8_val = acertos_val / totais_val

acuracia_por_classe = {
    classes[i]: (matriz_confusao[i, i] / matriz_confusao[i].sum() if matriz_confusao[i].sum() else float("nan"))
    for i in range(n_classes)
}

# ==========================================
# Avaliacao no conjunto de dominio (fotos reais da ESP32CAM)
# ==========================================
tem_dominio = os.path.isdir(DIR_DOMINIO) and any(os.scandir(DIR_DOMINIO))
acc_int8_dominio = None
total_dominio = 0
if tem_dominio:
    print("-> Avaliando no conjunto de dominio (fotos reais da ESP32CAM)")
    ds_dominio_raw = tf.keras.utils.image_dataset_from_directory(
        DIR_DOMINIO, labels="inferred", label_mode="int", color_mode="grayscale",
        image_size=IMG_SIZE, batch_size=8, shuffle=False, seed=SEED,
    )
    mapa = [classes.index(c) for c in ds_dominio_raw.class_names]

    def remapear(x, y):
        tabela = tf.constant(mapa, dtype=tf.int64)
        return x, tf.cast(tf.gather(tabela, y), tf.int32)

    ds_dominio = ds_dominio_raw.map(remapear).map(lambda x, y: (NORM(x), y))
    acertos_d, totais_d = 0, 0
    for xb, yb in ds_dominio:
        for img, rot in zip(xb.numpy(), yb.numpy()):
            pred = int(np.argmax(prever_int8(np.expand_dims(img, 0))))
            acertos_d += int(pred == rot)
            totais_d += 1
    acc_int8_dominio = acertos_d / totais_d
    total_dominio = totais_d

# ==========================================
# Matriz de confusao (imagem)
# ==========================================
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

fig, ax = plt.subplots(figsize=(6, 5))
im = ax.imshow(matriz_confusao, cmap="Blues")
ax.set_xticks(range(n_classes))
ax.set_yticks(range(n_classes))
ax.set_xticklabels(classes)
ax.set_yticklabels(classes)
ax.set_xlabel("Previsto")
ax.set_ylabel("Real")
ax.set_title("Matriz de confusao - validacao (INT8)")
for i in range(n_classes):
    for j in range(n_classes):
        valor = matriz_confusao[i, j]
        if valor > 0:
            cor = "white" if valor > matriz_confusao.max() / 2 else "black"
            ax.text(j, i, str(valor), ha="center", va="center", color=cor, fontsize=7)
fig.colorbar(im, ax=ax, shrink=0.8)
fig.tight_layout()
caminho_matriz = os.path.join(DIRETORIO_ATUAL, "matriz_confusao.png")
fig.savefig(caminho_matriz, dpi=150)
print(f"-> {caminho_matriz} salvo")

# ==========================================
# Grava resultados_treino.json (maquina-legivel) e RESULTADOS.md (humano)
# ==========================================
tam_tflite_kb = os.path.getsize(os.path.join(DIRETORIO_ATUAL, "modelo_digito.tflite")) / 1024
tam_seg_kb = os.path.getsize(os.path.join(DIRETORIO_ATUAL, "modelo_esp32.tflite")) / 1024

resultados = {
    "classes": classes,
    "contagem_por_classe_treino_total": contagens_treino,
    "total_imagens_dataset_digitos": sum(contagens_treino.values()),
    "tamanho_validacao": totais_val,
    "acuracia_float_h5": round(float(acc_f), 4),
    "acuracia_int8_tflite_validacao": round(float(acc_int8_val), 4),
    "acuracia_int8_tflite_dominio_esp32cam": (round(float(acc_int8_dominio), 4) if acc_int8_dominio is not None else None),
    "total_amostras_dominio": total_dominio,
    "acuracia_por_classe_int8_validacao": {k: round(float(v), 4) for k, v in acuracia_por_classe.items()},
    "matriz_confusao_validacao": matriz_confusao.tolist(),
    "parametros_modelo": int(modelo_float.count_params()),
    "tamanho_tflite_kb": round(tam_tflite_kb, 1),
    "tamanho_modelo_segmentacao_kb": round(tam_seg_kb, 1),
}
with open(os.path.join(DIRETORIO_ATUAL, "resultados_treino.json"), "w", encoding="utf-8") as f:
    json.dump(resultados, f, indent=2, ensure_ascii=False)

linhas_classe = "\n".join(
    f"| {c} | {contagens_treino[c]} | {acuracia_por_classe[c]:.2%} |" for c in classes
)

md = f"""# Resultados do classificador de dígitos

Gerado automaticamente por `gerar_relatorio_resultados.py`, reavaliando os arquivos
`modelo_digito.h5` (float) e `modelo_digito.tflite` (INT8) já treinados — **não** re-treina
nada, só mede. Para reproduzir do zero, rode `treinar_classificador_digitos.py` (ver
[README.md](README.md)).

## Resumo

| Métrica | Valor |
|---|---|
| Acurácia — modelo float (`modelo_digito.h5`) | **{acc_f:.2%}** |
| Acurácia — modelo INT8 (`modelo_digito.tflite`), validação | **{acc_int8_val:.2%}** ({acertos_val}/{totais_val}) |
| Acurácia — modelo INT8, fotos reais da ESP32CAM (domínio) | **{f"{acc_int8_dominio:.2%} ({total_dominio} amostras)" if acc_int8_dominio is not None else "N/A"}** |
| Parâmetros do modelo | {modelo_float.count_params():,} |
| Tamanho `modelo_digito.tflite` | {tam_tflite_kb:.1f} KB |
| Tamanho `modelo_esp32.tflite` (segmentação, referência) | {tam_seg_kb:.1f} KB |
| Total de imagens em `dataset/digits/` | {sum(contagens_treino.values()):,} |
| Tamanho da fatia de validação | {totais_val:,} |

## Acurácia por classe (INT8, validação)

| Dígito | Exemplos no dataset | Acurácia |
|---|---|---|
{linhas_classe}

## Matriz de confusão (INT8, validação)

![Matriz de confusão](matriz_confusao.png)

## Como verificar independentemente

1. Clone o repositório e siga o "Como rodar" do [README.md](README.md) (baixa os datasets,
   monta o `dataset/digits/`).
2. Rode `python gerar_relatorio_resultados.py` — ele recalcula tudo acima a partir dos
   arquivos `modelo_digito.h5`/`.tflite` já commitados, sem precisar re-treinar (leva
   segundos/poucos minutos, não os ~20min do treino completo).
3. Os números crus, sem arredondamento, também ficam em `resultados_treino.json`.
"""

with open(os.path.join(DIRETORIO_ATUAL, "RESULTADOS.md"), "w", encoding="utf-8") as f:
    f.write(md)

print("\n-> RESULTADOS.md e resultados_treino.json gerados")
print(f"Acuracia float: {acc_f:.4f} | INT8 validacao: {acc_int8_val:.4f} | INT8 dominio: {acc_int8_dominio}")
