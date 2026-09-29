import os
import cv2
import numpy as np
import random

# ==========================================
# 1. CONFIGURAÇÕES
# ==========================================
DIRETORIO_ATUAL = os.path.dirname(os.path.abspath(__file__))
DIR_DIGITOS_ANTIGOS = os.path.join(DIRETORIO_ATUAL, "dataset", "num")

# Nova pasta dedicada para não misturar com as imagens reais (blackout)
DIR_VISORES_SINTETICOS = os.path.join(DIRETORIO_ATUAL, "dataset", "visores_sinteticos")

TOTAL_GERAR = 1500  # Aumentado para gerar um bom volume de dados
ALTURA_DIGITO = 48
LARGURA_DIGITO = 24
LARGURA_MAXIMA = 168 

# ==========================================
# 2. CARREGAMENTO DOS NÚMEROS ISOLADOS
# ==========================================
banco_imagens = {str(i): [] for i in range(10)}

for i in range(10):
    pasta_digito = os.path.join(DIR_DIGITOS_ANTIGOS, str(i))
    if os.path.exists(pasta_digito):
        banco_imagens[str(i)] = [os.path.join(pasta_digito, f) for f in os.listdir(pasta_digito) if f.endswith(('.png', '.jpg', '.jpeg'))]

for i in range(10):
    if len(banco_imagens[str(i)]) == 0:
        raise ValueError(f"A pasta do número {i} está vazia ou não existe em {DIR_DIGITOS_ANTIGOS}!")

print(f"-> Gerando {TOTAL_GERAR} visores sintéticos...")

# ==========================================
# 3. MONTAGEM DOS VISORES
# ==========================================
for _ in range(TOTAL_GERAR):
    # Sorteia tamanhos de 5 a 8 dígitos para treinar o CTC com sequências variáveis
    qtd_digitos = random.choice([5, 6, 7, 8])
    sequencia = "".join([str(random.randint(0, 9)) for _ in range(qtd_digitos)])
    
    fatias = []
    for num in sequencia:
        caminho_escolhido = random.choice(banco_imagens[num])
        img = cv2.imread(caminho_escolhido, cv2.IMREAD_GRAYSCALE)
        img = cv2.resize(img, (LARGURA_DIGITO, ALTURA_DIGITO))
        
        if random.random() > 0.3:
            cv2.line(img, (0, 0), (0, ALTURA_DIGITO), (80), 1)
            
        fatias.append(img)
    
    visor_base = np.hstack(fatias)
    
    # Preenchimento de fundo PRETO (0) para alinhar com as imagens reais em blackout
    if visor_base.shape[1] < LARGURA_MAXIMA:
        falta_largura = LARGURA_MAXIMA - visor_base.shape[1]
        pad_esq = falta_largura // 2
        pad_dir = falta_largura - pad_esq
        visor_completo = cv2.copyMakeBorder(visor_base, 0, 0, pad_esq, pad_dir, cv2.BORDER_CONSTANT, value=0)
    else:
        # Se ultrapassar a largura (ex: 8 dígitos = 192px), redimensiona para caber
        visor_completo = cv2.resize(visor_base, (LARGURA_MAXIMA, ALTURA_DIGITO))
        
    # O "X" foi removido. A pasta terá exatamente a sequência numérica gerada.
    pasta_destino = os.path.join(DIR_VISORES_SINTETICOS, sequencia)
    os.makedirs(pasta_destino, exist_ok=True)
    
    hash_aleatorio = random.randint(10000, 99999)
    caminho_salvar = os.path.join(pasta_destino, f"sintetico_{hash_aleatorio}.jpg")
    cv2.imwrite(caminho_salvar, visor_completo)

print(f"\n-> Sucesso! Imagens sintéticas limpas salvas em: {DIR_VISORES_SINTETICOS}")