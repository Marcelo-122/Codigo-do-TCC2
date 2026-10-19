# Codigo-do-TCC2

Compilado de todos os códigos usados no TCC2: **leitura automática de hidrômetro com
ESP32-CAM e envio da imagem/leitura por LoRaWAN**.

O trabalho une duas frentes que se complementam:

1. **Visão computacional embarcada (OCR)** — a partir da foto de um hidrômetro de "rodinhas"
   (*word-wheel*), localizar a janela de dígitos e ler o valor (m³) com redes neurais pequenas
   o bastante para rodar em microcontrolador (TFLite Micro / INT8).
2. **Enlace LoRaWAN** — transportar a imagem (ou a leitura) da ESP32-CAM até um receptor
   usando um módulo Radioenge RD49C, no plano de canais AU915 e dentro das regras da Anatel.

---

## Sumário

- [Visão geral da arquitetura](#visão-geral-da-arquitetura)
- [Estrutura do repositório](#estrutura-do-repositório)
- [Hardware utilizado](#hardware-utilizado)
- [1. Rede LoRaWAN (`Rede/`)](#1-rede-lorawan-rede)
- [2. PoC de redução de imagem (`poc_diminuicao_imagem/`)](#2-poc-de-redução-de-imagem-poc_diminuicao_imagem)
- [3. OCR "na nuvem"/PC (`ocr_cloud/`)](#3-ocr-na-nuvempc-ocr_cloud)
- [4. OCR na borda — treino e modelos (`TreinoEModelosOCRNaBorda/`)](#4-ocr-na-borda--treino-e-modelos-treinoemodelosocrnaborda)
- [5. Classificador de dígitos + dataset (`ModeloEDataset/`)](#5-classificador-de-dígitos--dataset-modeloedataset)
- [6. Firmware de debug/calibração (`test_images/`)](#6-firmware-de-debugcalibração-test_images)
- [Configuração de segredos](#configuração-de-segredos)
- [Datasets e créditos](#datasets-e-créditos)
- [Histórico de branches](#histórico-de-branches)
- [Limitações conhecidas e próximos passos](#limitações-conhecidas-e-próximos-passos)
- [Autores](#autores)

---

## Visão geral da arquitetura

```
                       ┌────────────────────────── OCR (visão computacional) ───────────────────────────┐
                       │                                                                                 │
 Hidrômetro ──foto──▶ ESP32-CAM ──▶ [1] segmentação (U-Net INT8)  ──▶ recorte da janela de dígitos      │
                       │                                          ──▶ [2] leitura dos dígitos           │
                       │                                               (CNN por dígito  ou  CRNN+CTC)   │
                       └─────────────────────────────────────────────────────────────────────────────────┘
                                   │ imagem JPEG (ou leitura) em chunks de 100 bytes
                                   ▼
                       Radioenge RD49C (AU915, DR6 = SF8 / BW 500 kHz, canal 64 = 915,9 MHz)
                                   │  LoRaWAN (uplink, ABP)
                                   ▼
                       Heltec/TTGO LoRa32 (receptor, imprime  HEX:<frame>|RSSI:<n>  na serial)
                                   │ USB-serial
                                   ▼
                       PC: reconstrutor.py  →  descriptografa (AES-128 CTR) → remonta o JPEG
```

Os dois estágios de OCR já foram **testados juntos em uma ESP32-CAM real**
(ver [`test_images/`](test_images/debug_ocr_esp32cam/README.md)). O enlace LoRaWAN foi validado
separadamente transmitindo a imagem em chunks (ver [`Rede/`](#1-rede-lorawan-rede)). A integração
final (OCR no dispositivo → só a leitura trafega por LoRaWAN) é um dos próximos passos.

---

## Estrutura do repositório

```
Codigo-do-TCC2/
├── Rede/                          Enlace LoRaWAN (ESP32-CAM → Radioenge → LoRa32 → PC)
│   ├── transmissor_esp32cam/      Firmware: captura JPEG, fatia em chunks e envia via Radioenge
│   ├── receptor_lora32/           Firmware do receptor (Heltec/TTGO LoRa32)
│   ├── teste_enlace_radioenge/    Firmware de teste de enlace (payload fixo, SENDALL/RESEND)
│   ├── prototipo_serial_chirpstack/  Protótipo anterior: serial → ChirpStack (MQTT / simulador de gateway)
│   ├── reconstrutor.py            PC: lê a serial do receptor, descriptografa e remonta o JPEG
│   └── requirements.txt
├── poc_diminuicao_imagem/         PoC em C++/OpenCV: redução/binarização de imagem p/ caber no LoRa
├── ocr_cloud/                     OCR em Python (PC/nuvem): segmentação TFLite + CNN de dígitos
├── TreinoEModelosOCRNaBorda/      Treino do detector (U-Net QAT) e do leitor CRNN+CTC p/ ESP32
├── ModeloEDataset/                Pipeline do classificador de dígitos (CNN) + datasets + relatórios
├── test_images/                   Fotos da ESP32-CAM + firmware de debug/calibração com OCR on-device
├── .env.example                   Modelo das variáveis secretas (copie para .env)
└── README.md
```

> Cada pasta de OCR tem uma abordagem própria (ver tabela abaixo). Elas **não dependem umas das
> outras** — cada uma tem seu próprio dataset, `requirements.txt` e scripts.

| Pasta | Abordagem de leitura | Segmentação | Onde roda |
|---|---|---|---|
| `ocr_cloud/` | CNN de 1 caractere (68×68) sobre 6 recortes iguais; há também teste com CRNN+CTC | U-Net INT8 384×384 | PC / nuvem |
| `TreinoEModelosOCRNaBorda/` | **CRNN + CTC** (visor inteiro 48×224, classe *blank* = 10), float e QAT | U-Net com QAT, 384×384 | Treino no PC → ESP32 |
| `ModeloEDataset/` | CNN de dígito (28×28, 72 mil parâmetros) sobre N fatias | U-Net INT8 (`modelo_esp32.tflite`) | Treino no PC → ESP32-CAM |

---

## Hardware utilizado

| Peça | Função |
|---|---|
| **ESP32-CAM (AI-Thinker)** | Captura a imagem (QQVGA 160×120, JPEG qualidade 12) e, na versão de debug, roda o OCR |
| **Radioenge RD49C** | Módulo LoRaWAN (comandos `AT+...`), ligado à ESP32-CAM por UART (RX = GPIO 15, TX = GPIO 14) |
| **Heltec / TTGO LoRa32 V2** | Receptor LoRa: SS = 18, RST = 14, DIO0 = 26; imprime os frames recebidos na serial |
| **PC** | Roda `reconstrutor.py`, treina os modelos e (no protótipo antigo) hospeda o ChirpStack |
| **Gateway/ChirpStack** *(só protótipo antigo)* | Servidor LoRaWAN recebendo pacotes Semtech UDP / MQTT |

**Parâmetros de rádio (AU915):** canal 64 fixo, **915,9 MHz**, **SF8 / BW 500 kHz (DR6)**,
sync word `0x34`. Enquadramento pretendido: **item 10.3 do Ato Anatel nº 14448/2017**
(modulação digital de banda larga ≥ 500 kHz, sem exigência de salto de frequência). A alternativa
com salto de frequência (item 10.2.5.2, 35 canais de 125 kHz, `AT+DR=5`) está documentada nos
comentários de [`teste_enlace_radioenge.ino`](Rede/teste_enlace_radioenge/teste_enlace_radioenge.ino).

> Atenção: **nunca** use `CHMASK` com menos de 35 canais em BW = 125 kHz — não se enquadra em
> nenhum dos dois itens da regulamentação.

---

## 1. Rede LoRaWAN (`Rede/`)

### Fluxo

1. A ESP32-CAM recebe `CAPTURE` pela serial, tira uma foto JPEG e a divide em **chunks de 100 bytes**.
2. Cada chunk vai com um cabeçalho binário de 4 bytes — `uint16 index` + `uint16 total`
   (big-endian) — e é enviado ao Radioenge com `AT+SENDB=01:<hex>` (FPort 1).
3. O **receptor LoRa32** escuta em 915,9 MHz / SF8 / BW 500 kHz e escreve na serial uma linha por
   frame: `HEX:<bytes do frame>|RSSI:<valor>`.
4. O **`reconstrutor.py`** lê essas linhas, extrai o `FRMPayload`, **descriptografa com a AppSKey**
   (AES-128 em modo CTR, conforme a especificação LoRaWAN), junta os chunks e grava
   `imagem_recebida.jpg`. Chunks faltantes geram `imagem_parcial.jpg` (com zeros nos buracos);
   mandar `CAPTURE` de novo preenche apenas o que faltou.

### Firmwares (Arduino IDE)

| Sketch | Placa | Observações |
|---|---|---|
| `transmissor_esp32cam/` | AI Thinker ESP32-CAM | Comandos pela serial: `CAPTURE` (captura e envia) ou `AT...` (repassado direto ao Radioenge). Intervalo entre chunks: `SEND_INTERVAL_MS` (7000 ms). |
| `receptor_lora32/` | TTGO/Heltec LoRa32 V2 | Biblioteca **LoRa** (Sandeep Mistry). Frequência fixa 915,9 MHz. |
| `teste_enlace_radioenge/` | AI Thinker ESP32-CAM | Não usa câmera: envia um payload fixo. Comandos `SENDALL` e `RESEND:2,7,15` para testar perda/reenvio de chunks, com retentativas quando o módulo está ocupado. |

### Rodando o receptor no PC

```bash
cd Rede
python -m venv .venv
# Windows
.venv\Scripts\pip install -r requirements.txt
# Configure o .env com as chaves e RX_SERIAL_PORT (ver "Configuração de segredos")
.venv\Scripts\python reconstrutor.py
# Em outro terminal serial (ou no Monitor Serial do transmissor) envie:  CAPTURE
```

### Protótipo anterior (`prototipo_serial_chirpstack/`)

Primeira abordagem, **sem rádio real**: a ESP32-CAM manda os chunks por USB-serial e o PC os
injeta num servidor ChirpStack.

| Arquivo | Função |
|---|---|
| `esp32cam_jpeg_hex_chunks/` | Sketch: captura JPEG e envia `BEGIN,<bytes>,<chunks>` / `CHUNK,<i>,<len>,<hex>` / `END,<crc32>` pela serial (85 bytes por chunk) |
| `main.py` + `decode.py` | Gravam a saída serial em `raw_data.txt` e reconstroem `image.jpg` conferindo o CRC32 |
| `mqtt_bridge.py` | Publica cada chunk como uplink no tópico MQTT do ChirpStack |
| `mac_simulator.py` | "Finge" ser um gateway: monta o PHYPayload LoRaWAN (cifra + MIC) e envia via Semtech UDP (PUSH_DATA/PULL_DATA) ao ChirpStack |

---

## 2. PoC de redução de imagem (`poc_diminuicao_imagem/`)

Prova de conceito em **C++ / OpenCV** para medir quanto uma imagem encolhe ao ser convertida para
tons de cinza e binarizada (`Cinza.png`, `Binaria.png`) — relevante porque cada byte a menos
significa menos chunks no enlace LoRa. O programa varre `imagens/`, imprime largura, altura,
canais e tamanho em bytes de cada etapa e grava o resumo em `output.txt`.

```bash
cd poc_diminuicao_imagem
# Requer g++, OpenCV 4 e Qt6 (ajuste os caminhos do makefile para o seu sistema)
make
```

---

## 3. OCR "na nuvem"/PC (`ocr_cloud/`)

Pipeline em Python/TensorFlow que roda no PC (ou em um servidor), pensado como alternativa quando
o dispositivo apenas envia a foto:

```
foto ──▶ modelo_medidor.tflite (segmentação, INT8, 384×384) ──▶ recorte da janela
       ──▶ divide em 6 pedaços iguais ──▶ modelo_ocr.keras (CNN de 1 dígito, 68×68) ──▶ "leitura"
```

| Item | Descrição |
|---|---|
| `src/train_model_ocr_cloud.py` | Treina a CNN de 1 caractere (3 × Conv2D + Dense, 10 classes) com `num_dataset/` e salva `models/modelo_ocr.keras` |
| `src/test_model_ocr_cloud_poc.py` | Executa segmentação + OCR por fatias nas fotos de `metering_dataset/` |
| `src/test_model_ocr_cloud_gustavo.py` | Variante que usa o modelo CRNN+CTC float (entrada 48×224, *blank* = 10) |
| `models/` | `modelo_medidor.tflite`, `modelo_ocr.keras`, `modelo_digitos_float_ctc_sint.tflite` |
| `metering_dataset/` | Fotos reais de hidrômetros para teste |
| `num_dataset/` | Dígitos isolados 0–9 (uma pasta por classe) |

```bash
cd ocr_cloud
python -m venv .venv && .venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python src\train_model_ocr_cloud.py        # treino
.venv\Scripts\python src\test_model_ocr_cloud_poc.py     # inferência
```

---

## 4. OCR na borda — treino e modelos (`TreinoEModelosOCRNaBorda/`)

Treino dos dois modelos que devem rodar no microcontrolador, com **quantização consciente do
treino (QAT)** para INT8:

1. **Detector** (`treinamento-detector.py`): U-Net (entrada 384×384, 1 canal) com perda
   BCE + Dice; fase 1 treina em float, fase 2 faz *fine-tuning* com QAT e exporta
   `Modelos/modelo_medidor.tflite`.
2. **Leitor** (`treinamento-digitos-ctc.py`): rede convolucional + camadas temporais 1D (sem LSTM,
   para caber no MCU) treinada com **CTC** para ler o visor inteiro de uma vez. Treina em imagens
   reais "blackout" e em visores sintéticos; exporta versões float e QAT (`modelo_digitos_*_ctc*.tflite`).

| Script | Para que serve |
|---|---|
| `gerar_blackout.py` | Recorta e endireita o visor usando a máscara e apaga o fundo (`dataset/visores_blackout/`) |
| `gerador_sintetico.py` | Gera 1500 visores sintéticos colando dígitos isolados (`dataset/visores_sinteticos/`) |
| `treinamento-detector.py` / `treinamento-digitos-ctc.py` | Treino dos dois modelos |
| `diagnostico_detector.py` / `diagnostico_colapso_ctc.py` | Diagnósticos: IoU/Dice do detector; colapso do CTC e posição dos erros (Levenshtein) |
| `simulador_extracao_dual.py` | Roda detector + leitor sobre `dataset/imagens_reais/` e grava `CSVs/leituras_finais.*` |
| `BDM.py` | Valida o modelo QAT (IoU, Dice, latência) em amostras do dataset, do conjunto de teste e do "mundo real" → `CSVs/tabela_provas_funcionamento.csv` |
| `BDMwsl.cpp` | Teste do `.h` do modelo em **TFLite Micro** compilado no WSL/Linux (arena de 25 MB) |
| `Modelos/gerar_header.py` | Converte `.tflite` em header C (`modelo_medidor.h`) para o firmware |
| `Backups/`, `CSVs/`, `resultados_visuais/`, `ModeloBrutoAntigoParaTeste/` | Checkpoints, históricos de treino/validação, imagens de diagnóstico e modelos antigos |

```bash
cd TreinoEModelosOCRNaBorda
python -m venv .venv && .venv\Scripts\pip install -r requirements.txt
python gerar_blackout.py
python gerador_sintetico.py
python treinamento-detector.py
python treinamento-digitos-ctc.py
python simulador_extracao_dual.py
python Modelos\gerar_header.py
```

> Os scripts usam `TF_USE_LEGACY_KERAS=1` (necessário para o `tensorflow_model_optimization`).

---

## 5. Classificador de dígitos + dataset (`ModeloEDataset/`)

Segundo estágio do OCR: um **classificador de dígito (0–9)** pequeno (72.442 parâmetros, 81,5 KB em
INT8) que lê cada fatia da janela de dígitos. Combina três fontes de dados (Kaggle, Dryad e fotos
reais da própria ESP32-CAM) e é treinado em duas fases (treino principal + *fine-tuning* de domínio).

| Métrica | Valor |
|---|---|
| Acurácia (validação, INT8, 10 classes) | **96,9 %** |
| Fotos reais da ESP32-CAM (24 recortes — mesmas do *fine-tuning*, número otimista) | 100 % |
| Imagens totalmente novas (nunca vistas no treino): 30/32 dígitos | 94 % |

Tudo está documentado no **[README próprio](ModeloEDataset/README.md)** (fontes de dados, arquitetura,
histórico de iterações, bug de *split* corrigido), com relatórios reprodutíveis em
`ModeloEDataset/relatorios/`.

```bash
cd ModeloEDataset
python -m venv .venv                 # Python 3.10 (TensorFlow sem wheel estável p/ 3.13 no Windows)
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python preparar_dataset_digitos.py
.venv\Scripts\python preparar_dataset_dryad.py          # requer o dataset Dryad local (2,8 GB, não versionado)
.venv\Scripts\python preparar_dataset_dominio_esp32.py
.venv\Scripts\python treinar_classificador_digitos.py
.venv\Scripts\python gerar_header.py --tflite modelos/modelo_digito.tflite --header modelos/modelo_digito.h --array-name modelo_digito_tflite
```

---

## 6. Firmware de debug/calibração (`test_images/`)

`test_images/debug_ocr_esp32cam/` contém o firmware que roda **segmentação + classificação de dígitos
diretamente na ESP32-CAM** (TFLite Micro, 4 MB de PSRAM): a cada 5 s captura uma imagem 160×120,
localiza a janela de dígitos, classifica cada fatia (`N_FATIAS` ajustável por medidor — 6 no
medidor de teste) e envia pela serial a imagem anotada, a leitura e métricas (RAM, PSRAM, tempos,
temperatura). O PC recebe tudo com `grab_image_debug.py`, que gera `debug_frame_latest.jpg` e
`debug_metricas.csv`. Detalhes, erros de memória encontrados e correções no
[README da pasta](test_images/debug_ocr_esp32cam/README.md).

`test_images/grab_image.py` é o capturador simples de fotos pela serial (usado para montar os
conjuntos de imagens reais `imagem_capturada_N.jpg`).

Achado importante: a inferência da segmentação levou **~15,5 s por frame** em hardware real —
aceitável para calibração, mas precisa ser otimizada antes de uso em produção.

---

## Configuração de segredos

Chaves de sessão LoRaWAN, endereços de rede, IDs do ChirpStack e portas seriais **não ficam no
código**. Todos os scripts leem esses valores do arquivo `.env` (via `config.py`):

```bash
cp .env.example .env      # Windows: copy .env.example .env
```

Preencha o `.env` com os valores da sua máquina (o `.env.example` descreve cada variável e quais
scripts a usam). O `.env` está no `.gitignore` e nunca deve ser commitado. Para descobrir as portas
seriais disponíveis, rode `python verify.py`.

| Variável | Usada por |
| --- | --- |
| `TX_SERIAL_PORT` | `main.py`, `mqtt_bridge.py`, `mac_simulator.py`, `orchestrator.py`, `test_images/grab_image.py`, `test_images/debug_ocr_esp32cam/grab_image_debug.py` |
| `RX_SERIAL_PORT` | `reconstrutor.py`, `decode_lorawan.py`, `orchestrator.py` |
| `LORA_DEV_ADDR`, `LORA_APP_SKEY` | `reconstrutor.py`, `decode_lorawan.py`, `orchestrator.py`, `mac_simulator.py` |
| `LORA_NWK_SKEY`, `GATEWAY_UDP_IP`, `GATEWAY_UDP_PORT`, `GATEWAY_MAC` | `mac_simulator.py` |
| `MQTT_BROKER`, `MQTT_PORT`, `CHIRPSTACK_APPLICATION_ID`, `CHIRPSTACK_DEV_EUI` | `mqtt_bridge.py` |
| `IMAGE_PATH` | `orchestrator.py` |

> Se algum valor já foi commitado em algum momento, ele continua no histórico do Git: gere novas
> chaves (`AT+NWKSKEY`, `AT+APPSKEY`) em vez de reutilizar as antigas.

---

## Datasets e créditos

| Dataset | Autor | Uso | Licença/observação |
|---|---|---|---|
| [Yandex.Toloka Water Meters](https://www.kaggle.com/datasets/tapakah68/yandextoloka-water-meters-dataset) | Kucev Roman | Fotos + máscaras da janela de dígitos (`images/`, `masks/`) | Ver página do Kaggle |
| [Digits 0–9](https://www.kaggle.com/datasets/aquibiqbal/digits-09) | Aquib Iqbal | Dígitos isolados (`num/`, `num_dataset/`) | Ver página do Kaggle |
| Word-Wheel Water Meter Dataset | Zhao et al., *Scientific Data* 13, 479 (2026) — [DOI 10.1038/s41597-026-06809-z](https://doi.org/10.1038/s41597-026-06809-z) | Dígitos rotulados (não versionado, 2,8 GB) | **CC BY-NC-ND 4.0** — uso acadêmico OK; reavaliar se virar produto comercial |
| Fotos da ESP32-CAM | Próprio projeto | Fine-tuning de domínio e testes | — |

Documentos regulatórios/técnicos usados como referência (fora do repositório): Anatel — Ato nº 14448/2017,
Anatel — Resolução nº 715/2019 e o manual LoRaWAN.

---

## Histórico de branches

O trabalho foi desenvolvido em paralelo e unificado na `main`:

| Branch de origem | Conteúdo |
|---|---|
| `main` | Rede LoRaWAN (firmwares, `reconstrutor.py`), protótipo serial/ChirpStack, PoC de redução de imagem, `ocr_cloud/` |
| `Treino-Testes-e-Modelos` | `TreinoEModelosOCRNaBorda/` (treino do detector e do CRNN+CTC, modelos, datasets) |
| `ocr` | `ModeloEDataset/` (classificador de dígitos) e `test_images/` (firmware de debug com OCR on-device) |

---

## Limitações conhecidas e próximos passos

- **Latência da segmentação** no ESP32 (~15,5 s/frame): reduzir a resolução de entrada ou usar kernels
  otimizados para Xtensa.
- **Poucas fotos reais** da ESP32-CAM (dígitos 4, 5 e 6 ausentes no conjunto de domínio); coletar
  30–50 fotos por medidor, em condições variadas, separando uma fatia só para teste.
- **Integração final**: levar o OCR do firmware de debug para um firmware de produção e enviar apenas a
  leitura (poucos bytes) pelo LoRaWAN, em vez da imagem inteira.
- Perda de chunks no enlace: hoje o reenvio é manual (`CAPTURE` / `RESEND`); automatizar com confirmação.
- Unificar as três abordagens de OCR (`ocr_cloud`, `TreinoEModelosOCRNaBorda`, `ModeloEDataset`) após
  comparar a acurácia de cada uma no mesmo conjunto de teste.
- `mac_simulator.py` usa `FREQ = 868.1` (faixa EU868) com comentário de AU915; ajustar para o plano
  de canais realmente configurado no ChirpStack.

---

## Autores

- **Marcelo Fernandes** — enlace LoRaWAN, integração com a ESP32-CAM, `ModeloEDataset/` e `test_images/`
- **Gustavo Santos** — `TreinoEModelosOCRNaBorda/` (treino e modelos de OCR na borda; autor do modelo de segmentação original citado em `ModeloEDataset/`)
- **ChristianDev123** — `poc_diminuicao_imagem/` e `ocr_cloud/`

> Atribuições inferidas do histórico de commits — ajuste conforme a contribuição real de cada um.
