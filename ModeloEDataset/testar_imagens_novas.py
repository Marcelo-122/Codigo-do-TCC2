"""Teste com imagens totalmente novas (Imagens_2/), nunca usadas em nenhuma
etapa do treino/fine-tuning -- nem do Kaggle, nem do Dryad, nem das fotos de
dominio anteriores. Caixas de recorte calibradas manualmente (mesma tecnica
usada no resto do projeto); gera comparacao visual real-vs-previsto por foto
e um resumo em TESTE_IMAGENS_NOVAS.md."""
import os
import cv2
import numpy as np
import tensorflow as tf
from PIL import Image, ImageDraw, ImageFont

DIRETORIO_ATUAL = os.path.dirname(os.path.abspath(__file__))
DIR_OUT = os.path.join(DIRETORIO_ATUAL, "dataset", "teste_imagens_novas")
os.makedirs(DIR_OUT, exist_ok=True)

# (caminho, apelido_curto, rotulo_real, caixa_fracionaria(x0,y0,x1,y1), rotacao_graus, categoria)
# apelido_curto e usado no nome do arquivo de saida (os nomes originais de
# Imagens_2/Imagens_teste_2/ sao hashes longos que estouram o limite de
# caminho do Windows quando combinados com a pasta de saida).
# Nota: varias imagens de Imagens_2/ (incluindo as 2 da ESP32CAM real e 1
# outra de referencia) foram descartadas desta amostra porque a janela de
# digitos estava rotacionada demais/fora do alcance pra calibrar a caixa de
# recorte manualmente em tempo razoavel -- mesmo criterio de "descartar em
# vez de arriscar" usado no resto do projeto, aplicado aqui a escolha da
# amostra de teste.
AMOSTRAS = [
    ("Imagens_2/Imagens_teste_2/20220515025423_T1iyhTBjCi1RCvBVdK-000-00282.1296.jpg",
     "ref_00282", "00282", (0.28, 0.16, 0.63, 0.30), 0, "referencia_limpa"),
    ("Imagens_2/Imagens_teste_2/20221126_01576.jpg",
     "ref_00399", "00399", (0.26, 0.205, 0.685, 0.355), 0, "referencia_limpa"),
    # 20221221_00283.jpg ("00764") ficou de fora: a janela de digitos nessa
    # foto especifica segue uma leve curva/inclinacao ao longo do mostrador
    # que o corte + fatiamento em largura igual nao da conta de alinhar
    # direito (cada celula pega pedaco de 2 digitos vizinhos) -- descartada
    # em vez de reportar um numero que na verdade mede erro de recorte, nao
    # erro do modelo.
    ("Imagens_2/Imagens_teste_2/20221221_01143.jpg",
     "ref_027535", "027535", (0.255, 0.21, 0.78, 0.335), 0, "referencia_limpa"),
    ("Imagens_2/Imagens_teste_2/20221221_01471.jpg",
     "ref_021235", "021235", (0.255, 0.21, 0.78, 0.335), 0, "referencia_limpa"),
]

interpretador = tf.lite.Interpreter(model_path=os.path.join(DIRETORIO_ATUAL, "modelo_digito.tflite"))
interpretador.allocate_tensors()
entrada = interpretador.get_input_details()[0]
saida = interpretador.get_output_details()[0]
escala_in, zero_in = entrada["quantization"]


def prever_digito(celula_gray_28x28):
    img = celula_gray_28x28.astype(np.float32) / 255.0
    img = np.expand_dims(img, axis=(0, -1))
    img_int8 = np.round(img / escala_in + zero_in).astype(np.int8)
    interpretador.set_tensor(entrada["index"], img_int8)
    interpretador.invoke()
    return int(np.argmax(interpretador.get_tensor(saida["index"])[0]))


def montar_figura(nome, foto_original, celulas, real, previsto):
    tam_celula = 90
    foto = foto_original.copy()
    escala = 260 / foto.height
    foto = foto.resize((int(foto.width * escala), 260))

    largura_total = foto.width + 20 + tam_celula * len(celulas) + 20
    altura_total = max(300, tam_celula + 120)
    fig = Image.new("RGB", (largura_total, altura_total), "white")
    draw = ImageDraw.Draw(fig)
    fig.paste(foto, (10, 20))
    x = foto.width + 30

    try:
        fonte = ImageFont.truetype("arial.ttf", 20)
        fonte_pq = ImageFont.truetype("arial.ttf", 14)
    except OSError:
        fonte = ImageFont.load_default()
        fonte_pq = fonte

    y_celulas = 60
    for celula, r, p in zip(celulas, real, previsto):
        correto = r == p
        cor = (0, 150, 0) if correto else (200, 0, 0)
        celula_img = Image.fromarray(celula).resize((tam_celula - 10, tam_celula - 10))
        fig.paste(celula_img, (x + 5, y_celulas))
        draw.rectangle([x, y_celulas - 2, x + tam_celula - 2, y_celulas + tam_celula - 2], outline=cor, width=3)
        draw.text((x + 8, y_celulas + tam_celula), f"real {r}", fill="black", font=fonte_pq)
        draw.text((x + 8, y_celulas + tam_celula + 16), f"prev {p}", fill=cor, font=fonte_pq)
        x += tam_celula

    status = "CORRETO" if real == previsto else "DIVERGIU"
    cor_status = (0, 130, 0) if real == previsto else (190, 0, 0)
    draw.text((10, 2), f"{nome}  |  real: {real}  |  previsto: {previsto}  |  {status}", fill=cor_status, font=fonte)
    return fig


resultados = []
for caminho, apelido, rotulo_real, (fx0, fy0, fx1, fy1), rot, categoria in AMOSTRAS:
    caminho_abs = os.path.join(DIRETORIO_ATUAL, caminho)
    im = Image.open(caminho_abs).convert("RGB")
    w, h = im.size
    caixa = (int(fx0 * w), int(fy0 * h), int(fx1 * w), int(fy1 * h))
    tira = im.crop(caixa)
    if rot:
        tira = tira.rotate(rot, expand=True)

    arr = cv2.cvtColor(np.array(tira), cv2.COLOR_RGB2GRAY)
    n = len(rotulo_real)
    tw = arr.shape[1]
    celulas = [arr[:, int(tw * i / n):int(tw * (i + 1) / n)] for i in range(n)]
    celulas_28 = [cv2.resize(c, (28, 28), interpolation=cv2.INTER_AREA) for c in celulas]

    previstos = "".join(str(prever_digito(c)) for c in celulas_28)
    acertos = sum(r == p for r, p in zip(rotulo_real, previstos))

    nome = os.path.splitext(os.path.basename(caminho))[0]
    fig = montar_figura(nome, im, celulas_28, rotulo_real, previstos)
    caminho_saida = os.path.join(DIR_OUT, f"{apelido}_predicao.png")
    fig.save(caminho_saida)

    resultados.append({
        "arquivo": os.path.basename(caminho), "categoria": categoria,
        "real": rotulo_real, "previsto": previstos,
        "leitura_correta": rotulo_real == previstos,
        "digitos_corretos": acertos, "digitos_totais": n,
        "imagem": os.path.relpath(caminho_saida, DIRETORIO_ATUAL).replace(os.sep, "/"),
    })
    print(f"{nome} [{categoria}]: real={rotulo_real} previsto={previstos} "
          f"({'OK' if rotulo_real == previstos else 'DIVERGIU'}, {acertos}/{n})")

# ==========================================
# Resumo + markdown
# ==========================================
total_fotos = len(resultados)
fotos_ok = sum(r["leitura_correta"] for r in resultados)
total_digitos = sum(r["digitos_totais"] for r in resultados)
digitos_ok = sum(r["digitos_corretos"] for r in resultados)

linhas_tabela = "\n".join(
    f"| {r['arquivo']} | {r['categoria']} | {r['real']} | {r['previsto']} | "
    f"{'✅' if r['leitura_correta'] else '❌'} | {r['digitos_corretos']}/{r['digitos_totais']} | "
    f"[ver]({r['imagem']}) |"
    for r in resultados
)

md = f"""# Teste com imagens novas (nunca usadas no treino)

Teste com {total_fotos} imagens da pasta `Imagens_2/Imagens_teste_2/`, adicionadas depois
do treino e **nunca usadas** em nenhuma etapa — nem no dataset Kaggle, nem no Dryad, nem no
fine-tuning de domínio. São fotos limpas de hidrômetros chineses (marca/modelo/fonte de
dígito completamente diferente dos medidores russos/Cirílicos do Kaggle/Dryad e das fotos
de domínio usadas antes) — um teste de generalização pra um estilo de medidor nunca visto.

Gerado por `testar_imagens_novas.py`, reaproveitando `modelo_digito.tflite` já treinado
(sem re-treinar nada). `Imagens_2/` original tem ~150 fotos (pasta local do usuário, não
versionada por completo) — só as {total_fotos} imagens realmente usadas neste teste ficam
no repositório, em `Imagens_2/Imagens_teste_2/`.

> **Sobre a pasta `Imagens_2/Imagens_teste_2_ESP32/`** (fotos reais tiradas pela ESP32CAM,
> de um monitor exibindo essas mesmas imagens de hidrômetro): tentei calibrar caixas de
> recorte pra 2 delas, mas a rotação da janela de dígitos nessas fotos específicas exigiria
> bem mais tempo de calibração manual pra ficar confiável — descartei essas amostras em vez
> de arriscar um recorte mal alinhado (mesmo critério usado no resto do projeto). Fica como
> próximo passo.
>
> Uma sexta imagem de referência (`20221221_00283.jpg`, "00764") também foi descartada
> pelo mesmo motivo: a janela de dígitos segue uma leve curva ao longo do mostrador que o
> recorte retangular + fatiamento em largura igual não consegue alinhar direito (cada
> célula pega pedaço de dois dígitos vizinhos) — o número que sairia dali mediria erro de
> recorte, não erro do modelo.

## Resumo

| Métrica | Valor |
|---|---|
| Fotos com leitura 100% correta | {fotos_ok}/{total_fotos} ({fotos_ok/total_fotos:.0%}) |
| Dígitos individuais corretos | {digitos_ok}/{total_digitos} ({digitos_ok/total_digitos:.0%}) |

## Resultado por imagem

| Arquivo | Categoria | Real | Previsto | Leitura | Dígitos certos | Imagem |
|---|---|---|---|---|---|---|
{linhas_tabela}

## Metodologia e limitações

- As caixas de recorte da janela de dígitos foram calibradas **manualmente** por imagem
  (mesma técnica usada no resto do projeto — sem máscara de segmentação automática
  disponível pra essas fotos novas), depois divididas em N fatias de largura igual.
- Amostra pequena e escolhida a dedo entre as imagens mais legíveis disponíveis em
  `Imagens_2/` (que tem ~150 fotos no total) — não é uma amostra aleatória nem exaustiva,
  então a taxa de acerto aqui não deve ser lida como "a" acurácia do modelo, só como mais
  um ponto de evidência, complementar ao [RESULTADOS.md](RESULTADOS.md).
- Esta amostra cobre só condição limpa/frontal — não inclui a degradação real da câmera
  ESP32CAM (isso já foi testado separadamente em [RESULTADOS.md](RESULTADOS.md) e
  [verificar_predicoes_dominio.py](verificar_predicoes_dominio.py), mas com medidores que
  entraram no fine-tuning, não com estes daqui).
"""

with open(os.path.join(DIRETORIO_ATUAL, "TESTE_IMAGENS_NOVAS.md"), "w", encoding="utf-8") as f:
    f.write(md)

print(f"\nResumo: {fotos_ok}/{total_fotos} fotos corretas, {digitos_ok}/{total_digitos} dígitos corretos")
print("TESTE_IMAGENS_NOVAS.md gerado")
