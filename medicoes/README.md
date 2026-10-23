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
| Core Arduino-ESP32 | **a confirmar** (3.0.7 está instalado no PC de desenvolvimento, mas o log da captura não o registra) |
| Biblioteca TFLite Micro | **a confirmar** (nome e versão; o sketch inclui `micro_log.h`, ou seja, uma versão recente do `tflite-micro`) |
| Entrada da câmera | 160×120, tons de cinza; segmentação redimensiona para 192×192 |
| Modelos | `modelo.h` (segmentação, `modelo_esp32.tflite`) e `modelo_digito.h` (classificador) |
| Intervalo entre capturas | 5 s de `delay` + ~18 s de processamento |

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

## Ainda não medido

- Corrente por estado (sleep, captura, inferência, transmissão) e mAh por leitura.
- Latência ponta a ponta (disparo no nó até o dado no servidor), nos dois fluxos.
- Deep sleep entre leituras (ainda não implementado).
