# Resultados do classificador de dígitos

Gerado automaticamente por `gerar_relatorio_resultados.py`, reavaliando os arquivos
`modelo_digito.h5` (float) e `modelo_digito.tflite` (INT8) já treinados — **não** re-treina
nada, só mede. Para reproduzir do zero, rode `treinar_classificador_digitos.py` (ver
[README.md](README.md)).

## Resumo

| Métrica | Valor |
|---|---|
| Acurácia — modelo float (`modelo_digito.h5`) | **96.94%** |
| Acurácia — modelo INT8 (`modelo_digito.tflite`), validação | **96.89%** (8539/8813) |
| Acurácia — modelo INT8, fotos reais da ESP32CAM (domínio) | **100.00% (24 amostras)** |
| Parâmetros do modelo | 72,442 |
| Tamanho `modelo_digito.tflite` | 81.5 KB |
| Tamanho `modelo_esp32.tflite` (segmentação, referência) | 10.9 KB |
| Total de imagens em `dataset/digits/` | 58,757 |
| Tamanho da fatia de validação | 8,813 |

## Acurácia por classe (INT8, validação)

| Dígito | Exemplos no dataset | Acurácia |
|---|---|---|
| 0 | 24554 | 98.50% |
| 1 | 5999 | 95.69% |
| 2 | 4576 | 97.22% |
| 3 | 4310 | 97.50% |
| 4 | 3661 | 96.29% |
| 5 | 3406 | 95.79% |
| 6 | 3228 | 93.18% |
| 7 | 2995 | 96.00% |
| 8 | 3064 | 95.82% |
| 9 | 2964 | 92.55% |

## Matriz de confusão (INT8, validação)

![Matriz de confusão](matriz_confusao.png)

## Como verificar independentemente

1. Clone o repositório e siga o "Como rodar" do [README.md](README.md) (baixa os datasets,
   monta o `dataset/digits/`).
2. Rode `python gerar_relatorio_resultados.py` — ele recalcula tudo acima a partir dos
   arquivos `modelo_digito.h5`/`.tflite` já commitados, sem precisar re-treinar (leva
   segundos/poucos minutos, não os ~20min do treino completo).
3. Os números crus, sem arredondamento, também ficam em `resultados_treino.json`.
