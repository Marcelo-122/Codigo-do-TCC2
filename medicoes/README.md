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
| `corrente/auto30_imagem.csv` (+ `.png`) | `Rede/transmissor_esp32cam` com a câmera desligada após a captura, `AUTO:30` | 30 ciclos válidos (31 despertares com 1 falso) | mesmo formato; 2026-10-27 a partir das 09:29. O arquivo tem 1.041.066 amostras (≈ 10.410 s), mas a análise usa as primeiras 685.000 (6.850 s, até 11:22); o resultado é o mesmo com o arquivo inteiro |
| `corrente/auto30_ocr.csv` (+ `.png`) | `Rede/transmissor_ocr_esp32cam`, `AUTO:30` | 30 ciclos | mesmo formato; 159.035 amostras em 1.590 s, 2026-10-27 12:22 a 12:48 |
| `latencia_ponta_a_ponta.csv` | mesmo firmware, medido no PC por `latencia_ponta_a_ponta.py auto` | 31 disparos (30 com envio) | uma linha por leitura: chunks enviados/recebidos, bytes do JPEG, RSSI, tempo até o 1º/último chunk e até a imagem completa |
| `latencia_ocr.csv` | `Rede/transmissor_ocr_esp32cam`, medido no PC por `latencia_ponta_a_ponta.py auto --fluxo ocr` | 34 disparos (27 uplinks recebidos) | uma linha por leitura: RSSI, tempo até a linha `[ocr] leitura=` e até o dado no PC, dígitos lidos, `achou_caixa`; 2026-10-27, 12:59 a 13:27 |
| `latencia_ocr_tentativa1.csv` | mesmo firmware, primeira tentativa | 28 disparos (1 uplink recebido) | tentativa em que o receptor não entregou nenhum uplink ao PC durante 22 min (12:25 a 12:46); **não entra nas estatísticas**, fica como registro |
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
| Modelos | `modelo.h` (segmentação, `modelo_esp32.tflite`) e `modelo_digito.h` (classificador). **Atenção:** o `modelo.h` do repositório foi reexportado em 2026-10-25 (12.080 bytes, com os operadores `SHAPE`, `STRIDED_SLICE` e `PACK`) e **não é o que rodou nas 61 capturas**: o firmware de debug daquelas capturas só registrava 4 operadores, que o modelo atual não cabe (o de 11.128 bytes em `legado/` tem só esses 4). Latência, arena e temperatura desta tabela valem para o modelo antigo e serão refeitos com o atual no fluxo de OCR |
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
| Local (OCR na borda) | inferência de ~17,8 s mais 1 uplink de ~9 bytes | **18,84 s** (mediana; de 18,836 a 18,840 s), **medido** em 34 disparos de `AUTO:30`, dos quais 27 uplinks chegaram ao PC (ver "Latência ponta a ponta e entrega do fluxo de OCR"). O tempo acordado do ciclo inteiro, medido pelo INA219, é 19,45 s |

**Decisão.**
- *Reduzir o modelo* (entrada menor, menos filtros, kernels otimizados): descartado. Com câmera fixa a
  instalação não precisa de uma segmentação a cada leitura, e a rede é fraca (Dice 0,39, IoU 0,28), então
  encolhê-la ou melhorá-la não melhora a leitura.
- *Revisar a H2*: não é necessário pela latência. Mesmo com a segmentação a cada leitura, a latência medida do
  fluxo local (18,84 s) é cerca de 1/10 da do fluxo de imagem (mediana medida de 189 s). A outra metade da H2, a
  taxa de pacotes entregues, depende da métrica (ver a seção de entrega do fluxo de OCR).
- **Adotada:** manter o Pipeline B e retirar a segmentação do firmware com uma ROI calibrada na instalação
  (ver a decisão no README da raiz). Efeito esperado: leitura em ≈ 2 s por leitura. É uma **estimativa**: o
  firmware ainda não foi alterado.

**Resultado para a H2.** A latência está confirmada com folga (18,84 s contra 189 s). A taxa de entrega depende da
métrica: por **leitura** entregue o fluxo local foi melhor (27 de 34, 79,4%, contra 20 de 30, 66,7%, na imagem), mas
a diferença não é estatisticamente distinguível com essas amostras (Fisher exato, p = 0,27); por **pacote**, o fluxo
de imagem foi melhor (699 de 713, 98,0%, contra 79,4%). Ver as seções de entrega abaixo. `transmissao.csv` e
`transmissao_ocr.csv` (PDR com FCnt e tempo de rádio, pelo `reconstrutor.py`) ainda não foram gerados.

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
a H2 compara com o fluxo local, que envia 1 pacote por leitura (medido na seção do fluxo de OCR).

## Consumo do fluxo de OCR na borda (30 ciclos)

`Rede/transmissor_ocr_esp32cam` em `AUTO:30`, `JANELA_STOP_MS = 0`, mesma bancada e mesmo sleep de 30 s do fluxo de
imagem (`corrente/auto30_ocr.csv`, 2026-10-27, 159.035 amostras em 1.590 s, tensão média 4,955 V). Análise com
`python medicoes/corrente.py analisar medicoes/corrente/auto30_ocr.csv --offset-ma 0.0 --min-sleep-s 12`.

| Grandeza | Valor (n = 30 ciclos) |
|---|---|
| `mAh por leitura` | **0,825** (desvio 0,014) |
| Tempo acordado | **19,45 s** na maioria dos ciclos (início, captura, modelos, segmentação, dígitos e envio) |
| Corrente média acordado | ≈ 114 mA, com picos de TX de 206 a 227 mA |
| Corrente em sleep | ≈ 25,2 mA (de 24,1 a 26,3), **incluindo o Radioenge** |
| Período do ciclo | 49,1 s (≈ 19,5 s acordado + ≈ 29,6 s de sleep) |

Os ciclos 24 e 25 da tabela do `analisar` (0,778 e 0,872 mAh) têm a fronteira deslocada por um pico isolado de uma
amostra e somam 1,650 mAh, ou seja, 0,825 cada. O tempo acordado de 19,45 s é o ciclo inteiro do nó, medido pelo
INA219; a latência medida no PC (disparo até o dado no receptor) está na seção seguinte. O gráfico `corrente/auto30_ocr.png` foi gerado fora do venv (o venv do projeto não tem `matplotlib`).

### Comparação dos dois fluxos (mesmo sleep de 30 s)

| | Imagem (nuvem) | OCR na borda |
|---|---|---|
| `mAh por leitura` | 4,64 | **0,825** (5,6 vezes menos) |
| Tempo acordado | 189,9 s (173 a 219 s) | 19,45 s |
| Corrente média acordado | ≈ 84,5 mA (espera entre chunks) | ≈ 114 mA (inferência) |
| Corrente em sleep (com Radioenge) | ≈ 23,7 mA | ≈ 25,2 mA |
| Período do ciclo | 218,5 s | 49,1 s |
| Latência ponta a ponta vista pelo PC (mediana) | 189,1 s (n = 20 completas) | **18,84 s** (n = 27 recebidas) |
| Leituras entregues (imagem completa / uplink recebido) | 20 de 30 (66,7%) | 27 de 34 (79,4%) |
| Pacotes entregues | 699 de 713 (98,0%) | 27 de 34 (79,4%) |
| Autonomia, bateria hipotética de 2000 mAh | 1,1 dia | 1,4 dia |
| Autonomia a cada 10 min (extrapolação) | 1,9 dia | 3,0 dias |
| Autonomia a cada 1 h (extrapolação) | 3,1 dias | 3,2 dias |

As linhas de extrapolação **não foram medidas**: usam `mAh = corrente acordado × tempo acordado + corrente de sleep ×
(intervalo − tempo acordado)` com os valores medidos acima (o modelo reproduz os 4,64 e os 0,825 medidos). O resultado
para a H3: por leitura, o fluxo de imagem gasta 5,6 vezes mais; com leituras a cada poucos minutos isso vira uma
vantagem grande de autonomia, mas o piso de ≈ 24 mA do sleep (que inclui o Radioenge e ainda não foi separado) domina
quando o intervalo chega a 1 h, e a diferença cai para ≈ 5%.

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
  logo após o despertar e comparar as perdas.
- **Sem reenvio.** O nó dorme depois de um único envio, então um uplink perdido é uma leitura perdida. Isso favorece
  uma estratégia de reenvio ou de confirmação (uplink confirmado) como trabalho futuro.
- **A leitura varia entre ciclos** (13 valores distintos em 27 recebidas, com a câmera fixa). Não há rótulo, então
  isto não é um teste de acurácia; pode ser a câmera acordando fria, sem quadros de aquecimento, e não foi investigado.
- **Tentativa anterior sem dados.** Em `latencia_ocr_tentativa1.csv` o nó e o PC viram os 27 disparos (12:25 a 12:46), mas
  o receptor não entregou nenhum uplink ao PC até as 12:46:19, e a causa não foi identificada (o script dessa tentativa
  ainda não tinha o `--debug`). Essas 28 linhas **não entram** nas estatísticas acima.

## Pendente

- **Consumo, fluxo de imagem:** separar o sleep do Radioenge (`SLEEP:60` com ele desconectado); autonomia com a
  bateria real e o intervalo de campo; investigar a causa do despertar sem envio (ciclo 28) e do JPEG maior.
  Procedimento em [`medir_corrente.md`](medir_corrente.md).
- **Perdas de uplink nos dois fluxos:** 20,6% das leituras do OCR e 33% das imagens não chegaram ao PC; a causa
  não foi investigada (ver a hipótese do primeiro uplink depois do despertar, acima). Falta também a estratégia de
  reenvio, que não existe em nenhum dos dois firmwares no modo autônomo.
- **Deep sleep:** implementado em `Rede/transmissor_esp32cam` (comandos `AUTO`, `STOP`, `SLEEP`) e em
  `Rede/transmissor_ocr_esp32cam`. No de imagem, os 30 ciclos de `AUTO:30` (acima) mostram a corrente caindo de
  ≈ 84,5 mA acordado para ≈ 23,7 mA dormindo em todos os ciclos, e o teste curto de 4 ciclos confirmou
  `DEEPSLEEP_RESET` e o contador de ciclos na memória RTC. No de OCR, os 30 ciclos de `AUTO:30` mostram o mesmo
  padrão (≈ 114 mA acordado, ≈ 25 mA dormindo). Roteiro em
  [`teste_deep_sleep.md`](teste_deep_sleep.md).
- **Taxa de pacotes entregues (H2):** medida nos dois fluxos pelos CSVs de latência (imagem: 98,0% dos pacotes e
  20 de 30 imagens; OCR: 79,4% das leituras). `transmissao.csv` (imagem) e `transmissao_ocr.csv` (OCR), gerados pelo
  `reconstrutor.py` com FCnt e tempo de rádio, ainda sem medições em placa; ver
  [`medir_transmissao.md`](medir_transmissao.md).
