import serial
import sys
import time
import os
from pathlib import Path

# config.py fica na raiz do repositório (uma pasta acima desta)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config

PORTA_SERIAL = config.require("TX_SERIAL_PORT")  # defina no .env (veja .env.example)
BAUD_RATE = 115200

try:
    # Configuração manual para evitar que o ESP32 trave no reset
    ser = serial.Serial()
    ser.port = PORTA_SERIAL
    ser.baudrate = BAUD_RATE
    ser.timeout = 1
    
    ser.setDTR(False)
    ser.setRTS(False)
    
    ser.open()
    print(f"Conectado à porta {PORTA_SERIAL}. Aguardando fotos...")
except Exception as e:
    print(f"Erro ao conectar na porta {PORTA_SERIAL}: {e}")
    exit()

# O restante do seu código de leitura do buffer continua exatamente igual a partir daqui...
contador = 1
buffer_imagem = b''
recebendo = False

while True:
    try:
        if ser.in_waiting > 0:
            dados = ser.read(ser.in_waiting)
            
            if b'<IMG_START>' in dados:
                recebendo = True
                buffer_imagem = b''
                # Pega apenas os dados após o marcador de início
                dados = dados.split(b'<IMG_START>')[1]
                
            if recebendo:
                if b'<IMG_END>' in dados:
                    # Pega apenas os dados antes do marcador de fim
                    buffer_imagem += dados.split(b'<IMG_END>')[0]
                    recebendo = False
                    
                    # Salva o arquivo na pasta atual
                    nome_arquivo = f"imagem_capturada_{contador}.jpg"
                    with open(nome_arquivo, "wb") as f:
                        f.write(buffer_imagem)
                    
                    print(f"Foto salva: {nome_arquivo}")
                    contador += 1
                else:
                    buffer_imagem += dados
                    
    except KeyboardInterrupt:
        print("\nEncerrando captura.")
        ser.close()
        break