import os
import time
import numpy as np
import tensorflow as tf
from tensorflow.keras import layers, models
from tensorflow.keras.utils import load_img, img_to_array

# ==========================================
# 1. CONFIGURAÇÕES
# ========================================== 
DIRETORIO_ATUAL = os.path.dirname(os.path.abspath(__file__))

DIR_IMG = os.path.join(DIRETORIO_ATUAL, "dataset", "images")
DIR_MASK = os.path.join(DIRETORIO_ATUAL, "dataset", "masks")
IMG_SIZE = (192, 192)

# ==========================================
# 2. CARREGAMENTO DOS DADOS
# ==========================================
print("-> Carregando imagens e máscaras...")
arquivos = sorted(os.listdir(DIR_IMG))
X, Y = [], []

for arquivo in arquivos:
    if not arquivo.endswith(('.png', '.jpg', '.jpeg')): continue
    
    # Carrega Imagem e Máscara
    caminho_img = os.path.join(DIR_IMG, arquivo)
    caminho_mask = os.path.join(DIR_MASK, arquivo)
    
    img_array = img_to_array(load_img(caminho_img, color_mode="grayscale", target_size=IMG_SIZE)) / 255.0
    mask_array = img_to_array(load_img(caminho_mask, color_mode="grayscale", target_size=IMG_SIZE)) / 255.0
    
    # Binariza a máscara
    mask_array = np.where(mask_array > 0.5, 1.0, 0.0)
    
    X.append(img_array)
    Y.append(mask_array)

X_train = np.array(X)
Y_train = np.array(Y)
print(f"Dataset carregado! Total: {len(X_train)} amostras.")

# ==========================================
# 3. ARQUITETURA DO MODELO
# ==========================================
print("\n-> Criando modelo")
# batch_shape garante tamanho estático na memória do ESP32
inputs = layers.Input(batch_shape=(1, IMG_SIZE[0], IMG_SIZE[1], 1))

c1 = layers.Conv2D(8, (3, 3), activation='relu', padding='same')(inputs)
p1 = layers.MaxPooling2D((2, 2))(c1)

c2 = layers.Conv2D(16, (3, 3), activation='relu', padding='same')(p1)
p2 = layers.MaxPooling2D((2, 2))(c2)

u1 = layers.Conv2DTranspose(16, (3, 3), strides=(2, 2), padding='same', activation='relu')(p2)
u2 = layers.Conv2DTranspose(8, (3, 3), strides=(2, 2), padding='same', activation='relu')(u1)

outputs = layers.Conv2D(1, (1, 1), activation='sigmoid', padding='same')(u2)

model = models.Model(inputs=[inputs], outputs=[outputs])
model.compile(optimizer='adam', loss='binary_crossentropy', metrics=['accuracy'])

# Callback para estimativa de tempo restante
class TempoEstimadoCallback(tf.keras.callbacks.Callback):
    def on_train_begin(self, logs=None):
        self.tempo_inicio = time.time()

    def on_epoch_end(self, epoch, logs=None):
        epocas_feitas = epoch + 1
        epocas_totais = self.params['epochs']
        epocas_restantes = epocas_totais - epocas_feitas
        
        # Calcula a média de tempo por época até o momento
        tempo_decorrido = time.time() - self.tempo_inicio
        tempo_medio_por_epoca = tempo_decorrido / epocas_feitas
        
        # Estima o tempo restante
        tempo_restante_seg = tempo_medio_por_epoca * epocas_restantes
        
        # Converte para horas, minutos e segundos
        h = int(tempo_restante_seg // 3600)
        m = int((tempo_restante_seg % 3600) // 60)
        s = int(tempo_restante_seg % 60)
        
        if epocas_restantes > 0:
            print(f"\n[ETA Global] Faltam {epocas_restantes} épocas. Fim estimado em: {h}h {m}m {s}s\n")
            
# ==========================================
# 4. TREINAMENTO
# ==========================================

# coloquei 10000 épocas mas se tornou ineficiente pós as 6000. com acurácia maxima de 98.25%
print("\n-> Iniciando Treinamento")
model.fit(X_train, Y_train, validation_split=0.2, epochs=10000, batch_size=1, callbacks=[TempoEstimadoCallback()])

# isso é só o backup temporário do modelo, não é necessário para o ESP32
model.save("modelo_medidor.h5") 

# ==========================================
# 5. CONVERSÃO E QUANTIZAÇÃO (TFLITE INT8)
# ==========================================
print("\n-> Iniciando Conversão para int8")

def representative_dataset():
    for i in range(min(1244, len(X_train))):
        amostra = np.expand_dims(X_train[i], axis=0).astype(np.float32)
        yield [amostra]

converter = tf.lite.TFLiteConverter.from_keras_model(model)
converter.optimizations = [tf.lite.Optimize.DEFAULT]
converter.representative_dataset = representative_dataset

# Quantização completa para int8, incluindo entrada e saída
converter.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
converter.inference_input_type = tf.int8
converter.inference_output_type = tf.int8

tflite_quant_model = converter.convert()

with open("modelo_esp32.tflite", "wb") as f:
    f.write(tflite_quant_model)

print("\n->Arquivo 'modelo_esp32.tflite' gerado.")