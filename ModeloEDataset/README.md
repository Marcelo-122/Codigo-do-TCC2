# Leitura automática de hidrômetro via CNN + TFLite Micro (ESP32CAM)

Pipeline para treinar, no PC, os modelos que rodarão via **TensorFlow Lite Micro** numa
**ESP32CAM**, lendo a leitura (m³) de hidrômetros mecânicos do tipo "word-wheel" (rodinhas)
a partir de uma foto.

## Contexto

O trabalho original (Gustavo) cobre só o primeiro estágio: um modelo de **segmentação**
([pipeline.py](pipeline.py)) que recebe a foto do hidrômetro inteiro e devolve uma máscara
binária indicando **onde** está a janela de dígitos (retângulo rotacionado, já que a foto
pode ser tirada em qualquer ângulo). Esse modelo já é quantizado em INT8 e convertido para
`.h` ([gerar_header.py](gerar_header.py) → [modelo.h](modelo.h) / [modelo_esp32.tflite](modelo_esp32.tflite)).

Faltava o segundo estágio: depois de saber *onde* estão os dígitos, ainda é preciso
**ler** cada um deles. É isso que este trabalho adiciona — um classificador de dígitos
(0-9) pequeno o suficiente para rodar ao lado do modelo de segmentação no mesmo
microcontrolador.

## Pipeline completo (conceitual)

```
Foto do hidrômetro (ESP32CAM)
        │
        ▼
[1] modelo de segmentação (modelo_esp32.tflite, já existente)
        │  → máscara da janela de dígitos
        ▼
retificação (perspectiva/rotação) + corte em N células, uma por dígito
        │
        ▼
[2] modelo_digito.tflite (uma inferência por célula/dígito) ← este trabalho
        │
        ▼
leitura completa (ex.: "00588817" → 588.817 m³)
```

Os dois modelos são independentes e cabem juntos com folga no ESP32CAM:

| Modelo | Tamanho INT8 | Parâmetros |
|---|---|---|
| Segmentação (`modelo_esp32.tflite`) | 10,9 KB | — |
| Classificador de dígito (`modelo_digito.tflite`) | 81,5 KB | 72.442 |

## Fontes de dados

Rotular dígito-a-dígito é o problema central aqui: nenhum dos datasets crus vem com
"aqui está o dígito 7" — só com a leitura total do medidor. Três fontes foram combinadas.

> **Nenhum dos dois datasets externos (Kaggle e Dryad) fica versionado neste repositório**
> — juntos passariam de 3 GB. Baixe cada um antes de rodar os scripts de preparação (ver
> "Como rodar" mais abaixo).

### 1. Kaggle — *yandex-toloka water-meters-dataset*
Baixar de <https://www.kaggle.com/datasets/tapakah68/yandextoloka-water-meters-dataset> e
colocar em `dataset/images/` + `dataset/masks/` (créditos em
[dataset/Crédito.txt](dataset/Crédito.txt)). 1244 fotos reais de hidrômetros variados
(ângulo arbitrário), com máscara da janela de dígitos e o valor total no nome do arquivo
(`id_1000_value_176_881.jpg` → 176,881 m³).

Não há como saber de antemão quantas rodinhas cada medidor tem, então
[preparar_dataset_digitos.py](preparar_dataset_digitos.py) faz, para cada imagem:

1. Retifica a janela de dígitos usando a máscara (`cv2.minAreaRect` + transformação de
   perspectiva) → tira horizontal.
2. Segmenta a tira em células por **projeção vertical** (soma de pixels de primeiro plano
   por coluna, achando os vãos entre rodinhas).
3. Só aceita a amostra se a segmentação achar **exatamente 8 células** (hipótese: 5 dígitos
   inteiros + 3 fracionários, testada e confirmada como a mais consistente no dataset) *e*
   as células tiverem largura parecida entre si (rejeita quando a projeção "colou" ou
   "partiu" um dígito errado, mesmo batendo a contagem por coincidência — isso reduziu o
   ruído de rótulo de ~15-20% para ~3-4%, conferido visualmente).
4. Amostras que não batem são **descartadas**, nunca rotuladas no chute.

Resultado: 195 imagens aceitas (de 1244) → ~1.560 recortes de dígito. Relatório completo em
`dataset/digits_report.csv` + `dataset/digits_preview.png` (amostra visual por classe).

### 2. Dryad — *Word-Wheel Water Meter Dataset* (Zhao et al., 2026)
Dataset público, revisado por pares (Nature *Scientific Data*, 2,8 GB). Baixar em
<https://doi.org/10.5061/dryad.7d7wm3860> e extrair em
`dataset/Word-Wheel_Water_Meter_Dataset/`, mantendo a estrutura original do zip (deve
sobrar `dataset/Word-Wheel_Water_Meter_Dataset/Word-Wheel_Water_Meter_Dataset/recognition/...`).
O paper completo está salvo aqui em
[s41597-026-06809-z (1).pdf](<s41597-026-06809-z (1).pdf>). Referência: Zhao, S. et al. *A
comprehensive dataset for word-wheel water meter reading under challenging conditions.*
Scientific Data 13, 479 (2026).
DOI: [10.1038/s41597-026-06809-z](https://doi.org/10.1038/s41597-026-06809-z).

> **Licença:** CC BY-NC-ND 4.0 (não-comercial, sem derivados). Uso acadêmico/TCC está
> coberto; se este projeto virar produto comercial, os pesos treinados com esses dados
> precisam ser reavaliados.

Ao contrário do Kaggle, o conjunto de **reconhecimento** do Dryad já vem com recortes
padronizados (200×60 px) e a **string completa do rótulo pronta em CSV** (5 ou 6 dígitos),
incluindo flags `reversed` (imagem espelhada) e `half-word` (rodinha capturada no meio da
troca entre dois dígitos — ambíguo).
[preparar_dataset_dryad.py](preparar_dataset_dryad.py):

1. Descarta linhas com `half-word=1` (dígito ambíguo).
2. Para `reversed=1`, aplica `cv2.flip` horizontal — isso desfaz simultaneamente a ordem
   invertida *e* o espelhamento de cada dígito (confirmado visualmente comparando
   antes/depois).
3. Divide a tira em N fatias de largura igual (aqui a divisão simples funciona bem, já que
   os recortes já vêm padronizados e retos — diferente do Kaggle).

Resultado: 11.079 imagens aceitas → **57.197 recortes de dígito** (ruído residual estimado
em ~1-2%, bem mais limpo que o Kaggle). Isso multiplicou o dataset de treino por ~35x e foi
o que mais melhorou a acurácia (51,6% → 97,6%).

### 3. Fotos reais da própria ESP32CAM (conjunto de domínio / fine-tuning)
Nem o Kaggle nem o Dryad foram fotografados com o sensor/lente/compressão da ESP32CAM alvo
— há uma diferença real de domínio. [preparar_dataset_dominio_esp32.py](preparar_dataset_dominio_esp32.py)
usa fotos reais tiradas pela ESP32CAM (pasta [Imagens/](Imagens) + uma pasta externa do
usuário) com caixas de recorte calibradas manualmente por foto (`RECORTES_MANUAIS`, já que
não há máscara de referência para essas fotos) e o mesmo fatiamento em largura igual.
Rótulos ficam em [dominio_labels.csv](dominio_labels.csv), transcritos manualmente (poucas
fotos, checagem visual viável).

De ~39 fotos reais disponíveis, só 3 (2 medidores físicos diferentes) tiveram
ângulo/recorte confiável o suficiente pra virar dado de treino sem arriscar rótulo errado —
as demais tinham corte ou rotação ambígua demais. **24 recortes de dígito no total.**

## Arquitetura da CNN

Entrada 28×28 grayscale, ~72 mil parâmetros (ainda pequena para padrão de CNNs, mas maior
que a primeira versão — ver "Histórico de iterações" abaixo):

```
Conv2D(16,3×3) → Conv2D(16,3×3) → MaxPool
Conv2D(32,3×3) → Conv2D(32,3×3) → MaxPool
Conv2D(64,3×3) → MaxPool
Flatten → Dense(64) → Dropout(0.3) → Dense(10, softmax)
```

Treino em duas fases, em [treinar_classificador_digitos.py](treinar_classificador_digitos.py):

- **Fase A** — treino principal nos ~58.760 recortes combinados (Kaggle + Dryad), com
  aumento de dados simulando a câmera do ESP32CAM (downsample+upsample pra imitar baixa
  resolução nativa, ruído gaussiano leve, rotação/translação leves, jitter de contraste) e
  `class_weight` pra compensar o dígito `0` (superrepresentado por zero-padding).
- **Fase B** — fine-tuning com as 24 fotos reais de domínio (fortemente aumentadas e
  repetidas) + uma fatia do treino principal, para não esquecer o que já sabia
  (*catastrophic forgetting*). Learning rate bem mais baixo que a Fase A.

Depois do treino: exporta como SavedModel e converte para TFLite **INT8** (mesmo padrão do
`pipeline.py` original: representative dataset, `TFLITE_BUILTINS_INT8`, entrada/saída
`int8`), e valida a acurácia do modelo **já quantizado** rodando `tf.lite.Interpreter` no
PC — nada disso roda no ESP32, só o modelo final congelado.

## Resultados

| Etapa | Acurácia geral (validação) | Acurácia nas fotos reais da ESP32CAM |
|---|---|---|
| Antes do Dryad (só Kaggle, CNN pequena) | 51,6% | 25% (zero-shot) |
| Fase A com Dryad (sem fine-tuning) | 97,7% (float) / 97,6% (INT8) | 62,5% (zero-shot) |
| **Fase A + Fase B (final, INT8)** | **96,3%** | **95,8%** (23/24) |

O ganho do Dryad foi o maior fator isolado. A Fase B custou ~1,4 ponto de acurácia geral
mas fechou quase todo o gap de domínio (62,5%→95,8%) — troca que vale a pena, já que o que
importa no fim é ler o hidrômetro real, não o dataset de validação.

> Os 95,8% de domínio são sobre as *mesmas* 24 fotos usadas no fine-tuning (não há fatia
> separada de teste, dado o volume pequeno) — é um número otimista, não uma medida
> independente. Ver "Próximos passos".

## Como rodar

```bash
# 0. Baixa os datasets externos (nao versionados aqui, ver secao "Fontes de dados")
#    - Kaggle -> dataset/images/ + dataset/masks/
#    - Dryad  -> dataset/Word-Wheel_Water_Meter_Dataset/

# 1. Ambiente (Python 3.10 — TensorFlow não tem wheel estável pra 3.13 no Windows ainda)
python -m venv .venv
./.venv/Scripts/pip install -r requirements.txt

# 2. Prepara os datasets de dígito (nesta ordem, cada um soma ao mesmo dataset/digits/)
./.venv/Scripts/python preparar_dataset_digitos.py        # Kaggle
./.venv/Scripts/python preparar_dataset_dryad.py           # Dryad
./.venv/Scripts/python preparar_dataset_dominio_esp32.py   # fotos reais da ESP32CAM (ja incluidas em Imagens/)

# 3. Treina, converte e valida
./.venv/Scripts/python treinar_classificador_digitos.py

# 4. Gera o header C para o firmware (compatível com o uso antigo, agora com argumentos)
./.venv/Scripts/python gerar_header.py --tflite modelo_digito.tflite --header modelo_digito.h --array-name modelo_digito_tflite
```

Conferir sempre antes de confiar no dataset gerado:
- `dataset/digits_report.csv` / `dataset/digits_preview.png` (Kaggle)
- `dataset/digits_domain_report.csv` / `dataset/digits_domain_preview.png` (fotos reais)

## Arquivos deste estágio

| Arquivo | Papel |
|---|---|
| [digitos_comum.py](digitos_comum.py) | Funções compartilhadas: retificação por máscara, segmentação por projeção/largura igual, leitura de imagem com path Unicode |
| [preparar_dataset_digitos.py](preparar_dataset_digitos.py) | Extrai dígitos rotulados do Kaggle |
| [preparar_dataset_dryad.py](preparar_dataset_dryad.py) | Extrai dígitos rotulados do Dryad |
| [preparar_dataset_dominio_esp32.py](preparar_dataset_dominio_esp32.py) + [dominio_labels.csv](dominio_labels.csv) | Extrai dígitos das fotos reais da ESP32CAM |
| [treinar_classificador_digitos.py](treinar_classificador_digitos.py) | Constrói, treina (Fase A + B), converte INT8 e valida a CNN |
| [gerar_header.py](gerar_header.py) | Converte qualquer `.tflite` em `.h` (usado tanto pro modelo de segmentação quanto pro de dígito) |
| `modelo_digito.h5` / `.tflite` / `.h` | Artefatos finais do classificador de dígito |

## Limitações conhecidas

- **Escopo atual é só Python** (dataset → modelo → INT8 → `.h`). Não existe ainda nenhum
  código de firmware (Arduino/PlatformIO/TFLite Micro em C++) neste repositório — a
  integração dos dois modelos no ESP32CAM real fica para uma etapa futura.
- O conjunto de domínio real (24 recortes, 2 medidores) cobre só os dígitos
  `{0,1,2,3,7,8,9}` — faltam exemplos reais de `4,5,6`.
- A acurácia de domínio (95,8%) não tem fatia de teste separada — é otimista.
- Rotulagem automática (Kaggle e Dryad) depende de suposições e heurísticas auditáveis via
  os `*_report.csv`, mas não é 100% livre de ruído (~1-4% estimado).
- Dimensionamento exato de RAM/flash/latência em hardware real (tensor arena, tempo de
  inferência no Xtensa LX6) só será confirmado quando o firmware for escrito.

## Próximos passos recomendados

1. **Coletar mais fotos reais da ESP32CAM** do(s) hidrômetro(s) que serão efetivamente
   monitorados, na mesma posição/distância/ângulo da instalação real:
   - ~30-50 fotos, variando iluminação (dia/noite/luz artificial), pequenas variações de
     ângulo, reflexo/embaçado no vidro.
   - Se o medidor estiver em uso, fotografar ao longo de dias/semanas pra cobrir dígitos
     diferentes conforme o consumo gira as rodinhas.
   - Separar uma fatia (ex.: 30%) como teste real, nunca usada no fine-tuning, pra medir a
     acurácia de verdade.
   - Se houver mais de um medidor físico a monitorar, pelo menos 5-10 fotos de cada.
2. Escrever o firmware (Arduino/PlatformIO + TFLite Micro) que roda os dois modelos em
   sequência no ESP32CAM real, e então medir o orçamento real de RAM/flash/latência.
3. Opcional: se a acurácia de domínio (com teste real separado) ficar abaixo do esperado,
   reconsiderar usar também o conjunto de **detecção** do Dryad (46 mil imagens rotuladas)
   pra melhorar o modelo de segmentação, hoje treinado só com as 1244 imagens do Kaggle.

## Histórico de iterações (contexto do processo)

Registrado aqui porque explica *por que* o pipeline ficou do jeito que está, não só o
resultado final:

1. Primeira versão da CNN (8→16 filtros, ~20k parâmetros) treinada só com o Kaggle: 32%
   depois 53,5% de acurácia após um filtro de segmentação mais rigoroso — ainda baixo.
2. Tentativa de fine-tuning de domínio nessa fase (poucos dados, modelo fraco) **piorou**
   a acurácia geral (53%→39%) sem ganho real — ficou desligado (`EXECUTAR_FASE_B = False`).
3. Achado do dataset Dryad (PDF anexado pelo usuário) → adicionado como fonte principal.
4. CNN aumentada (16→32→64 filtros, ~72k parâmetros) porque com muito mais dado real dava
   pra sustentar mais capacidade sem overfitar, e ainda sobra bastante orçamento de memória
   no ESP32CAM.
5. Com o modelo bem mais forte, a Fase B foi testada de novo (3 intensidades) e desta vez
   ajudou bastante (62,5%→95,8% no domínio, custando ~1,4pp geral) — reativada.
