# Medições em hardware (H2 – latência, H3 – energia)

Dados brutos capturados na ESP32-CAM pelo firmware
[`debug_ocr_esp32cam`](../test_images/debug_ocr_esp32cam/debug_ocr_esp32cam.ino)
e gravados por [`grab_image_debug.py`](../test_images/debug_ocr_esp32cam/grab_image_debug.py).

## Arquivos

| Arquivo | Firmware | Capturas | Conteúdo |
|---|---|---|---|
| `debug_metricas.csv` | atual (segmentação + classificador de dígito) | 61 | tempos por etapa, heap, PSRAM, arena dos dois modelos, leitura |
| `debug_metricas_v1_so_segmentacao.csv` | versão antiga, só segmentação | 28 | sem leitura nem `t_digitos_ms`; coluna `t_inferencia_ms` |
| `debug_metricas_teste2_so_segmentacao.csv` | versão antiga, só segmentação | 17 | idem |
| `corrente/teste_1.csv` | `Rede/transmissor_esp32cam` antes de desligar a câmera após a captura, `AUTO:30` | 4 ciclos | `t_us,shunt_mV,bus_V` do INA219 (shunt 0,1 Ω) lido por um Arduino Uno a 100 Hz; analisado com `corrente.py` ([`medir_corrente.md`](medir_corrente.md)) |
| `corrente/auto30_imagem.csv` (+ `.png`) | `Rede/transmissor_esp32cam` com a câmera desligada após a captura, `AUTO:30` | 30 ciclos válidos (31 despertares com 1 falso) | mesmo formato; 685.000 amostras em 6.850 s, 2026-10-27 09:29 a 11:22 |
| `latencia_ponta_a_ponta.csv` | mesmo firmware, medido no PC por `latencia_ponta_a_ponta.py auto` | 31 disparos (30 com envio) | uma linha por leitura: chunks enviados/recebidos, bytes do JPEG, RSSI, tempo até o 1º/último chunk e até a imagem completa |
| `transmissao.csv` | `Rede/transmissor_esp32cam` (fluxo de imagem) | — | uma linha por imagem: PDR, tempo de rádio, latência ([`medir_transmissao.md`](medir_transmissao.md)) |
| `transmissao_ocr.csv` | `Rede/transmissor_ocr_esp32cam` (fluxo de OCR, FPort 2) | — | uma linha por leitura recebida: dígitos, FCnt, RSSI, tempo de rádio, latência ([`medir_transmissao.md`](medir_transmissao.md)) |

Os dois últimos são gerados pelo `reconstrutor.py` e ainda não têm medições em placa.

Todas as capturas são de 2026-09-27 (17:54 a 19:02). Os arquivos `v1`/`teste2` foram
mantidos por serem medições reais, mas **não entram** na contagem do critério de pronto
(firmware diferente).

> **Correção do CSV.** O `debug_metricas.csv` original misturava 28 linhas do firmware antigo
> (21 colunas) com 61 do firmware atual (25 colunas) sob um único cabeçalho, porque o script
> anexava linhas ao arquivo existente sem comparar as colunas. As linhas foram separadas
> sem alterar nenhum valor, com duas exceções: o cabeçalho das 61 linhas atuais foi reescrito
> na ordem do `printf` do `.ino`, e a coluna `leitura` recebeu o zero à esquerda que o
> parser havia descartado (largura 8 até 18:42:24, 6 depois, conforme `N_FATIAS` da época;
> `46663` → `046663`). O `grab_image_debug.py` agora grava em `medicoes/` e renomeia o
> arquivo antigo se as colunas mudarem.

## Ambiente

| Item | Valor |
|---|---|
| Placa | AI-Thinker ESP32-CAM, CPU a 240 MHz, PSRAM de 4 MB (`cpu_mhz`, `psram_size` do CSV) |
| Core Arduino-ESP32 | **3.0.7** (`esp32` da Espressif Systems, Boards Manager da Arduino IDE 2.3.10; ESP-IDF v5.1). Versão lida da instalação em 2026-10-27; o log das capturas de 2026-09-27 não a registra, então assume-se o mesmo core (o README da raiz já o citava como o do PC de desenvolvimento) |
| Biblioteca TFLite Micro | **`espressif/esp-tflite-micro` 1.3.1, com `esp-nn` 1.1.0**, embutida no core 3.0.7 (arquivo `versions.txt` de `esp32-arduino-libs`). Não há biblioteca TFLite instalada à parte na pasta de bibliotecas do sketchbook; o sketch inclui `tensorflow/lite/micro/micro_log.h` desse pacote |
| Entrada da câmera | 160×120, tons de cinza; segmentação redimensiona para 192×192 |
| Modelos | `modelo.h` (segmentação, `modelo_esp32.tflite`) e `modelo_digito.h` (classificador) |
| Intervalo entre capturas | 5 s de `delay` + ~18 s de processamento |
| Medição de corrente | INA219 (shunt R100 = 0,1 Ω) lido por um Arduino Uno a 100 amostras/s; 5 V do USB da ESP32-CAM-MB passando pelo INA219 antes da ESP32-CAM; capacitor de 100 µF/50 V depois do shunt; offset não descontado (leitura de 0,00 mV com o nó desligado, resolução de 0,01 mV) |

## Resultados (61 capturas, firmware atual)

| Métrica | Mínimo | Mediana | Máximo |
|---|---:|---:|---:|
| `t_inferencia_seg_ms` (segmentação) | 15.563 | **15.564** | 15.567 |
| `t_digitos_ms` (classificador, 6 fatias, capturas com caixa) | 1.994 | 1.995 | 2.644 |
| `t_encode_ms` (JPEG) | 9 | 11 | 14 |
| `t_total_ms` (capturas com caixa) | 17.739 | 17.838 | 18.720 |
| `heap_free` (bytes) | 293.744 | 293.744 | 294.008 |
| `psram_free` (bytes) | 1.289.292 | 1.289.292 | 1.289.292 |
| `arena_seg_bytes` | 1.623.852 | 1.623.852 | 1.623.852 |
| `arena_digito_bytes` | 28.556 | 28.556 | 28.556 |
| `temp_c` | 72,2 | 73,3 | 73,9 |

- A inferência de segmentação leva **~15,6 s com variação de 4 ms**, então o número é
  determinístico, não ruído de medição. O `t_total_ms` passa de 17,7 s.
- 58 das 61 capturas encontraram a caixa dos dígitos; nas 3 sem caixa o classificador não roda
  (`leitura=--------`, `t_total_ms` = 15.746).
- No medidor de teste (leitura real `046663`), as 12 últimas capturas leem `046663` (14 no
  total); antes, durante a calibração da posição, a leitura varia (por exemplo `026663`).
  Isto mostra consistência com a câmera parada, **não** acurácia: não há rótulo por captura.
- A temperatura do chip passou de 72 °C durante toda a sessão.

## Latência de inferência e decisão sobre o modelo (H2)

**Medido.** A segmentação leva 15.564 ms por captura (mediana de 61 capturas; mínimo 15.563, máximo 15.567)
e a leitura completa, 17.838 ms (segmentação mais classificador de dígitos, ~2,0 s). O valor confirma os
~15,5 s do `ModeloEDataset/README.md` e é determinístico (variação de 4 ms), não ruído de medição.

**Relação com a H2.** A H2 ("o método de processamento local apresenta menor latência e maior valor de taxa de
pacotes entregues") compara fluxos, não etapas:

| Fluxo | Composição | Latência (despertar até o dado no PC) |
|---|---|---|
| Nuvem (imagem) | captura em ~0,7 s, 1º chunk em ~2,0 s e envio de 22 a 27 chunks, um a cada ~7,9 s (JPEG de 3,7 a 4,6 KB) | **mediana de 189 s** (173 a 214 s), **medido** em 30 leituras de `AUTO:30` (20 imagens completas; ver "Latência ponta a ponta e entrega do fluxo de imagem"). No teste curto anterior, com JPEG de ~3,0 KB (18 chunks), foram ≈ 141 s. A inferência na nuvem não está incluída |
| Local (OCR na borda) | inferência de ~17,8 s mais 1 uplink de ~9 bytes | ≈ 18 s mais o uplink, **estimado**: o `transmissor_ocr_esp32cam` ainda não foi medido |

**Decisão.**
- *Reduzir o modelo* (entrada menor, menos filtros, kernels otimizados): descartado. Com câmera fixa a
  instalação não precisa de uma segmentação a cada leitura, e a rede é fraca (Dice 0,39, IoU 0,28), então
  encolhê-la ou melhorá-la não melhora a leitura.
- *Revisar a H2*: não é necessário pelos números. Mesmo com a segmentação a cada leitura, a latência estimada
  do fluxo local (~18 s) é cerca de 1/10 da do fluxo de imagem (mediana medida de 189 s).
- **Adotada:** manter o Pipeline B e retirar a segmentação do firmware com uma ROI calibrada na instalação
  (ver a decisão no README da raiz). Efeito esperado: leitura em ≈ 2 s por leitura. É uma **estimativa**: o
  firmware ainda não foi alterado.

**Ainda falta para confirmar a H2:** a latência medida do fluxo local (`latencia_ponta_a_ponta.py auto --fluxo ocr`)
e a taxa de pacotes entregues do fluxo local (1 pacote por leitura). Do fluxo de imagem já há 30 leituras
(22 a 27 pacotes cada): 98,0% dos pacotes e 66,7% das imagens entregues (seção abaixo); `transmissao.csv` e
`transmissao_ocr.csv` ainda não foram gerados.

## Consumo do fluxo de imagem (teste curto, câmera ligada durante o envio)

Primeira medição de corrente, em 2026-10-27, com `Rede/transmissor_esp32cam` no modo `AUTO:30` e
`JANELA_STOP_MS = 1500` (`corrente/teste_1.csv`, 1.024 s, tensão média 4,874 V). Resultado com 4 ciclos completos
(`python corrente.py analisar corrente/teste_1.csv --offset-ma 0.0 --init-s 2.699 --captura-s 0.01 --envio-s 139.7 --min-sleep-s 5`):

| Grandeza | Valor |
|---|---|
| `mAh por leitura` | **6,62** (desvio 0,005 mAh, n = 4; sleep de 30 s) |
| Período do ciclo | 172,1 s (≈ 142,7 s acordado + 30 s de sleep) |
| Corrente média acordado | ≈ 162 mA, com base de ≈ 159 mA entre os chunks e picos de TX até ≈ 298 mA |
| Corrente em sleep | ≈ 24,1 mA, **incluindo o Radioenge** (ainda não separado) |
| Antes de iniciar a câmera | ≈ 77 mA; o degrau até ≈ 159 mA aparece quando a câmera inicia |

O consumo é dominado pela espera de 7 s entre chunks com CPU e câmera ligadas (≈ 95% da carga do ciclo); os picos
de TX somam ≈ 2%. Isto é a referência de **antes da otimização** (câmera ligada), com 4 ciclos. A versão com
a câmera desligada foi medida em 30 ciclos (seção seguinte). Detalhes e a interpretação em
[`medir_corrente.md`](medir_corrente.md).

## Consumo do fluxo de imagem (30 ciclos, câmera desligada após a captura)

`Rede/transmissor_esp32cam` em `AUTO:30`, captura de corrente em `corrente/auto30_imagem.csv`
(2026-10-27, 685.000 amostras em 6.850 s, tensão média 4,914 V). Análise com
`python medicoes/corrente.py analisar medicoes/corrente/auto30_imagem.csv --offset-ma 0.0 --min-sleep-s 12`
(com `--min-sleep-s 5` três picos isolados de uma amostra, ≈ 61 mA, partem o sleep e geram ciclos falsos).
O ciclo 28 da tabela do `analisar` não é uma leitura: o nó acordou por 0,97 s (pico de 190 mA) e voltou a dormir
sem enviar nada (coincide com a linha vazia de 11:10:24 em `latencia_ponta_a_ponta.csv`; causa não investigada).
Ele foi **excluído**, o que deixa **30 ciclos completos**.

| Grandeza | Valor (n = 30 ciclos) |
|---|---|
| `mAh por leitura` | **4,64** (mediana 4,65; desvio 0,24; de 4,26 a 5,24) |
| Corrente média acordado | ≈ 84,5 mA (de 81 a 86 mA por ciclo); picos de TX de 206 a 220 mA |
| Corrente em sleep | ≈ 23,7 mA, **incluindo o Radioenge** (ainda não separado) |
| Tempo acordado | média 189,9 s (de 173 a 219 s) |
| Período do ciclo | média 218,5 s (≈ 190 s acordado + ≈ 29 s de sleep) |

- **Efeito de desligar a câmera:** a corrente acordado caiu de ≈ 162 mA para ≈ 84,5 mA (−48%). O consumo por
  leitura caiu de 6,62 para 4,64 mAh (−30%), menos do que a corrente sugere porque o tempo acordado subiu.
- **A variação entre ciclos vem do tamanho da imagem.** O tempo acordado cresce em degraus de ≈ 8 s, um chunk a
  mais, e acompanha os 22 a 27 chunks de `latencia_ponta_a_ponta.csv`. O JPEG ficou maior que no teste curto
  (3,7 a 4,6 KB contra ≈ 3,0 KB). A causa não foi estabelecida (provavelmente cena e luz diferentes), então o
  valor de 4,64 mAh vale para imagens desse tamanho.
- Com uma bateria hipotética de 2000 mAh e um ciclo de ≈ 218 s (intervalo de 30 s de sleep), o `analisar` estima
  ≈ 1,1 dia, sem perdas do regulador nem auto-descarga. O intervalo real de campo (mais sleep) muda esse número.

## Latência ponta a ponta e entrega do fluxo de imagem (30 leituras)

`latencia_ponta_a_ponta.py auto` rodou junto com a captura de corrente (2026-10-27, 09:34 a 11:20). O PC marca o
tempo até cada chunk e monta a imagem. Foram 31 disparos: 30 com envio e 1 sem nenhum chunk (o falso ciclo 28).

| Grandeza | Valor |
|---|---|
| Chunks enviados / recebidos | 713 / 699 (14 perdidos): **98,0%** dos pacotes entregues |
| Imagens completas | **20 de 30 (66,7%)**; as 10 incompletas perderam 1 ou 2 chunks cada |
| Latência até a imagem completa (n = 20) | **mediana 189,1 s**, de 172,7 a 213,5 s (média 188,2; desvio 11,8) |
| Tempo até o último chunk (todas as 30) | mediana 189,2 s, de 172,7 a 213,5 s |
| Chunks por imagem / JPEG | 22 a 27 (mediana 24) / 3.689 a 4.568 bytes (mediana 4.068) |
| Foto / 1º chunk | ≈ 0,7 s / ≈ 2,0 s (em 3 leituras o 1º chunk levou mais de 10 s) |
| RSSI médio | de −28,4 a −27,1 dBm (sinal muito forte) |

A latência é dominada pelo envio: ≈ 7,9 s por chunk, então cresce com o tamanho do JPEG. Os 98% de pacotes
entregues parecem altos, mas como a imagem só serve inteira, **um terço das imagens se perdeu**. É o dado que
a H2 compara com o fluxo local, que envia 1 pacote por leitura (ainda não medido).

## Pendente

- **Consumo, fluxo de imagem:** separar o sleep do Radioenge (`SLEEP:60` com ele desconectado); autonomia com a
  bateria real e o intervalo de campo; investigar a causa do despertar sem envio (ciclo 28) e do JPEG maior.
  Procedimento em [`medir_corrente.md`](medir_corrente.md).
- **Consumo, fluxo de OCR na borda:** sem medição. O firmware
  [`Rede/transmissor_ocr_esp32cam`](../Rede/transmissor_ocr_esp32cam/transmissor_ocr_esp32cam.ino) existe, mas
  **não foi compilado com a toolchain do ESP32 nem testado em placa**.
- **Latência ponta a ponta, fluxo de OCR:** o fluxo de imagem está medido (30 leituras, seção acima). Para o de
  OCR o script tem `--fluxo ocr` ([`medir_latencia.md`](medir_latencia.md)), mas o lado do PC (FPort 2,
  `transmissao_ocr.csv`) foi testado só com frames sintéticos e não há medição em placa.
- **Deep sleep:** implementado em `Rede/transmissor_esp32cam` (comandos `AUTO`, `STOP`, `SLEEP`) e em
  `Rede/transmissor_ocr_esp32cam`. No de imagem, os 30 ciclos de `AUTO:30` (acima) mostram a corrente caindo de
  ≈ 84,5 mA acordado para ≈ 23,7 mA dormindo em todos os ciclos, e o teste curto de 4 ciclos confirmou
  `DEEPSLEEP_RESET` e o contador de ciclos na memória RTC. O de OCR não foi testado em placa. Roteiro em
  [`teste_deep_sleep.md`](teste_deep_sleep.md).
- **Taxa de pacotes entregues (H2):** fluxo de imagem medido em `latencia_ponta_a_ponta.csv` (98,0% dos
  pacotes, 20 de 30 imagens completas); `transmissao.csv` (imagem) e `transmissao_ocr.csv` (OCR) ainda sem
  medições em placa, e o fluxo de OCR não tem número de entrega; ver [`medir_transmissao.md`](medir_transmissao.md).
