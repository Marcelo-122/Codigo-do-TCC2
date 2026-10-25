# Teste de viabilidade: OCR genérico em imagem 160×120

[`Teste_OCR.ipynb`](Teste_OCR.ipynb) é o notebook do Google Colab em que Tesseract e EasyOCR foram aplicados a
uma foto do hidrômetro. **Foi só um teste de viabilidade**: a pergunta era se um OCR genérico consegue ler um
medidor numa imagem pequena como a que a ESP32-CAM captura (160×120, tons de cinza). Tesseract e EasyOCR
**não serão usados** nos pipelines avaliados no trabalho.

O notebook tem três experimentos (uma célula de código cada). Os três usaram a mesma foto,
[`imagens/20260511204204.jpg`](imagens/20260511204204.jpg) (160×120), enviada pelo `files.upload()` do Colab: para
repetir, rode o notebook no Colab e envie esse arquivo quando a célula pedir.

## Resultado

Na foto aparece o valor `3 5 3 4 8 5` (o último dígito fica cortado na borda direita da imagem).

| # | Método | Saída | Leu certo? |
|---|---|---|---|
| 1 | Tesseract (`pytesseract`) direto sobre a imagem binarizada | texto `F1` (confiança 15) e `flslalalals` (confiança 20) | Não |
| 2 | EasyOCR sobre a imagem binarizada | `1581`, confiança 67 % | Não (4 dígitos, valores errados) |
| 3 | OpenCV (binarização e componentes conectados, um recorte por dígito) + Tesseract em cada recorte | 6 dígitos: `3`, `5`, `3`, `4`, `8`, `5` → **`353485`** | Sim, confere com o que se vê na foto |

**Conclusão.** Um OCR genérico aplicado à linha inteira não leu esta imagem (experimentos 1 e 2). A leitura só
funcionou quando a imagem foi segmentada em um recorte por dígito e cada recorte foi reconhecido sozinho
(experimento 3). Isso é a mesma estrutura do Pipeline B (segmentar, depois classificar dígito a dígito).

**Limites.** É **uma única foto**, a mesma nos três experimentos, sem gabarito independente e sem medida de
acurácia: serve como teste de viabilidade, não como resultado de avaliação.

## Versões usadas (lidas das saídas gravadas no notebook)

| Componente | Versão |
|---|---|
| Ambiente | Google Colab, Python 3.12, CPU |
| Tesseract | 4.1.1 (`tesseract-ocr`), idioma `por` 4.00 |
| pytesseract | 0.3.13 |
| EasyOCR | 1.7.2 (com torch 2.11.0+cpu, torchvision 0.26.0+cpu) |
| OpenCV | opencv-python-headless 4.13.0.92 |
| Pillow | 11.3.0 |

## O que falta

- **Mais fotos.** Para que esta etapa valha como avaliação (e não só viabilidade), ela precisaria passar pelo
  conjunto de teste comum do trabalho, com gabarito.
