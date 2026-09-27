"""
Recebe, pela Serial, o par (imagem anotada + métricas) que o firmware
debug_ocr_esp32cam.ino manda a cada 5 segundos.

Baseado no mesmo estilo de test_images/grab_image.py (leitura direta da
Serial com marcadores de texto), estendido pra também separar o bloco de
métricas e gravar tudo num arquivo de debug.

Uso: ajuste PORTA_SERIAL abaixo e rode. Segure Ctrl+C pra parar.

Saídas (nesta mesma pasta):
  - debug_frame_latest.jpg   -> sempre a imagem mais recente (pra ficar
                                 olhando enquanto ajusta a posição da câmera)
  - debug_frames/frame_N.jpg -> histórico de todas as imagens recebidas
  - debug_metricas.csv       -> uma linha por captura, todas as métricas
"""
import csv
import os
import re
import time

import serial

PORTA_SERIAL = 'COM5'  # ajuste para a porta que a ESP32CAM está usando
BAUD_RATE = 115200

PASTA_ATUAL = os.path.dirname(os.path.abspath(__file__))
ARQUIVO_LATEST = os.path.join(PASTA_ATUAL, 'debug_frame_latest.jpg')
PASTA_HISTORICO = os.path.join(PASTA_ATUAL, 'debug_frames')
ARQUIVO_METRICAS = os.path.join(PASTA_ATUAL, 'debug_metricas.csv')

os.makedirs(PASTA_HISTORICO, exist_ok=True)

IMG_START = b'<IMG_START>'
IMG_END = b'<IMG_END>'
METRICS_START = b'<METRICS_START>'
METRICS_END = b'<METRICS_END>'


# Campos que sao sequencias de digitos mas NAO devem virar int (perderiam
# zero a esquerda, ex.: "leitura=046663" -> 46663). Sempre tratados como
# string, mesmo parecendo um numero.
CAMPOS_SEMPRE_STRING = {"leitura"}


def parse_metricas(texto):
    """'chave=valor chave2=valor2 ...' -> dict. Tenta converter pra
    int/float quando der (exceto CAMPOS_SEMPRE_STRING); senão mantém string."""
    campos = {}
    for par in texto.strip().split():
        if '=' not in par:
            continue
        chave, valor = par.split('=', 1)
        if chave in CAMPOS_SEMPRE_STRING:
            pass
        elif re.fullmatch(r'-?\d+', valor):
            valor = int(valor)
        else:
            try:
                valor = float(valor)
            except ValueError:
                pass
        campos[chave] = valor
    return campos


def preparar_csv(cabecalho):
    novo = not os.path.exists(ARQUIVO_METRICAS)
    f = open(ARQUIVO_METRICAS, 'a', newline='', encoding='utf-8')
    writer = csv.DictWriter(f, fieldnames=cabecalho)
    if novo:
        writer.writeheader()
    return f, writer


def main():
    try:
        ser = serial.Serial()
        ser.port = PORTA_SERIAL
        ser.baudrate = BAUD_RATE
        ser.timeout = 1
        ser.setDTR(False)
        ser.setRTS(False)
        ser.open()
        print(f"Conectado à porta {PORTA_SERIAL}. Aguardando frames de debug...")
    except Exception as e:
        print(f"Erro ao conectar na porta {PORTA_SERIAL}: {e}")
        return

    contador = 1
    buffer = b''
    estado = None  # None | 'imagem' | 'metricas'
    imagem_atual = b''
    csv_file = None
    csv_writer = None

    try:
        while True:
            if ser.in_waiting > 0:
                buffer += ser.read(ser.in_waiting)
            else:
                time.sleep(0.02)
                continue

            progresso = True
            while progresso:
                progresso = False

                if estado is None:
                    if IMG_START in buffer:
                        _, buffer = buffer.split(IMG_START, 1)
                        estado = 'imagem'
                        imagem_atual = b''
                        progresso = True
                    elif METRICS_START in buffer:
                        _, buffer = buffer.split(METRICS_START, 1)
                        estado = 'metricas'
                        progresso = True

                elif estado == 'imagem':
                    if IMG_END in buffer:
                        parte, buffer = buffer.split(IMG_END, 1)
                        imagem_atual += parte
                        estado = None
                        progresso = True

                        nome_historico = os.path.join(PASTA_HISTORICO, f"frame_{contador}.jpg")
                        with open(nome_historico, 'wb') as f:
                            f.write(imagem_atual)
                        with open(ARQUIVO_LATEST, 'wb') as f:
                            f.write(imagem_atual)
                        print(f"[{contador}] imagem salva: {nome_historico} "
                              f"({len(imagem_atual)} bytes) — também em debug_frame_latest.jpg")
                        contador += 1
                    else:
                        imagem_atual += buffer
                        buffer = b''

                elif estado == 'metricas':
                    if METRICS_END in buffer:
                        parte, buffer = buffer.split(METRICS_END, 1)
                        texto = parte.decode('ascii', errors='ignore')
                        estado = None
                        progresso = True

                        campos = parse_metricas(texto)
                        campos['recebido_em'] = time.strftime('%Y-%m-%d %H:%M:%S')
                        print(f"[metricas] {campos}")

                        if csv_writer is None:
                            cabecalho = ['recebido_em'] + [k for k in campos if k != 'recebido_em']
                            csv_file, csv_writer = preparar_csv(cabecalho)
                        csv_writer.writerow(campos)
                        csv_file.flush()

    except KeyboardInterrupt:
        print("\nEncerrando captura de debug.")
    finally:
        if csv_file:
            csv_file.close()
        ser.close()


if __name__ == '__main__':
    main()
