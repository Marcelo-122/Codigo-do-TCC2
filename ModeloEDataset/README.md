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
"aqui está o dígito 7" — só com a leitura total do medidor. Três fontes foram combinadas:

### 1. Kaggle — *yandex-toloka water-meters-dataset* (já estava no repo)
[dataset/images](dataset/images) + [dataset/masks](dataset/masks), 1244 fotos reais de
hidrômetros variados (ângulo arbitrário), com máscara da janela de dígitos e o valor total
no nome do arquivo (`id_1000_value_176_881.jpg` → 176,881 m³).

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
Dataset público, revisado por pares (Nature *Scientific Data*), colocado pelo usuário em
`dataset/Word-Wheel_Water_Meter_Dataset/` (não versionado no git — 2,8 GB, ver
`.gitignore`). Referência: Zhao, S. et al. *A comprehensive dataset for word-wheel water
meter reading under challenging conditions.* Scientific Data 13, 479 (2026).
DOI: [10.1038/s41597-026-06809-z](https://doi.org/10.1038/s41597-026-06809-z) — dados em
Dryad, DOI [10.5061/dryad.7d7wm3860](https://doi.org/10.5061/dryad.7d7wm3860).

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
o que mais melhorou a acurácia (ver números corrigidos em [RESULTADOS.md](RESULTADOS.md)).

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

Números oficiais em **[RESULTADOS.md](RESULTADOS.md)** — gerado por
`gerar_relatorio_resultados.py`, que reavalia `modelo_digito.h5`/`.tflite` já treinados
(sem re-treinar) e é reprodutível por qualquer pessoa que clonar o repo. Inclui matriz de
confusão e acurácia por dígito. É a fonte confiável, não os números soltos abaixo — ver a
nota importante logo depois.

Pra conferir visualmente, foto a foto, o que o modelo previu contra o valor real (em vez de
só a acurácia agregada), rode `verificar_predicoes_dominio.py` — gera uma imagem por foto de
domínio em `dataset/predicoes_dominio/`, com a foto original, cada recorte de dígito e o
par "real/previsto" (verde = acertou, vermelho = errou). Exemplo:
[campo_imagem_capturada_15_predicao.png](dataset/predicoes_dominio/campo_imagem_capturada_15_predicao.png).

Também há um teste com imagens **completamente novas** (nunca usadas em nenhuma etapa do
treino) em **[TESTE_IMAGENS_NOVAS.md](TESTE_IMAGENS_NOVAS.md)** — hidrômetros chineses de
marca/fonte de dígito nunca vista (4 fotos limpas) + fotos reais tiradas pela própria
ESP32CAM (2 fotos), gerado por `testar_imagens_novas.py`: 30/32 dígitos individuais
corretos (94%), incluindo as 2 fotos reais da ESP32CAM 100% corretas.

| Etapa | Acurácia geral (validação, 10 classes) | Acurácia nas fotos reais da ESP32CAM |
|---|---|---|
| **Fase A + Fase B (final, INT8)** | **96,9%** | **100%** (24/24) |

> **Os 100% de domínio são sobre as *mesmas* 24 fotos usadas no fine-tuning** (não há fatia
> separada de teste, dado o volume pequeno) — é um número otimista, não uma medida
> independente. Ver "Próximos passos".

> **Bug corrigido nos números anteriores:** até uma revisão feita depois do treino, o
> dataset de validação era construído com `shuffle=False` numa chamada e `shuffle=True` na
> outra (treino) do `image_dataset_from_directory` do Keras — esse parâmetro também decide
> se a lista de arquivos é embaralhada *antes* de cortar treino/validação, então as duas
> chamadas geravam cortes não-complementares. Na prática, "validação" era só os últimos 15%
> da lista ordenada por classe, que caíam inteiramente nos dígitos 7, 8 e 9 — todo número
> de acurácia relatado antes disso (inclusive os "51,6%→97,6%→96,3%" que já foram
> mencionados em conversa) media só esses 3 dígitos, nunca os outros 7. Corrigido em
> `treinar_classificador_digitos.py` e `gerar_relatorio_resultados.py` (as duas chamadas
> agora usam `shuffle=True` consistente) e o modelo foi re-treinado do zero. Os números
> corrigidos acima ficaram parecidos com os antigos (96,9% vs 96,3%) — não porque o bug não
> importasse, mas porque o modelo de fato generaliza bem pras 10 classes, o que só dá pra
> afirmar agora que a validação está correta.

## Como rodar

```bash
# 1. Ambiente (Python 3.10 — TensorFlow não tem wheel estável pra 3.13 no Windows ainda)
python -m venv .venv
./.venv/Scripts/pip install -r requirements.txt

# 2. Prepara os datasets de dígito (nesta ordem, cada um soma ao mesmo dataset/digits/)
./.venv/Scripts/python preparar_dataset_digitos.py        # Kaggle
./.venv/Scripts/python preparar_dataset_dryad.py           # Dryad (requer a pasta local)
./.venv/Scripts/python preparar_dataset_dominio_esp32.py   # fotos reais da ESP32CAM

# 3. Treina, converte e valida
./.venv/Scripts/python treinar_classificador_digitos.py

# 4. Gera o header C para o firmware (compatível com o uso antigo, agora com argumentos)
./.venv/Scripts/python gerar_header.py --tflite modelo_digito.tflite --header modelo_digito.h --array-name modelo_digito_tflite

# 5. (Opcional) Gera/atualiza o relatório verificável de resultados
./.venv/Scripts/python gerar_relatorio_resultados.py

# 6. (Opcional) Conferencia visual foto a foto (real vs. previsto)
./.venv/Scripts/python verificar_predicoes_dominio.py
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
| [gerar_relatorio_resultados.py](gerar_relatorio_resultados.py) | Reavalia o modelo já treinado e gera [RESULTADOS.md](RESULTADOS.md) + matriz de confusão (não re-treina) |
| [verificar_predicoes_dominio.py](verificar_predicoes_dominio.py) | Gera uma imagem por foto de domínio comparando dígito real vs. previsto (verificação visual) |
| [testar_imagens_novas.py](testar_imagens_novas.py) | Testa o modelo em imagens novas (`Imagens_2/`), nunca usadas no treino — gera [TESTE_IMAGENS_NOVAS.md](TESTE_IMAGENS_NOVAS.md) |
| `modelo_digito.h5` / `.tflite` / `.h` | Artefatos finais do classificador de dígito |

## Limitações conhecidas

- **Escopo atual é só Python** (dataset → modelo → INT8 → `.h`). Não existe ainda nenhum
  código de firmware (Arduino/PlatformIO/TFLite Micro em C++) neste repositório — a
  integração dos dois modelos no ESP32CAM real fica para uma etapa futura.
- O conjunto de domínio real (24 recortes, 2 medidores) cobre só os dígitos
  `{0,1,2,3,7,8,9}` — faltam exemplos reais de `4,5,6`.
- A acurácia de domínio (100%, ver [RESULTADOS.md](RESULTADOS.md)) não tem fatia de teste
  separada — é otimista.
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
resultado final. **Os percentuais abaixo são os que foram medidos em cada etapa na época,
com o bug de shuffle/split descrito em "Resultados" ainda presente** (validação enviesada
pros dígitos 7/8/9) — servem pra entender a direção/magnitude relativa de cada mudança, não
como valores absolutos confiáveis. Os únicos números corrigidos e confiáveis são os da
versão final, em [RESULTADOS.md](RESULTADOS.md).

1. Primeira versão da CNN (8→16 filtros, ~20k parâmetros) treinada só com o Kaggle: 32%
   depois 53,5% de acurácia após um filtro de segmentação mais rigoroso — ainda baixo.
2. Tentativa de fine-tuning de domínio nessa fase (poucos dados, modelo fraco) **piorou**
   a acurácia geral (53%→39%) sem ganho real — ficou desligado (`EXECUTAR_FASE_B = False`).
3. Achado do dataset Dryad (PDF anexado pelo usuário) → adicionado como fonte principal.
4. CNN aumentada (16→32→64 filtros, ~72k parâmetros) porque com muito mais dado real dava
   pra sustentar mais capacidade sem overfitar, e ainda sobra bastante orçamento de memória
   no ESP32CAM.
5. Com o modelo bem mais forte, a Fase B foi testada de novo (3 intensidades) e desta vez
   ajudou bastante — reativada.
6. Ao gerar um relatório verificável de resultados (pedido do usuário), a matriz de
   confusão saiu quebrada (só 3 classes apareciam) — investigando isso, achei o bug real de
   `shuffle` no split treino/validação (ver "Resultados"). Corrigido e re-treinado do zero;
   os números finais corrigidos ficaram parecidos com os antigos, o que dá mais confiança de
   que o modelo generaliza bem — mas só porque agora isso foi de fato medido certo.
