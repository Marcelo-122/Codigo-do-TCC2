"""Gera os headers C do teste do pipeline A a partir dos .tflite de ../Modelos.

Uso (nesta pasta):  python gerar_headers.py

Os arrays saem com alignas(16) e em `const`, então ficam na flash e alinhados como o
TFLite Micro espera. Só entram os modelos que o teste usa; os float (2 MB) ficam de fora.
Os headers gerados (cerca de 7,5 MB) não ficam no Git: rode este script antes de compilar.
"""
import os

AQUI = os.path.dirname(os.path.abspath(__file__))
MODELOS = os.path.join(AQUI, "..", "Modelos")

LISTA = [
    ("modelo_medidor.tflite", "a_detector.h", "a_detector_tflite"),
    ("modelo_digitos_ctc.tflite", "a_ctc.h", "a_ctc_tflite"),
    ("modelo_digitos_ctc_sint.tflite", "a_ctc_sint.h", "a_ctc_sint_tflite"),
]

for tflite, header, nome in LISTA:
    with open(os.path.join(MODELOS, tflite), "rb") as f:
        dados = f.read()
    guard = nome.upper() + "_H"
    with open(os.path.join(AQUI, header), "w", newline="\n") as f:
        f.write(f"#ifndef {guard}\n#define {guard}\n\n")
        f.write(f"alignas(16) const unsigned char {nome}[] = {{\n  ")
        for i, b in enumerate(dados):
            f.write(f"0x{b:02x}, ")
            if (i + 1) % 12 == 0:
                f.write("\n  ")
        f.write(f"\n}};\nconst unsigned int {nome}_len = {len(dados)};\n\n#endif\n")
    print(f"{header}: {len(dados)} bytes (de {tflite})")
