# Teste do Pipeline A na ESP32-CAM (arena e operadores)

Teste em hardware do Pipeline A (U-Net 384×384 + leitor CRNN+CTC 48×224, hoje em
[`legado/TreinoEModelosOCRNaBorda/`](../legado/TreinoEModelosOCRNaBorda/)). Serve de evidência para a
escolha do Pipeline B como OCR de borda (ver o README da raiz).

- Firmware: [`teste_esp32cam_pipeline_a.ino`](../legado/TreinoEModelosOCRNaBorda/teste_esp32cam_pipeline_a/teste_esp32cam_pipeline_a.ino)
  (os headers dos modelos saem de `gerar_headers.py`, na mesma pasta).
- Ambiente: AI-Thinker ESP32-CAM, CPU a 240 MHz, PSRAM de 4 MB, core Arduino-ESP32 3.0.7 com a
  TFLite Micro que vem junto dele (`esp-tflite-micro` com ESP-NN), partição "Huge APP", Arduino IDE 2.3.10.
- O teste **não usa a câmera**: a pergunta é se o modelo aloca e se os operadores existem. Cada modelo
  recebeu todo o maior bloco livre da PSRAM (4.063.220 bytes) menos 64 KB de folga.

## Resultado

| Modelo | `AllocateTensors` | Mensagem do TFLM |
|---|---|---|
| Detector U-Net 384×384 (`modelo_medidor.tflite`) | **falhou** | `Failed to resize buffer. Requested: 15335424, available 4053940, missing: 11281484` |
| Leitor CTC original (`modelo_digitos_ctc.tflite`) | **falhou** | `Failed to get registration from op code REDUCE_PROD` |
| Leitor CTC com sintéticos, QAT (`modelo_digitos_ctc_sint.tflite`) | **falhou** | `Failed to get registration from op code REDUCE_PROD` |

Com a PSRAM inteira livre (4.192.124 bytes no início, 4.128.756 no maior bloco, sem câmera nem outro
modelo carregado), o detector pede **15.335.424 bytes** de arena, 3,8 vezes o que há.

## Leitura do resultado

- **Detector: não cabe.** O custo vem do tamanho da entrada (384×384) e do buffer temporário em int32 do
  kernel `TRANSPOSE_CONV` do TFLM; não depende da versão da biblioteca.
- **Leitores CTC: falham por operador, não por memória.** O `REDUCE_PROD` vem de um `Dense` aplicado a
  tensor 3D (o `Tensordot` do Keras) e não existe no resolver da TFLM do core 3.0.7. Com o operador
  removido na exportação (por exemplo, `Conv1D` de kernel 1 no lugar do `Dense`), a memória estimada
  é de 0,2 a 0,4 MB, mas isso **não foi testado em hardware**.
- Vale para o Pipeline A **como exportado**, na TFLM do core 3.0.7. Não prova nada sobre a ideia de CTC.

## Estimativa por software (validada contra a placa)

[`estimar_arena_tflm.py`](estimar_arena_tflm.py) lê um `.tflite` e reproduz o planejador de memória do
TFLM. Comparação com a arena medida:

| Modelo | Estimado | Medido |
|---|---:|---:|
| Segmentação de B (192×192), `arena_used_bytes` no ESP32-CAM | 1.622.016 | 1.623.852 |
| Classificador de dígito de B, `arena_used_bytes` no ESP32-CAM | 25.088 | 28.556 |
| Detector de A, `Requested` do TFLM na placa | 15.335.424 | 15.335.424 |

Estimativa dos leitores CTC (sem medição em hardware): 215.040 bytes (original) e 430.080 bytes (QAT).

```bash
pip install tflite numpy
python medicoes/estimar_arena_tflm.py legado/TreinoEModelosOCRNaBorda/Modelos/modelo_medidor.tflite
python medicoes/estimar_arena_tflm.py --calibrar
```

## Observação sobre o firmware

A primeira versão do sketch derrubava a placa (`LoadProhibited`) ao destruir o interpretador depois de um
`AllocateTensors` que falhou, e entrava em loop de reinício. A versão atual não o destrói, e a saída
completa termina em `FIM`.
