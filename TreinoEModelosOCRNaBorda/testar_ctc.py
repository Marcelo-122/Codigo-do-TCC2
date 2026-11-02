import os
import random
import cv2
import numpy as np
import pandas as pd
import tensorflow as tf
from diagnostico_colapso_ctc import (diagnosticar_colapso, acuracia_valor, acuracia_por_parte,
                                     distancia_edicao, acertos_por_posicao, acuracia_digito_posicao,
                                     acuracia_digito_edicao, acuracia_por_casa)

# ==========================================
# 1. CONFIGURAÇÕES
# ==========================================
DIRETORIO_ATUAL = os.path.dirname(os.path.abspath(__file__))

DIR_DATASET_REAL = os.path.join(DIRETORIO_ATUAL, "dataset", "visores_blackout")
DIR_MODELOS = os.path.join(DIRETORIO_ATUAL, "Modelos")
DIR_CSVS = os.path.join(DIRETORIO_ATUAL, "CSVs")

NOME_MODELO_TFLITE = "modelo_digitos_qat_ctc_sint_8d.tflite"
CAMINHO_TFLITE = os.path.join(DIR_MODELOS, NOME_MODELO_TFLITE)
ARQUIVO_RELATORIO_CSV = os.path.join(DIR_CSVS, "relatorio_teste_ctc.csv")

IMG_HEIGHT = 48
IMG_WIDTH = 224
MAX_DIGITOS = 8
BLANK = 10

SEED = 42

MODO_ACURACIA = "ambas"

SUBCONJUNTO = "todas"
PROPORCAO_TREINO = 0.8
TOTAL_AMOSTRAS = 30  # um inteiro (ex.: 100) testa N imagens aleatórias; None testa todas do subconjunto

ADICIONAR_RESUMO_NO_CSV = True

if MODO_ACURACIA not in ("completa", "digito", "ambas"):
    raise ValueError("MODO_ACURACIA deve ser 'completa', 'digito' ou 'ambas'.")
if SUBCONJUNTO not in ("todas", "validacao"):
    raise ValueError("SUBCONJUNTO deve ser 'todas' ou 'validacao'.")

random.seed(SEED)
np.random.seed(SEED)
os.makedirs(DIR_CSVS, exist_ok=True)

# ==========================================
# 2. MAPEAMENTO E SELEÇÃO DAS IMAGENS
# ==========================================
print(f"-> Mapeando imagens em: {DIR_DATASET_REAL}...")

imagens_por_rotulo = {}
for root, dirs, files in os.walk(DIR_DATASET_REAL):
    nome_pasta = os.path.basename(root)
    if not nome_pasta or nome_pasta.startswith('.') or "visores" in nome_pasta:
        continue

    imgs = [os.path.join(root, f) for f in files if f.lower().endswith(('.png', '.jpg', '.jpeg'))]
    if not imgs:
        continue

    rotulo = nome_pasta.strip().upper().rstrip('X')
    if not (1 <= len(rotulo) <= MAX_DIGITOS) or not all(c in '0123456789' for c in rotulo):
        continue

    imagens_por_rotulo.setdefault(rotulo, []).extend(imgs)

if not imagens_por_rotulo:
    raise ValueError(f"Nenhuma imagem válida encontrada em {DIR_DATASET_REAL}.")

rotulos_usados = sorted(imagens_por_rotulo.keys())
if SUBCONJUNTO == "validacao":
    # Mesma lógica do treino: sorted -> shuffle com semente 42 -> corte em 80%.
    # random.Random(SEED).shuffle equivale ao random.seed(SEED) + random.shuffle do treino.
    embaralhados = list(rotulos_usados)
    random.Random(SEED).shuffle(embaralhados)
    corte = int(len(embaralhados) * PROPORCAO_TREINO)
    rotulos_usados = embaralhados[corte:]

lista_completa = []
for rotulo in rotulos_usados:
    digitos_reais = [int(c) for c in rotulo]
    for caminho in imagens_por_rotulo[rotulo]:
        lista_completa.append((caminho, digitos_reais, rotulo))

print(f"-> Subconjunto '{SUBCONJUNTO}': {len(rotulos_usados)} leituras, {len(lista_completa)} imagens.")
if SUBCONJUNTO == "validacao":
    print("   Confira se este número bate com 'Validação: N imagens reais' impresso no início do treino.")
else:
    print("   [ATENÇÃO] Inclui imagens usadas no TREINO: não use este número como acurácia de generalização.")

# Embaralha aleatoriamente as imagens
random.shuffle(lista_completa)

if TOTAL_AMOSTRAS is not None and TOTAL_AMOSTRAS < len(lista_completa):
    lista_completa = lista_completa[:TOTAL_AMOSTRAS]
    print(f"-> Selecionadas {TOTAL_AMOSTRAS} amostras aleatórias para o teste.")
else:
    print(f"-> Serão testadas todas as {len(lista_completa)} imagens em ordem aleatória.")

# ==========================================
# 3. PRÉ-PROCESSAMENTO DAS IMAGENS (igual ao do treino)
# ==========================================
def preparar_imagem(caminho):
    img = cv2.imread(caminho, cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise FileNotFoundError(f"Não foi possível abrir a imagem: {caminho}")

    h, w = img.shape
    escala = min(IMG_HEIGHT / h, IMG_WIDTH / w)
    nova_h = max(1, int(round(h * escala)))
    nova_w = max(1, int(round(w * escala)))

    img_redimensionada = cv2.resize(img, (nova_w, nova_h), interpolation=cv2.INTER_LINEAR)

    canvas = np.zeros((IMG_HEIGHT, IMG_WIDTH), dtype=np.float32)
    canvas[:nova_h, :nova_w] = img_redimensionada

    canvas = canvas / 255.0
    return canvas[..., np.newaxis].astype(np.float32)

# ==========================================
# 4. DECODIFICAÇÃO CTC (GREEDY)
# ==========================================
def softmax(x):
    e = np.exp(x - x.max(axis=-1, keepdims=True))
    return e / e.sum(axis=-1, keepdims=True)

def decodificar_greedy(logits):
    probs = softmax(logits)
    ids = np.argmax(probs, axis=-1)
    saida, anterior = [], BLANK
    for i in ids:
        if i != BLANK and i != anterior:
            saida.append(int(i))
        anterior = i
    return saida

def lista_para_texto(lista):
    return ''.join(str(d) for d in lista)

# ==========================================
# 5. INFERÊNCIA TFLITE
# ==========================================
if not os.path.exists(CAMINHO_TFLITE):
    raise FileNotFoundError(f"Modelo TFLite não encontrado em: {CAMINHO_TFLITE}.")

print(f"\n-> Carregando modelo TFLite: {CAMINHO_TFLITE}...")
interpretador = tf.lite.Interpreter(model_path=CAMINHO_TFLITE)
interpretador.allocate_tensors()

det_in = interpretador.get_input_details()[0]
det_out = interpretador.get_output_details()[0]
escala_in, zero_in = det_in['quantization']
escala_out, zero_out = det_out['quantization']

resultados = []
detalhes_relatorio = []

print("-> Processando inferências...")
for caminho, real, rotulo_str in lista_completa:
    img_tensor = preparar_imagem(caminho)

    if det_in['dtype'] == np.int8:
        q = np.clip(np.round(img_tensor / escala_in + zero_in), -128, 127).astype(np.int8)
        interpretador.set_tensor(det_in['index'], q[np.newaxis, ...])
    else:
        interpretador.set_tensor(det_in['index'], img_tensor[np.newaxis, ...])

    interpretador.invoke()

    bruto = interpretador.get_tensor(det_out['index'])[0].astype(np.float32)
    if det_out['dtype'] == np.int8 or escala_out != 0.0:
        logits = (bruto - zero_out) * escala_out
    else:
        logits = bruto

    pred = decodificar_greedy(logits)
    resultados.append((real, pred))

    completo = (real == pred)
    oks = acertos_por_posicao(real, pred)
    dist_edit = distancia_edicao(real, pred)
    valor_ok = acuracia_valor([(real, pred)]) == 1.0
    int_ok, dec_ok = (v == 1.0 for v in acuracia_por_parte([(real, pred)]))

    if completo:
        status = "OK"
    elif MODO_ACURACIA != "completa" and any(oks):
        status = "PARCIAL"          # alguns dígitos certos, mas não todos
    else:
        status = "ERRO"

    detalhes_relatorio.append({
        "Arquivo": os.path.basename(caminho),
        "Leitura_Real": rotulo_str,
        "Leitura_Prevista": lista_para_texto(pred),
        "Status": status,
        "Acerto_Completo": completo,
        "Digitos_Corretos": f"{sum(oks)}/{len(real)}",
        "Acuracia_Digito_Posicao": round(sum(oks) / len(real), 4),
        "Acuracia_Digito_Edicao": round(max(0.0, 1.0 - dist_edit / len(real)), 4),
        "Erros_Por_Caracteres": dist_edit,
        "Valor_Correto": valor_ok,
        "Parte_Inteira_Correta": int_ok,
        "Parte_Decimal_Correta": dec_ok
    })

# ==========================================
# 6. CÁLCULO E RELATÓRIO DAS MÉTRICAS
# ==========================================
total_amostras = len(resultados)
exatos = sum(1 for real, pred in resultados if real == pred)
acuracia_completa = exatos / total_amostras if total_amostras > 0 else 0.0

acertos_pos, total_digitos = acuracia_digito_posicao(resultados)
acuracia_dig_pos = acertos_pos / total_digitos if total_digitos > 0 else 0.0
acuracia_dig_edicao = acuracia_digito_edicao(resultados)

mostrar_completa = MODO_ACURACIA in ("completa", "ambas")
mostrar_digito = MODO_ACURACIA in ("digito", "ambas")

print("\n" + "=" * 70)
print(f"RELATÓRIO DE AVALIAÇÃO — {total_amostras} imagens | subconjunto: {SUBCONJUNTO} | modo: {MODO_ACURACIA}")
print("=" * 70)

if mostrar_completa:
    print(f" - Acurácia COMPLETA (todos os dígitos corretos): {acuracia_completa * 100:.2f}% "
          f"({exatos}/{total_amostras})")

if mostrar_digito:
    print(f" - Acurácia POR DÍGITO, por posição (alinhada pela direita): "
          f"{acuracia_dig_pos * 100:.2f}% ({acertos_pos}/{total_digitos})")
    print(f" - Acurácia POR DÍGITO, por edição (tolera 1 dígito a mais/a menos): "
          f"{acuracia_dig_edicao * 100:.2f}%")

    acertos_casa, totais_casa = acuracia_por_casa(resultados, MAX_DIGITOS)
    print("\n   Acerto por casa (d1 = mais à esquerda de uma leitura de "
          f"{MAX_DIGITOS} dígitos, d{MAX_DIGITOS} = último):")
    for k in range(MAX_DIGITOS - 1, -1, -1):
        if totais_casa[k]:
            print(f"     d{MAX_DIGITOS - k}: {100 * acertos_casa[k] / totais_casa[k]:6.2f}% "
                  f"({acertos_casa[k]}/{totais_casa[k]})")

ac_valor = acuracia_valor(resultados)
ac_int, ac_dec = acuracia_por_parte(resultados)
print("\n Complementares (ignoram zeros à esquerda / separam inteira e decimal):")
print(f"   Valor correto (sem zeros à esquerda): {ac_valor * 100:.2f}%")
print(f"   Parte inteira correta:                {ac_int * 100:.2f}%")
print(f"   Parte decimal correta (3 últimos):    {ac_dec * 100:.2f}%")

if mostrar_completa:
    print("\n-> Diagnóstico de Colapso CTC:")
    diagnosticar_colapso(resultados)

# ==========================================
# 7. EXPORTAÇÃO PARA CSV
# ==========================================
df_detalhes = pd.DataFrame(detalhes_relatorio)

if ADICIONAR_RESUMO_NO_CSV and total_amostras > 0:
    contagem = pd.Series([d["Status"] for d in detalhes_relatorio]).value_counts()
    linha_resumo = {
        "Arquivo": "MEDIA_FINAL",
        "Leitura_Real": f"{total_amostras} imagens | subconjunto: {SUBCONJUNTO}",
        "Leitura_Prevista": "",
        "Status": (f"{contagem.get('OK', 0)} OK | {contagem.get('PARCIAL', 0)} PARCIAL | "
                   f"{contagem.get('ERRO', 0)} ERRO"),
        # nesta linha, as colunas de acerto trazem a FRAÇÃO média (0 a 1), não True/False
        "Acerto_Completo": round(acuracia_completa, 4),
        "Digitos_Corretos": f"{acertos_pos}/{total_digitos}",
        "Acuracia_Digito_Posicao": round(acuracia_dig_pos, 4),
        "Acuracia_Digito_Edicao": round(acuracia_dig_edicao, 4),
        "Erros_Por_Caracteres": round(sum(d["Erros_Por_Caracteres"] for d in detalhes_relatorio) / total_amostras, 4),
        "Valor_Correto": round(ac_valor, 4),
        "Parte_Inteira_Correta": round(ac_int, 4),
        "Parte_Decimal_Correta": round(ac_dec, 4),
    }
    df_detalhes = pd.concat([df_detalhes, pd.DataFrame([linha_resumo])], ignore_index=True)
    print("-> Linha final 'MEDIA_FINAL' (acurácia média das imagens testadas) adicionada ao CSV.")

df_detalhes.to_csv(ARQUIVO_RELATORIO_CSV, index=False, encoding='utf-8-sig')

print(f"\n-> Relatório em CSV exportado com sucesso para: {ARQUIVO_RELATORIO_CSV}")
