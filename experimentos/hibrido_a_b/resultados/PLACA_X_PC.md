# Placa x PC nas mesmas imagens

Gerado por `comparar_placa_pc.py` em 2026-11-18. Os 33 quadros de `quadros_160x120.csv` foram mandados pela serial ao `transmissor_ocr_esp32cam` (comando `LERQ`), cada um com a ROI da sua posição de câmera, e lidos pelo mesmo `lerDigitos()` do OCR na placa (TFLite Micro, esp-nn). O PC leu os mesmos quadros com o `pipeline_nuvem.py` (ai-edge-litert sem XNNPACK, kernels otimizados do LiteRT).

| | Resultado |
|---|---|
| Leituras iguais na placa e no PC | 33/33 |
| Saídas int8 do classificador idênticas (todas as fatias) | 4/33 (maior diferença: 18) |
| Leituras exatas contra o rótulo (30 quadros sem `?`) | placa 25/30, PC 25/30 |
| Tempo do classificador na placa (6 fatias) | mediana 1917 ms (1917 a 1918 ms) |

Mede só o cálculo: não inclui a câmera, a exposição nem a variação entre quadros ao vivo. Detalhe por quadro em `placa_x_pc_por_foto.csv`.
