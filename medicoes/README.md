# Medições em hardware (H2 – latência, H3 – energia)

As hipóteses H2 e H3 estão definidas no [README da raiz](../README.md#hipóteses-avaliadas).

Dados brutos de três firmwares:

- [`debug_ocr_esp32cam`](../test_images/debug_ocr_esp32cam/debug_ocr_esp32cam.ino): tempos, memória e leitura do OCR
  na placa (`debug_metricas*.csv`, gravados por
  [`grab_image_debug.py`](../test_images/debug_ocr_esp32cam/grab_image_debug.py)), em 2026-09-27;
- [`Rede/transmissor_esp32cam`](../Rede/transmissor_esp32cam/transmissor_esp32cam.ino) (fluxo de imagem) e
  [`Rede/transmissor_ocr_esp32cam`](../Rede/transmissor_ocr_esp32cam/transmissor_ocr_esp32cam.ino) (OCR na borda):
  corrente (`corrente/`), latência ponta a ponta e transmissão, em 2026-10-27.

## Arquivos

| Arquivo | Firmware | Capturas | Conteúdo |
|---|---|---|---|
| `debug_metricas.csv` | atual (segmentação + classificador de dígito) | 61 | tempos por etapa, heap, PSRAM, arena dos dois modelos, leitura |
| `debug_metricas_v1_so_segmentacao.csv` | versão antiga, só segmentação | 28 | sem leitura nem `t_digitos_ms`; coluna `t_inferencia_ms` |
| `debug_metricas_teste2_so_segmentacao.csv` | versão antiga, só segmentação | 17 | idem |
| `corrente/teste_1.csv` | `Rede/transmissor_esp32cam` antes de desligar a câmera após a captura, `AUTO:30` | 4 ciclos | `t_us,shunt_mV,bus_V` do INA219 (shunt 0,1 Ω) lido por um Arduino Uno a 100 Hz; analisado com `corrente.py` ([`medir_corrente.md`](medir_corrente.md)) |
| `corrente/auto30_imagem.csv` (+ `.png`) | `Rede/transmissor_esp32cam` com a câmera desligada após a captura, `AUTO:30` | 30 ciclos válidos (31 despertares com 1 falso) | mesmo formato; 2026-10-27 a partir das 09:29. O arquivo tem 1.041.066 amostras (≈ 10.410 s), mas a análise usa as primeiras 685.000 (6.850 s, até 11:22); o resultado é o mesmo com o arquivo inteiro |
| `corrente/auto30_ocr.csv` (+ `.png`) | `Rede/transmissor_ocr_esp32cam`, `AUTO:30` | 32 ciclos | mesmo formato; 169.738 amostras em 1.697 s, 2026-10-27 12:22 a 12:49 |
| `latencia_ponta_a_ponta.csv` | mesmo firmware, medido no PC por `latencia_ponta_a_ponta.py auto` | 31 disparos (30 com envio) | uma linha por leitura: chunks enviados/recebidos, bytes do JPEG, RSSI, tempo até o 1º/último chunk e até a imagem completa |
| `latencia_ocr.csv` | `Rede/transmissor_ocr_esp32cam`, medido no PC por `latencia_ponta_a_ponta.py auto --fluxo ocr` | 34 disparos (27 uplinks recebidos) | uma linha por leitura: RSSI, tempo até a linha `[ocr] leitura=` e até o dado no PC, dígitos lidos, `achou_caixa`; 2026-10-27, 12:59 a 13:27 |
| `latencia_ocr_roi.csv` | `Rede/transmissor_ocr_esp32cam` em modo ROI (sem segmentação), medido no PC por `latencia_ponta_a_ponta.py auto --fluxo ocr --iniciar-auto 30` | 30 disparos (30 uplinks recebidos) | mesmo formato de `latencia_ocr.csv`; 2026-11-18 23:58 a 2026-11-19 00:14 |
| `corrente/auto30_ocr_roi_classe_a.csv` | `Rede/transmissor_ocr_esp32cam` em modo ROI, Radioenge em **classe A**, `AUTO:30` | 29 ciclos | formato do INA219; 102.707 amostras (1.027 s), 2026-11-19 |
| `corrente/auto30_imagem_classe_a.csv` | `Rede/transmissor_esp32cam`, Radioenge em **classe A**, `AUTO:30` | 29 ciclos | formato do INA219; 527.088 amostras (5.271 s), 2026-11-19 |
| `latencia_ocr_roi_classe_a.csv` e `latencia_imagem_classe_a.csv` | as mesmas corridas, medidas no PC por `latencia_ponta_a_ponta.py auto --iniciar-auto 30` | 30 leituras cada | mesmo formato de `latencia_ocr.csv` e `latencia_ponta_a_ponta.csv` |
| `corrente/descartadas/` | primeira corrida do fluxo de imagem em classe A | 4 ciclos válidos | interrompida por uma queda de energia do nó às 12:19; **fora das estatísticas** |
| `latencia_ocr_tentativa1.csv` | mesmo firmware, primeira tentativa | 28 disparos (1 uplink recebido) | tentativa em que o receptor não entregou nenhum uplink ao PC durante 22 min (12:25 a 12:46); **não entra nas estatísticas**, fica como registro |
| `transmissao.csv` | `Rede/transmissor_esp32cam` (fluxo de imagem, `CAPTURE` pelo PC) | 30 envios | uma linha por imagem: PDR, tempo de rádio, latência ([`medir_transmissao.md`](medir_transmissao.md)); corrida de 2026-10-27, 14:59 a 16:44 |
| `transmissao_execucoes_anteriores.csv` | mesmo firmware, 5 execuções interrompidas | 21 linhas | execuções das 13:41 a 14:55 que pegaram as janelas de silêncio do receptor (ver "Enlace do fluxo de imagem"); **fora das estatísticas**; os logs e as imagens delas foram apagados |
| `logs/<execução>/` e `imagens/` | `reconstrutor.py` | 1 execução | `chunks.csv`, `eventos.jsonl`, `serial_rx.txt` (DevAddr mascarado), `serial_tx.txt` e `meta.json` da corrida de `transmissao.csv`; as 21 imagens completas dela (`..._L<id>.jpg`) |
| `transmissao_ocr.csv` | `Rede/transmissor_ocr_esp32cam` (fluxo de OCR, FPort 2) | — | uma linha por leitura recebida: dígitos, FCnt, RSSI, tempo de rádio, latência ([`medir_transmissao.md`](medir_transmissao.md)) |
| `tempo_inferencia_nuvem.py` | servidor (`ocr/pipeline_nuvem.py`, LiteRT sem XNNPACK) | 21 imagens × 5 | tempo do OCR da nuvem sobre as imagens completas de `imagens/`, que a latência ponta a ponta não inclui; em 2026-11-01, Ryzen 5 5600GT (WSL): leitura completa 6,25 ms, segmentação 4,30 ms, ROI fixa 1,91 ms (medianas). Só imprime, não grava CSV |
| `ina219_logger/` e `ina219_diagnostico/` | Arduino Uno + INA219 | — | o logger de corrente (100 amostras/s, `t_us,shunt_mV,bus_V`) e o diagnóstico ao vivo da ligação do INA219 (para achar mau contato); ver [`medir_corrente.md`](medir_corrente.md) |
| `exportar_ciclo_corrente.py` | — | 1 ciclo por arquivo | exporta um ciclo de `corrente/*.csv` (mesma detecção de ciclos do `corrente.py analisar`) como envelope mín./máx. a cada 0,25 s, em `.dat` para o gráfico do TCC; o docstring tem os dois comandos usados (ciclo 8 da imagem, ciclo 4 do OCR) |

O `transmissao.csv` e o `transmissao_ocr.csv` são gerados pelo `reconstrutor.py`. O `transmissao.csv` tem a corrida de
30 envios do fluxo de imagem; o `transmissao_ocr.csv` nunca foi gerado (a latência do OCR está em `latencia_ocr.csv`).

As capturas do firmware de debug (`debug_metricas*.csv`) são de 2026-09-27 (17:54 a 19:02); as de corrente, latência
e transmissão são de 2026-10-27. Os arquivos `v1`/`teste2` foram
mantidos por serem medições reais, mas **não entram** nos resultados abaixo
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
| Modelos | `modelo.h` (segmentação, `modelo_esp32.tflite`) e `modelo_digito.h` (classificador). **Atenção:** o `modelo.h` do repositório foi reexportado em 2026-10-25 (12.080 bytes, com os operadores `SHAPE`, `STRIDED_SLICE` e `PACK`) e **não é o que rodou nas 61 capturas**: o firmware de debug daquelas capturas só registrava 4 operadores, que o modelo atual não cabe (o de 11.128 bytes em `legado/` tem só esses 4). Latência, arena e temperatura desta tabela valem para o modelo antigo e serão refeitos com o atual no fluxo de OCR |
| Intervalo entre capturas | 5 s de `delay` + ~18 s de processamento |
| Medição de corrente | INA219 (shunt R100 = 0,1 Ω) lido por um Arduino Uno a 100 amostras/s; 5 V do USB da ESP32-CAM-MB passando pelo INA219 antes da ESP32-CAM; capacitor de 100 µF/50 V depois do shunt; offset não descontado (leitura de 0,00 mV com o nó desligado, resolução de 0,01 mV) |

## Resultados (61 capturas, firmware atual)

| Métrica | Mínimo | Mediana | Máximo |
|---|---:|---:|---:|
| `t_inferencia_seg_ms` (segmentação) | 15.563 | **15.564** | 15.567 |
| `t_digitos_ms` (classificador, 6 fatias, capturas com caixa) | 1.994 | 1.995 | 2.644 |
| `t_encode_ms` (JPEG) | 9 | 11 | 14 |
| `t_total_ms` (capturas com caixa; inclui a compressão e o envio serial da imagem de debug) | 17.739 | 17.838 | 18.720 |
| Processamento da leitura (`t_prep` + segmentação + `t_pos_seg` + dígitos, capturas com caixa) | 17.567 | **17.568** | 18.220 |
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
  Isto mostra consistência com a câmera parada, **não** acurácia: não há rótulo por captura. O firmware dessas
  capturas desenhava as linhas-guia no quadro antes de ler os dígitos (corrigido em 2026-11-18; ver
  `test_images/debug_ocr_esp32cam/README.md`), então as leituras foram feitas com essas linhas dentro das fatias.
- A temperatura do chip passou de 72 °C durante toda a sessão.

## Latência de inferência e decisão sobre o modelo (H2)

**Medido.** A segmentação leva 15.564 ms por captura (mediana de 61 capturas; mínimo 15.563, máximo 15.567)
e a leitura completa, 17.568 ms de processamento (segmentação mais classificador de dígitos, ~2,0 s; o `t_total_ms` de
17.838 ms inclui ainda a compressão e o envio serial da imagem de debug). O valor confirma os
~15,5 s do `ModeloEDataset/README.md` e é determinístico (variação de 4 ms), não ruído de medição.

**Relação com a H2.** A H2 ("o método de processamento local apresenta menor latência e maior valor de taxa de
pacotes entregues") compara fluxos, não etapas:

| Fluxo | Composição | Latência (despertar até o dado no PC) |
|---|---|---|
| Nuvem (imagem) | captura em ~0,7 s, 1º chunk em ~2,0 s e envio de 22 a 27 chunks, um a cada ~8,1 s (JPEG de 3,7 a 4,6 KB) | **mediana de 189 s** (173 a 214 s), **medido** em 30 leituras de `AUTO:30` (20 imagens completas; ver "Latência ponta a ponta e entrega do fluxo de imagem"). No teste curto anterior, com JPEG de ~3,0 KB (18 chunks), foram ≈ 141 s. A inferência na nuvem não está incluída |
| Local (OCR na borda), com segmentação | inferência de ~17,5 s mais 1 uplink de ~9 bytes | **18,84 s** (mediana; de 18,836 a 18,840 s), **medido** em 34 disparos de `AUTO:30`, dos quais 27 uplinks chegaram ao PC (ver "Latência ponta a ponta e entrega do fluxo de OCR"). O tempo acordado do ciclo inteiro, medido pelo INA219, é 19,45 s |
| Local (OCR na borda), modo ROI (adotado) | captura 0,24 s e classificador 1,92 s, mais 1 uplink de 9 bytes | **3,50 s** (mediana; de 3,496 a 3,580 s), **medido** em 29 despertares de `AUTO:30`, todos entregues (ver "Latência ponta a ponta do fluxo de OCR no modo ROI"). Energia: 0,175 mAh por leitura com o Radioenge em classe A (ver "Consumo dos dois fluxos com o Radioenge em classe A") |

**Decisão.**
- *Reduzir o modelo* (entrada menor, menos filtros, kernels otimizados): descartado. Com câmera fixa a
  instalação não precisa de uma segmentação a cada leitura, e a rede é fraca (Dice 0,39, IoU 0,28), então
  encolhê-la ou melhorá-la não melhora a leitura.
- *Revisar a H2*: não é necessário pela latência. Mesmo com a segmentação a cada leitura, a latência medida do
  fluxo local (18,84 s) é cerca de 1/10 da do fluxo de imagem (mediana medida de 189 s). A outra metade da H2, a
  taxa de pacotes entregues, depende da métrica (ver a seção de entrega do fluxo de OCR).
- **Adotada:** manter o pipeline CNN Simples e retirar a segmentação do firmware com uma ROI calibrada na instalação
  (ver a decisão no README da raiz). Implementada em 2026-11-18: com ROI na NVS, o `transmissor_ocr_esp32cam` não
  carrega nem roda a segmentação. O classificador leva 1,92 s para as 6 fatias na placa (33 quadros mandados pelo PC,
  `experimentos/hibrido_a_b/resultados/PLACA_X_PC.md`). A latência ponta a ponta nesse modo foi medida em 2026-11-18:
  **3,50 s** (mediana), contra 18,84 s com a segmentação (ver "Latência ponta a ponta do fluxo de OCR no modo ROI").
  A energia nesse modo foi medida em 2026-11-19, já com o Radioenge em classe A: **0,175 mAh por leitura** com sleep de
  30 s (ver "Consumo dos dois fluxos com o Radioenge em classe A"). As seções de energia de 27/10 abaixo são do modo com
  segmentação e do Radioenge em classe C.

**Resultado para a H2.** A latência está confirmada com folga (18,84 s contra 189 s com a segmentação; 3,50 s no modo ROI). A taxa de entrega depende da
métrica: por **leitura** entregue o fluxo local foi melhor (27 de 34, 79,4%, contra 20 de 30, 66,7%, na imagem), mas
a diferença não é estatisticamente distinguível com essas amostras (Fisher exato, p = 0,27); por **pacote**, o fluxo
de imagem foi melhor (699 de 713, 98,0%, contra 79,4%). Ver as seções de entrega abaixo. Nas corridas de 2026-11-19
(Radioenge em classe A, OCR no modo ROI), o OCR entregou 29 de 30 leituras (96,7%) e a imagem 24 de 30 (80%; 98,9% dos
pacotes); a diferença por leitura também não é estatisticamente distinguível (Fisher exato, p = 0,10). O
`transmissao_ocr.csv` ainda não foi gerado.

**Duas corridas do fluxo de imagem.** Houve duas corridas de 30 imagens em 2026-10-27, com números diferentes:

| Corrida | Disparo | Imagens completas | PDR por pacote | Latência (mediana) |
|---|---|---|---|---|
| `latencia_ponta_a_ponta.csv` (09:34 a 11:20) | `AUTO:30`: o nó acorda do deep sleep, captura e envia | 20 de 30 | 98,0% (699/713) | 189 s, a partir do boot |
| `transmissao.csv` (14:59 a 16:44) | nó sempre ligado, o PC manda `CAPTURE` | 21 de 30 | 98,7% (749/759) | 197 s, a partir do comando |

Os números de latência e entrega do fluxo de imagem vêm da primeira, porque ela usa o mesmo disparo (despertar do deep sleep) que a corrida do OCR
(`latencia_ocr.csv`). A segunda não é uma repetição da mesma medição (o disparo e o marco inicial da latência são
outros) e serve para conferir o PDR por pacote com o `reconstrutor.py`. A diferença de 8 s na latência e de 1 imagem
completa não foi investigada.

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
`python medicoes/corrente.py analisar medicoes/corrente/auto30_imagem.csv --offset-ma 0.0 --min-sleep-s 12 --max-amostras 685000 --excluir-ciclos 28`
(com `--min-sleep-s 5` três picos isolados de uma amostra, ≈ 61 mA, partem o sleep e geram ciclos falsos).
O ciclo 28 da tabela do `analisar` não é uma leitura: o nó acordou por 0,97 s (pico de 190 mA) e voltou a dormir
sem enviar nada (coincide com a linha vazia de 11:10:24 em `latencia_ponta_a_ponta.csv`; causa não investigada).
Ele foi **excluído**, o que deixa **30 ciclos completos**.

| Grandeza | Valor (n = 30 ciclos) |
|---|---|
| `mAh por leitura` | **4,64** (mediana 4,65; desvio 0,24; de 4,26 a 5,24) |
| Corrente média acordado | ≈ 84,5 mA (de 81 a 86 mA por ciclo); picos de TX de 207 a 220 mA |
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
a H2 compara com o fluxo local, que envia 1 pacote por leitura (medido na seção do fluxo de OCR).

## Consumo do fluxo de OCR na borda (32 ciclos)

`Rede/transmissor_ocr_esp32cam` em `AUTO:30`, `JANELA_STOP_MS = 0`, mesma bancada e mesmo sleep de 30 s do fluxo de
imagem (`corrente/auto30_ocr.csv`, 2026-10-27, 169.738 amostras em 1.697 s, tensão média 4,954 V). Análise com
`python medicoes/corrente.py analisar medicoes/corrente/auto30_ocr.csv --offset-ma 0.0 --min-sleep-s 12`.

| Grandeza | Valor (n = 32 ciclos) |
|---|---|
| `mAh por leitura` | **0,824** (desvio 0,014) |
| Tempo acordado | **19,45 s** na maioria dos ciclos (início, captura, modelos, segmentação, dígitos e envio) |
| Corrente média acordado | ≈ 114 mA, com picos de TX de 206 a 227 mA |
| Corrente em sleep | ≈ 25,2 mA (de 24,1 a 26,3), **incluindo o Radioenge** |
| Período do ciclo | 49,1 s (≈ 19,5 s acordado + ≈ 29,6 s de sleep) |

Os ciclos 24 e 25 da tabela do `analisar` (0,778 e 0,872 mAh) têm a fronteira deslocada por um pico isolado de uma
amostra e somam 1,650 mAh, ou seja, 0,825 cada. O tempo acordado de 19,45 s é o ciclo inteiro do nó, medido pelo
INA219; a latência medida no PC (disparo até o dado no receptor) está na seção seguinte.

**Sobre os gráficos** (`corrente/auto30_imagem.png` e `corrente/auto30_ocr.png`): cada um tem a média de 1 s da corrida
inteira (em cima) e um ciclo ampliado com as amostras de 100 Hz (embaixo). Antes o gráfico desenhava as 700 mil amostras
da corrida de imagem como uma linha só, e os picos de TX (a cada ≈ 8 s) preenchiam tudo de azul, parecendo corrente alta
o tempo todo; na verdade a corrente acordado fica em ≈ 80 mA (mediana) e só 2,5% do tempo passa de 150 mA, tanto na
imagem quanto no OCR. Gerar os gráficos precisa de `matplotlib` e `numpy`, que não estão no venv do projeto.

### Comparação dos dois fluxos (mesmo sleep de 30 s; 27/10, Radioenge em classe C)

| | Imagem (nuvem) | OCR na borda |
|---|---|---|
| `mAh por leitura` | 4,64 | **0,824** (5,6 vezes menos) |
| Tempo acordado | 189,9 s (173 a 219 s) | 19,45 s |
| Corrente média acordado | ≈ 84,5 mA (espera entre chunks) | ≈ 114 mA (inferência) |
| Corrente em sleep (com Radioenge) | ≈ 23,7 mA | ≈ 25,2 mA |
| Período do ciclo | 218,5 s | 49,1 s |
| Latência ponta a ponta vista pelo PC (mediana) | 189,1 s (n = 20 completas) | **18,84 s** (n = 27 recebidas) |
| Leituras entregues (imagem completa / uplink recebido) | 20 de 30 (66,7%) | 27 de 34 (79,4%) |
| Pacotes entregues | 699 de 713 (98,0%) | 27 de 34 (79,4%) |
| Carga acordado por leitura, sem contar o sleep | 4,46 mAh | **0,62 mAh** (7,2 vezes menos) |
| Autonomia, bateria hipotética de 2000 mAh, ciclo de 30 s de sleep | 1,1 dia | 1,4 dia |

O que a tabela mede de cada fluxo é o **custo de uma leitura**: 4,64 contra 0,824 mAh (5,6 vezes) com o sleep de 30 s, ou
4,46 contra 0,62 mAh (7,2 vezes) só do tempo acordado. Isso é o que a H3 compara durante a transmissão. A autonomia depende
também do sleep, como mostra a próxima seção.

### Autonomia: o piso de sleep esconde a diferença entre os fluxos

> **Atualização de 2026-11-19:** o piso de 24 mA era o Radioenge em **classe C**, recebendo o tempo todo. Em classe A o
> sleep caiu para ≈ 6 mA; a autonomia recalculada está em "Consumo dos dois fluxos com o Radioenge em classe A". O texto
> abaixo é a análise de 27/10.

Em sleep o protótipo consome **≈ 24 mA**, e isso é um defeito da bancada, não uma característica dos fluxos: o ESP32 em
deep sleep gasta microampères, mas o Radioenge continua ligado (o firmware só dorme o ESP32), e a placa ESP32-CAM tem
regulador, LED e a câmera em power-down. A medição de sleep inclui tudo isso, e **ainda não foi separada** (falta medir o
`SLEEP:60` com o Radioenge desconectado). Com intervalos longos, esses 24 mA dominam a conta dos dois fluxos: em 1 h são
22,7 mAh de sleep, contra 4,5 mAh (imagem) ou 0,6 mAh (OCR) da leitura. Por isso, com o piso medido, a autonomia dos dois
fica próxima (3,1 e 3,4 dias), embora uma leitura de imagem custe 7 vezes mais.

Autonomia estimada para a bateria hipotética de 2000 mAh, variando o piso de sleep (mesmo valor nos dois fluxos, para
isolar o efeito do fluxo). **Só a linha de 24 mA usa um valor medido; os demais pisos são hipóteses.**

| Intervalo | Piso de sleep | Imagem | OCR | OCR / imagem |
|---|---|---|---|---|
| 10 min | 24 mA (medido) | 1,9 dia | 3,1 dias | 1,6× |
| 10 min | 5 mA | 2,8 dias | 9,8 dias | 3,5× |
| 10 min | 1 mA | 3,0 dias | 17,8 dias | 5,9× |
| 10 min | 0,1 mA | 3,1 dias | 21,9 dias | 7,0× |
| 1 h | 24 mA (medido) | 3,1 dias | 3,4 dias | 1,1× |
| 1 h | 5 mA | 9,1 dias | 14,9 dias | 1,6× |
| 1 h | 1 mA | 15,4 dias | 51,7 dias | 3,4× |
| 1 h | 0,1 mA | 18,3 dias | 116,1 dias | 6,3× |

Cálculo: `mAh por leitura = corrente acordado × tempo acordado + piso de sleep × (intervalo − tempo acordado)`, com 84,5 mA e
189,9 s (imagem) e 114,4 mA e 19,45 s (OCR); o modelo reproduz os 4,64 e os 0,824 mAh medidos com o sleep de 30 s. Os
1,1 e 1,4 dia da tabela anterior usam o sleep medido em cada corrida (23,7 e 25,2 mA); a diferença entre corridas
também explica por que a linha de 1 h dava 3,1 e 3,2 dias antes e agora 3,1 e 3,4.

**Para a H3**, o resultado é: por leitura, o fluxo de imagem gasta 5,6 a 7,2 vezes mais energia, e o efeito sobre a
autonomia vai de pequeno (1,1× em 1 h, com o piso medido) a grande (6× com piso de 0,1 mA) conforme o piso de sleep. Só
dá para afirmar a autonomia real depois de medir o sleep sem o Radioenge e com o regulador que o campo usará.

## Latência ponta a ponta e entrega do fluxo de OCR (34 leituras)

`python medicoes/latencia_ponta_a_ponta.py auto --n 34 --fluxo ocr --csv medicoes/latencia_ocr.csv --debug`, com o nó em
`AUTO:30` (2026-10-27, 12:59 a 13:27), câmera fixa. Foram 34 disparos e 27 uplinks decodificados no PC.

| Grandeza | Valor |
|---|---|
| Leituras entregues | **27 de 34 (79,4%)**; 7 perdidas (posições 9, 16, 17, 21, 27, 33 e 34) |
| Latência ponta a ponta (n = 27) | **mediana 18.838 ms**, de 18.836 a 18.840 ms (desvio 0,9 ms) |
| Disparo até a linha `[ocr] leitura=` | 18.195 ms (o OCR), mais ≈ 0,64 s até o uplink aparecer no PC |
| Tempos do nó (`[CICLO_FIM]`) | início 1.189 ms, segmentação ≈ 15.537 ms, dígitos ≈ 1.965 ms |
| Caixa achada | 27 de 27 uplinks recebidos com `achou_caixa=1` |
| RSSI médio | de −31 a −27 dBm (sinal muito forte) |

- **A latência é determinística** (desvio de ~1 ms): é a inferência (≈ 17,5 s) mais o início, sem nada de rede que
  varie. O modelo atual de segmentação leva 15.537 ms, praticamente o mesmo dos 15.564 ms do modelo antigo.
- **Perdas com sinal forte.** Com RSSI de −27 a −31 dBm não é falta de sinal. Nos dois ciclos perdidos que aparecem
  no log (33 e 34) o nó registrou `AT_TX_OK` e `falhas=0`: o Radioenge aceitou o envio e o receptor não o entregou ao PC.
  A causa não foi estabelecida. Uma hipótese, **não testada**, é que o primeiro uplink depois do despertar do deep sleep
  se perde mais: no fluxo de imagem, em 3 de 30 leituras (10%) o primeiro chunk recebido só chegou aos 10 a 11 s
  (o chunk inicial parece ter se perdido), contra 2,0% de perda no total; no fluxo de OCR todo uplink é o primeiro depois
  do despertar. As amostras são pequenas demais para afirmar. Um teste direto seria mandar dois `AT+SENDB` seguidos
  logo após o despertar e comparar as perdas. Nas corridas de 2026-11-19 a hipótese **não se confirmou**: o chunk 0
  chegou nas 30 imagens e o OCR perdeu 1 de 30 uplinks (ver "Consumo dos dois fluxos com o Radioenge em classe A").
- **Sem reenvio.** O nó dorme depois de um único envio, então um uplink perdido é uma leitura perdida. Isso favorece
  uma estratégia de reenvio ou de confirmação (uplink confirmado) como trabalho futuro.
- **A leitura varia entre ciclos** (13 valores distintos em 27 recebidas, com a câmera fixa). Não há rótulo, então
  isto não é um teste de acurácia; pode ser a câmera acordando fria, sem quadros de aquecimento, e não foi investigado.
- **Tentativa anterior sem dados.** Em `latencia_ocr_tentativa1.csv` o nó e o PC viram os 27 disparos (12:25 a 12:46), mas
  o receptor não entregou nenhum uplink ao PC até as 12:46:19, e a causa não foi identificada (o script dessa tentativa
  ainda não tinha o `--debug`). Essas 28 linhas **não entram** nas estatísticas acima.

## Latência ponta a ponta do fluxo de OCR no modo ROI (30 leituras)

`python medicoes/latencia_ponta_a_ponta.py auto --n 30 --fluxo ocr --iniciar-auto 30 --csv medicoes/latencia_ocr_roi.csv --debug`
(2026-11-18 23:58 a 2026-11-19 00:14), com o `transmissor_ocr_esp32cam` em modo ROI (caixa 21,69,151,95, N = 6, face
14–74 %, sem realce), câmera fixa sobre o hidrômetro. O script reiniciou a placa e mandou `AUTO:30`.

| Grandeza | Valor |
|---|---|
| Leituras entregues | **30 de 30** |
| Latência ponta a ponta (29 despertares do deep sleep) | **mediana 3.499 ms**, de 3.496 a 3.580 ms (desvio 15 ms) |
| Disparo até a linha `[ocr] leitura=` | 2.856 ms (mediana), mais ≈ 0,64 s até o uplink aparecer no PC |
| Tempos do nó (`[CICLO_FIM]`) | captura 239 ms, segmentação 0 ms, dígitos 1.916 ms |
| RSSI médio | de −60 a −59 dBm |

- O 1º disparo (2.838 ms) foi o `[auto] ligado`, logo depois do `AUTO:30`, sem o boot do despertar; fica no CSV, mas
  fora da mediana para comparar com a medição de 27/10, que conta a partir do `[boot] causa=timer`.
- Contra os 18.838 ms com a segmentação, a latência caiu 15,3 s (5,4 vezes menor). A diferença é a segmentação
  (≈ 15,5 s) que deixou de rodar; o classificador e o uplink levam o mesmo tempo de antes.
- **As leituras não valem como resultado de acurácia.** O foco era a latência: a leitura do hidrômetro e as imagens
  não foram conferidas nem salvas. Os uplinks trouxeram `000200` (20), `000000` (7) e `000220` (3). A acurácia do modo ROI é a das 30 fotos
  de `dados/teste/` (25/30) e da comparação placa × PC (33/33 iguais).
- **Sem perdas** nesta corrida (30 de 30, com RSSI de −60 dBm), contra 27 de 34 em 27/10 (RSSI de −30 dBm). Com
  amostras deste tamanho isso não basta para concluir nada sobre a causa das perdas de 27/10.

## Consumo dos dois fluxos com o Radioenge em classe A (2026-11-19)

**O que mudou na bancada.** Até 27/10 o Radioenge estava em **classe C** (`AT+CLASS=?` respondia `C`). Pelo manual
(seção 5.2.4), em classe C o módulo **não entra em baixo consumo**: fica recebendo o tempo todo (20 mA de recepção a 3,3 V,
especificações do manual), inclusive enquanto o ESP32 dorme. Em classe A ele desliga o rádio sozinho depois das janelas de
recepção de cada envio (1,8 µA em modo suspenso). O enlace não usa downlink (ABP, `AT+CFM=0`, keepalive desligado), então
a classe A não tira nada do sistema. O módulo foi passado para classe A com `AT+CLASS=A` (resposta `AT_OK`); a configuração
**fica gravada no módulo**: continuou `A` depois de uma queda de energia que reiniciou o Radioenge. O manual não tem outro
comando de sleep; a classe A é o modo de baixo consumo do RD49C.

Medição: `corrente.py capturar` (INA219 no Uno, 100 Hz) junto com `latencia_ponta_a_ponta.py auto --n 30 --iniciar-auto 30`
(que manda o `AUTO:30` e registra a entrega), mesma bancada e mesmo sleep de 30 s de 27/10. Análise com
`python medicoes/corrente.py analisar <csv> --offset-ma 0.0 --min-sleep-s 12`. Uma primeira corrida do fluxo de imagem
foi interrompida por uma queda de energia do nó às 12:19 (os fios da bancada se mexeram); ela está em
`corrente/descartadas/` e **não entra nas estatísticas**.

| | Imagem (`transmissor_esp32cam`) | OCR na borda, modo ROI (`transmissor_ocr_esp32cam`) |
|---|---|---|
| Arquivos | `corrente/auto30_imagem_classe_a.csv`, `latencia_imagem_classe_a.csv` | `corrente/auto30_ocr_roi_classe_a.csv`, `latencia_ocr_roi_classe_a.csv` |
| Ciclos analisados | 29 (30 leituras) | 29 (30 leituras) |
| `mAh por leitura` (sleep de 30 s) | **2,91** (desvio 0,14) | **0,175** (desvio 0,004): **16,7 vezes menos** |
| Carga acordado por leitura, sem o sleep | 2,87 mAh | **0,129 mAh** (22 vezes menos) |
| Tempo acima do limiar de sleep | 147,6 s (135 a 160 s) | 6,49 s (ESP32 ≈ 4,1 s + janelas de recepção do Radioenge) |
| Corrente média nesse tempo | 69,9 mA | 71,4 mA |
| **Corrente em sleep** | **≈ 6,3 mA** | **≈ 6,1 mA** |
| Período do ciclo | 174,8 s | 33,8 s |
| JPEG / chunks | 2,9 a 3,4 KB, 17 a 20 chunks (mediana 19) | — (1 uplink de 9 bytes) |
| Latência ponta a ponta (mediana) | 148,3 s (132 a 157 s, n = 24 completas) | 3,50 s (3,501 a 3,505 s, n = 28 despertares) |
| Leituras entregues | 24 de 30 (80%) | 29 de 30 (96,7%) |
| Pacotes entregues | 551 de 557 (98,9%) | 29 de 30 |
| RSSI (mediana) | −53 dBm | −49 dBm |

- **O sleep caiu de ≈ 24 para ≈ 6 mA** nos dois fluxos (eram 23,7 e 25,2 mA em 27/10). A diferença, ≈ 18 mA, bate com
  os 20 mA de recepção contínua da classe C no manual. Os ≈ 6 mA que sobram **não foram separados** por medição; o
  manual dá 1,8 µA para o Radioenge suspenso, então eles devem ser da placa ESP32-CAM (regulador, LED, câmera em
  power-down), mas isso ainda é inferência.
- **A corrente acordado também caiu** no fluxo de imagem (69,9 contra 84,5 mA em 27/10): entre um chunk e outro o
  Radioenge não fica mais recebendo.
- **Perfil de um ciclo do OCR** (médias de 250 ms): o ESP32 fica acordado ≈ 4,1 s (90 a 160 mA), dorme, e o Radioenge
  ainda abre as janelas de recepção da classe A (um pico curto ≈ 1 s depois do envio e ≈ 1 s a 24 mA ≈ 2 s depois)
  antes de cair para o piso. Por isso o "tempo acima do limiar" (6,49 s) é maior que o tempo acordado do ESP32.
- **Imagem menor que a de 27/10.** A câmera mudou de posição (agora perto do mostrador) e os JPEGs têm 2,9 a 3,4 KB
  (17 a 20 chunks) contra 3,7 a 4,6 KB (22 a 27 chunks). A carga cresce linearmente com os chunks: **0,157 mAh e 8,1 s
  por chunk** (ajuste nos 29 ciclos, resíduo de 0,016 mAh). Com 22 a 27 chunks, o mesmo fluxo gastaria **3,5 a 4,2 mAh**
  por leitura (estimativa), contra 4,64 mAh medidos em 27/10 em classe C. A razão imagem/OCR depende do tamanho da imagem.
- **Comparação com 27/10, para o OCR:** 0,824 → 0,175 mAh por leitura. Mudaram duas coisas juntas: a segmentação saiu
  (≈ 15,5 s a menos acordado) e o sleep caiu (classe A). A primeira explica a maior parte da carga acordado; a segunda,
  o sleep.
- **Chunks perdidos.** As 6 imagens incompletas perderam **um** chunk cada (índices 5, 3, 13, 1, 9 e 1, conferidos
  decodificando os uplinks recebidos). O chunk 0, o primeiro depois do despertar, chegou nas 30 leituras. Isso **não
  apoia** a hipótese de que o primeiro uplink depois do despertar se perde mais (seção do fluxo de OCR acima). A
  perda por pacote (1,1%) é parecida com a de 27/10 (2,0%), mas no fluxo de imagem um chunk perdido perde a leitura.

**Autonomia com o piso medido em classe A** (bateria hipotética de 2000 mAh, piso de 6,2 mA, média das duas corridas;
mesmo cálculo da seção de autonomia acima, com 69,9 mA × 147,6 s para a imagem e 71,4 mA × 6,49 s para o OCR):

| Intervalo | Imagem (17 a 20 chunks) | OCR, modo ROI | OCR / imagem | Com o piso de 24 mA de 27/10 (imagem / OCR) |
|---|---|---|---|---|
| 10 min | 3,8 dias | 12,1 dias | 3,2× | 1,9 / 3,1 dias |
| 1 h | 9,5 dias | 13,2 dias | 1,4× | 3,1 / 3,4 dias |

O modelo reproduz as cargas medidas com o sleep de 30 s (2,92 e 0,180 mAh, contra 2,91 e 0,175). Com o piso de ≈ 6 mA,
o sleep ainda domina em intervalos longos (em 1 h são ≈ 6,2 mAh de sleep, contra 2,9 mAh de uma leitura de imagem e
0,13 mAh de uma de OCR); o próximo ganho de autonomia está na placa (os ≈ 6 mA restantes), não no fluxo.

## Enlace do fluxo de imagem: PDR, tempo de rádio e latência (`transmissao.csv`, 30 envios)

`python Rede/reconstrutor.py --tx --envios 30 --distancia 2 --rotulo "bancada, imagem"` (2026-10-27, 14:59 a 16:44), com o nó
`transmissor_esp32cam` sempre ligado e o PC mandando `CAPTURE`. Enlace AU915, canal 64, SF8/BW 500 kHz, 175 B por bloco, 7 s
entre blocos, nó e receptor a ≈ 2 m. Comando de PDR e colunas em [`medir_transmissao.md`](medir_transmissao.md).

| Grandeza | Valor (30 envios) |
|---|---|
| Imagens completas | **21 de 30 (70,0%)**; as 9 incompletas perderam 1 ou 2 blocos cada |
| PDR do enlace (blocos únicos / blocos enviados) | **749 / 759 = 98,7%** |
| PDR da leitura (blocos únicos / total da imagem) | mediana 1,00, média 0,99, mínimo 0,92 |
| Tempo de rádio por envio (**calculado**, Semtech AN1200.13) | mediana 3,41 s (2,58 a 3,48 s) |
| Latência até a imagem completa (n = 21) | **mediana 197,1 s**, de 148,1 a 204,9 s |
| Blocos por imagem / JPEG | 19 a 26 (mediana 25,5) / 3.323 a 4.468 bytes (mediana 4.379) |
| RSSI médio | de −33,5 a −31,8 dBm |
| Tentativas / ocupado / falhas no nó | 759 / 0 / 0 |

- **Conferência:** o nó informou `[envio] concluido: N ok, 0 falhas` em todos os envios; as perdas estão na recepção. Dos
  751 frames recebidos, 749 viraram blocos novos, 1 era de outro dispositivo (DevAddr diferente, ignorado) e 1 chegou com o
  cabeçalho corrompido (`total` divergente). O MIC não é validado (não temos a chave de rede), então um frame com bits
  errados que passe o CRC do rádio entra como bloco; confira a imagem antes de usá-la.
- **A imagem versionada:** as 21 imagens completas estão em `imagens/`, por exemplo `20261027_145936_bancada-imagem_L60485.jpg`
  (160×120, mostrador do hidrômetro legível), cada uma com o SHA-256 em `transmissao.csv` e o log em
  `logs/20261027_145936_bancada-imagem/`.
- **Perdas no último bloco:** dos 10 blocos perdidos, 4 foram o último da imagem, 2 o primeiro, 1 o penúltimo e 3 do meio.
  Pelo acaso seriam ≈ 0,4 no último (p < 0,001, binomial simples). A perda do último não aparece como lacuna de `FCnt`
  (não há frame depois dele). O nó não faz nada depois do último envio além de imprimir `concluido`; a causa não foi
  investigada.
- **Janelas de silêncio do receptor (execuções anteriores).** Entre 12:25 e 14:42 o receptor ficou mudo por 15 a 25 min
  seguidos, enquanto o nó registrava `AT_TX_OK` em todos os blocos: 125 blocos consecutivos perdidos das 14:18 às 14:42,
  além de rajadas de 15, 14, 10, 8 e 7. Nelas, 185 dos 191 blocos perdidos estavam em rajadas, e as perdas isoladas eram
  1,9% (a mesma de 09:34 a 11:20). A corrida de `transmissao.csv` (14:59 a 16:44) **não teve nenhuma janela**, então a
  hipótese de uma recorrência de ≈ 1 h não se confirmou. A causa não foi identificada. As 21 linhas dessas execuções
  estão em `transmissao_execucoes_anteriores.csv` e não entram nas estatísticas; os logs e as imagens delas foram
  apagados.

## Pendente

- **Piso de sleep (vale para os dois fluxos):** com o Radioenge em classe A o sleep caiu de ≈ 24 para ≈ 6 mA
  (2026-11-19). Falta separar o que sobra (`SLEEP:60` com o Radioenge desconectado) e ver o que a placa ESP32-CAM gasta
  (regulador, LED). Também: autonomia com a bateria real e o intervalo de campo.
- **Consumo, fluxo de imagem:** investigar a causa do despertar sem envio (ciclo 28) e do JPEG maior. Procedimento em
  [`medir_corrente.md`](medir_corrente.md).
- **Perdas de uplink nos dois fluxos:** em 27/10, 20,6% das leituras do OCR e 33% das imagens não chegaram ao PC; em
  2026-11-19, 1 de 30 (OCR) e 6 de 30 (imagem, um chunk perdido em cada). A causa não foi investigada; a hipótese do
  primeiro uplink depois do despertar não se confirmou em 2026-11-19. Falta também a estratégia de reenvio, que não
  existe em nenhum dos dois firmwares no modo autônomo.
- **Deep sleep:** implementado em `Rede/transmissor_esp32cam` (comandos `AUTO`, `STOP`, `SLEEP`) e em
  `Rede/transmissor_ocr_esp32cam`. No de imagem, os 30 ciclos de `AUTO:30` (acima) mostram a corrente caindo de
  ≈ 84,5 mA acordado para ≈ 23,7 mA dormindo em todos os ciclos, e o teste curto de 4 ciclos confirmou
  `DEEPSLEEP_RESET` e o contador de ciclos na memória RTC. No de OCR, os 32 ciclos de `AUTO:30` mostram o mesmo
  padrão (≈ 114 mA acordado, ≈ 25 mA dormindo). Com o Radioenge em classe A (2026-11-19), o sleep dos dois cai para
  ≈ 6 mA. Roteiro em [`teste_deep_sleep.md`](teste_deep_sleep.md).
- **Taxa de pacotes entregues (H2):** medida nos dois fluxos pelos CSVs de latência (27/10: imagem com 98,0% dos
  pacotes e 20 de 30 imagens, OCR com 79,4% das leituras; 2026-11-19: imagem com 98,9% e 24 de 30, OCR com 29 de 30) e,
  no fluxo de imagem, pelo `transmissao.csv` (98,7% dos pacotes, 21 de 30 imagens). Falta o `transmissao_ocr.csv` (OCR), gerado pelo `reconstrutor.py --tx --fluxo ocr`, ainda sem medições
  em placa; ver [`medir_transmissao.md`](medir_transmissao.md).
- **Janelas de silêncio do receptor:** a causa não foi identificada (ver "Enlace do fluxo de imagem").
- **Perda do último bloco:** 4 dos 10 blocos perdidos na corrida de `transmissao.csv` foram o último da imagem
  (esperado ≈ 0,4); a causa não foi investigada.
