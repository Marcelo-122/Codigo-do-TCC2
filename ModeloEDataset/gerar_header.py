import argparse

parser = argparse.ArgumentParser()
parser.add_argument("--tflite", default="modelos/modelo_esp32.tflite")
parser.add_argument("--header", default="modelos/modelo.h")
parser.add_argument("--array-name", default="modelo_tflite")
args = parser.parse_args()

arquivo_tflite = args.tflite
arquivo_header = args.header
nome_do_array = args.array_name

with open(arquivo_tflite, "rb") as f:
    dados = f.read()

with open(arquivo_header, "w") as f:
    f.write(f"const unsigned char {nome_do_array}[] = {{\n  ")

    hex_bytes = [f"0x{b:02x}" for b in dados]

    for i, hex_byte in enumerate(hex_bytes):
        f.write(hex_byte + ", ")
        if (i + 1) % 12 == 0:
            f.write("\n  ")

    f.write("\n};\n")
    f.write(f"const unsigned int {nome_do_array}_len = {len(dados)};\n")

print(f"Arquivo {arquivo_header} gerado. Tamanho: {len(dados)} bytes.")
