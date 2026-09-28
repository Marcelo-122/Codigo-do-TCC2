import tensorflow as tf
import os
import shutil

MODEL_PATH = "modelo_ocr.keras"
EXPORT_DIR = "modelo_ocr_savedmodel"

if os.path.exists(EXPORT_DIR):
    shutil.rmtree(EXPORT_DIR)

# 1. Carrega o modelo Keras .keras
model = tf.keras.models.load_model(MODEL_PATH)

# 2. Encapsula o modelo em uma ConcreteFunction explícita
# Define o nome exato da entrada para facilitar a busca no C
@tf.function(input_signature=[tf.TensorSpec(shape=[1, 64, 64, 1], dtype=tf.float32, name="input_tensor")])
def serve_fn(x):
    return {"output_tensor": model(x)}

# 3. Extrai a função concreta do Grafo
concrete_func = serve_fn.get_concrete_function()

# 4. Salva o SavedModel com a assinatura explícita
tf.saved_model.save(
    model,
    EXPORT_DIR,
    signatures={"serving_default": concrete_func}
)

print("Modelo exportado com sucesso para 'modelo_ocr_savedmodel'!")