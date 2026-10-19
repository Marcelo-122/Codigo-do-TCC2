"""Mostra, foto a foto, o que o modelo previu pra cada digito das fotos
reais da ESP32CAM (dataset/digits_domain), comparando com o valor real —
pra conferir visualmente em vez de so olhar a acuracia agregada."""
import os
import csv
import glob
import cv2
import numpy as np
import tensorflow as tf
from PIL import Image, ImageDraw, ImageFont

DIRETORIO_ATUAL = os.path.dirname(os.path.abspath(__file__))
DIR_DOMINIO = os.path.join(DIRETORIO_ATUAL, "dataset", "digits_domain")
DIR_FOTOS = os.path.join(DIRETORIO_ATUAL, "Imagens")
LABELS_CSV = os.path.join(DIRETORIO_ATUAL, "dominio_labels.csv")
DIR_OUT = os.path.join(DIRETORIO_ATUAL, "dataset", "predicoes_dominio")

interpretador = tf.lite.Interpreter(model_path=os.path.join(DIRETORIO_ATUAL, "modelos", "modelo_digito.tflite"))
interpretador.allocate_tensors()
entrada = interpretador.get_input_details()[0]
saida = interpretador.get_output_details()[0]
escala_in, zero_in = entrada["quantization"]


def prever_digito(caminho_png):
    img = cv2.imread(caminho_png, cv2.IMREAD_GRAYSCALE)
    img = img.astype(np.float32) / 255.0
    img = np.expand_dims(img, axis=(0, -1))
    img_int8 = np.round(img / escala_in + zero_in).astype(np.int8)
    interpretador.set_tensor(entrada["index"], img_int8)
    interpretador.invoke()
    saida_vals = interpretador.get_tensor(saida["index"])[0]
    return int(np.argmax(saida_vals))


def achar_recortes(prefixo, n_digitos):
    """Acha os N arquivos <prefixo>_<i>.png nas pastas 0-9, na ordem certa."""
    recortes = [None] * n_digitos
    for i in range(n_digitos):
        candidatos = glob.glob(os.path.join(DIR_DOMINIO, "*", f"{prefixo}_{i}.png"))
        if candidatos:
            recortes[i] = candidatos[0]
    return recortes


def montar_figura(nome_foto, caminho_foto, real, previsto, recortes):
    tam_celula = 90
    foto = None
    if caminho_foto and os.path.exists(caminho_foto):
        foto = Image.open(caminho_foto).convert("RGB")
        escala = 260 / foto.height
        foto = foto.resize((int(foto.width * escala), 260))

    largura_total = max((foto.width if foto else 0) + 20, 0) + tam_celula * len(recortes) + 20
    altura_total = max(300, tam_celula + 120)
    fig = Image.new("RGB", (largura_total, altura_total), "white")
    draw = ImageDraw.Draw(fig)

    x = 10
    if foto:
        fig.paste(foto, (x, 20))
        x += foto.width + 20

    try:
        fonte = ImageFont.truetype("arial.ttf", 22)
        fonte_pq = ImageFont.truetype("arial.ttf", 14)
    except OSError:
        fonte = ImageFont.load_default()
        fonte_pq = fonte

    y_celulas = 60
    for i, (caminho_recorte, r, p) in enumerate(zip(recortes, real, previsto)):
        correto = r == p
        cor = (0, 150, 0) if correto else (200, 0, 0)
        if caminho_recorte:
            celula = Image.open(caminho_recorte).convert("L").resize((tam_celula - 10, tam_celula - 10))
            fig.paste(celula, (x + 5, y_celulas))
        draw.rectangle([x, y_celulas - 2, x + tam_celula - 2, y_celulas + tam_celula - 2], outline=cor, width=3)
        draw.text((x + 8, y_celulas + tam_celula), f"real {r}", fill="black", font=fonte_pq)
        draw.text((x + 8, y_celulas + tam_celula + 16), f"prev {p}", fill=cor, font=fonte_pq)
        x += tam_celula

    status = "CORRETO" if real == previsto else "DIVERGIU"
    cor_status = (0, 130, 0) if real == previsto else (190, 0, 0)
    titulo = f"{nome_foto}  |  real: {real}  |  previsto: {previsto}  |  {status}"
    draw.text((10, 2), titulo, fill=cor_status, font=fonte)
    return fig


def main():
    os.makedirs(DIR_OUT, exist_ok=True)
    with open(LABELS_CSV, newline="", encoding="utf-8") as f:
        linhas = list(csv.DictReader(f))

    resumo = []
    for linha in linhas:
        origem, nome, rotulo_real = linha["source"], linha["filename"], linha["label"]
        prefixo = f"{origem}_{os.path.splitext(nome)[0]}"
        recortes = achar_recortes(prefixo, len(rotulo_real))

        previstos = []
        for i, caminho in enumerate(recortes):
            if caminho is None:
                previstos.append("?")
                continue
            previstos.append(str(prever_digito(caminho)))
        rotulo_previsto = "".join(previstos)

        caminho_foto = os.path.join(DIR_FOTOS, nome) if origem == "campo" else None
        fig = montar_figura(nome, caminho_foto, rotulo_real, rotulo_previsto, recortes)
        caminho_saida = os.path.join(DIR_OUT, f"{prefixo}_predicao.png")
        fig.save(caminho_saida)

        acertos_digito = sum(r == p for r, p in zip(rotulo_real, rotulo_previsto))
        resumo.append((nome, rotulo_real, rotulo_previsto, rotulo_real == rotulo_previsto,
                        acertos_digito, len(rotulo_real)))
        print(f"{nome}: real={rotulo_real} previsto={rotulo_previsto} "
              f"({'OK' if rotulo_real == rotulo_previsto else 'DIVERGIU'}, "
              f"{acertos_digito}/{len(rotulo_real)} digitos certos) -> {caminho_saida}")

    total_fotos = len(resumo)
    fotos_100 = sum(1 for r in resumo if r[3])
    total_digitos = sum(r[5] for r in resumo)
    digitos_certos = sum(r[4] for r in resumo)
    print(f"\nResumo: {fotos_100}/{total_fotos} fotos com leitura 100% correta, "
          f"{digitos_certos}/{total_digitos} dígitos individuais corretos")


if __name__ == "__main__":
    main()
