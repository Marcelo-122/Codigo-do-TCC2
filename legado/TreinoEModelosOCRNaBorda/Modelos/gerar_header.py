import os

DIRETORIO_ATUAL = os.path.dirname(os.path.abspath(__file__))
DIR_MODELOS = os.path.join(DIRETORIO_ATUAL)

modelos_para_converter = [
    {
        "tflite": "modelo_medidor.tflite",
        "header": "modelo_medidor.h",
        "array_name": "modelo_medidor_tflite"
    },
    {
        "tflite": "modelo_multihead.tflite",
        "header": "modelo_multihead.h",
        "array_name": "modelo_multihead_tflite"
    }
]

def converter_para_header(nome_tflite, nome_header, nome_array):
    caminho_tflite = os.path.join(DIR_MODELOS, nome_tflite)
    caminho_header = os.path.join(DIR_MODELOS, nome_header)
    
    if not os.path.exists(caminho_tflite):
        print(f"[Erro] Ficheiro não encontrado: {caminho_tflite}")
        return

    with open(caminho_tflite, "rb") as f:
        dados = f.read()

    with open(caminho_header, "w") as f:
        guard_name = f"{nome_array.upper()}_H"
        f.write(f"#ifndef {guard_name}\n")
        f.write(f"#define {guard_name}\n\n")
        
        f.write(f"const unsigned char {nome_array}[] = {{\n  ")
        
        hex_bytes = [f"0x{b:02x}" for b in dados]
        
        for i, hex_byte in enumerate(hex_bytes):
            f.write(hex_byte + ", ")
            if (i + 1) % 12 == 0:
                f.write("\n  ")
                
        f.write("\n};\n")
        f.write(f"const unsigned int {nome_array}_len = {len(dados)};\n\n")
        
        f.write(f"#endif // {guard_name}\n")

    print(f"-> Ficheiro '{nome_header}' gerado com sucesso. Tamanho: {len(dados)} bytes.")

print("Iniciando conversão dos modelos para C++...\n")

for config in modelos_para_converter:
    converter_para_header(config["tflite"], config["header"], config["array_name"])
    
print("\nConversão concluída. Ficheiros .h prontos para o ESP32.")