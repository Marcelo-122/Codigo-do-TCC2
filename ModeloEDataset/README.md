# Leitura automática de hidrômetro via CNN + TFLite Micro (ESP32CAM)

Pipeline para treinar, no PC, os modelos que rodam via **TensorFlow Lite Micro** numa
**ESP32CAM** real, lendo a leitura (m³) de hidrômetros mecânicos do tipo "word-wheel"
(rodinhas) a partir de uma foto. Os dois modelos (segmentação + classificador de dígito) já
foram testados juntos em hardware real — ver
["Firmware / ferramenta de calibração no ESP32CAM real"](#firmware--ferramenta-de-calibração-no-esp32cam-real).

## Contexto

O trabalho original (Gustavo) cobre só o primeiro estágio: um modelo de **segmentação**
([pipeline.py](pipeline.py)) que recebe a foto do hidrômetro inteiro e devolve uma máscara
binária indicando **onde** está a janela de dígitos (retângulo rotacionado, já que a foto
pode ser tirada em qualquer ângulo). Esse modelo já é quantizado em INT8 e convertido para
`.h` ([gerar_header.py](gerar_header.py) → [modelos/modelo.h](modelos/modelo.h) / [modelos/modelo_esp32.tflite](modelos/modelo_esp32.tflite)).

Faltava o segundo estágio: depois de saber *onde* estão os dígitos, ainda é preciso
**ler** cada um deles. É isso que este trabalho adiciona — um classificador de dígitos
(0-9) pequeno o suficiente para rodar ao lado do modelo de segmentação no mesmo
microcontrolador.

## Estrutura de pastas

```
ModeloEDataset/
├── *.py                    scripts do pipeline (todos na raiz, mesmo nível)
├── dominio_labels.csv       rótulos das fotos de domínio (usado por preparar_dataset_dominio_esp32.py)
├── requirements.txt
├── modelos/                 todos os artefatos de modelo (.h5 / .tflite / .h)
├── relatorios/               RESULTADOS.md, TESTE_IMAGENS_NOVAS.md, matriz_confusao.png, resultados_treino.json
├── docs/                     paper de referência (Dryad)
├── dataset/                  dados (a maior parte gitignored — ver "Como rodar")
├── Imagens/                   fotos reais da ESP32CAM usadas no fine-tuning (Fase B)
└── Imagens_2/                 fotos novas de teste (nunca usadas no treino)

../test_images/debug_ocr_esp32cam/   firmware real (fora do ModeloEDataset/, pasta irmã no
                                       repo) que roda os dois modelos numa ESP32CAM de
                                       verdade — ver seção "Firmware" abaixo
```

Scripts ficam todos no mesmo nível (não em `scripts/`) de propósito — são poucos e cada um já
tem nome autoexplicativo; separar em subpasta só adicionaria `../` em todo canto sem ganho
real de organização. Só o que não é código (modelos, relatórios, referências) foi separado
em pastas.

## Pipeline completo (conceitual)

```
Foto do hidrômetro (ESP32CAM)
        │
        ▼
[1] modelo de segmentação (modelos/modelo_esp32.tflite, já existente)
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

O modelo de segmentação é treinado por [pipeline.py](pipeline.py): 70 % treino / 15 % validação / 15 % teste, com
semente fixa (a divisão fica em `relatorios/split_segmentacao.csv`). O treino usa lote de 16 numa versão da rede
com lote livre, e os pesos são copiados para a versão de lote fixo em 1 (`batch_shape=(1, ...)`, que é a que o TFLite
Micro precisa) antes de converter; antes, o treino inteiro era feito com `batch_size=1` por 10.000 épocas, sem parada
antecipada. A perda é entropia cruzada + Dice suave (`--perda bce_dice`), porque a janela ocupa poucos pixels e só a
entropia cruzada ficou no platô de "tudo fundo": no mesmo número de épocas, o Dice de validação foi de 0,306 (só
entropia cruzada) para 0,396. O log de progresso fica em `relatorios/treino_segmentacao.log`, o histórico por época em
`relatorios/historico_treino_segmentacao.csv` (gráfico: `relatorios/grafico_treino_segmentacao.png`, gerado por
[gerar_graficos_treino.py](gerar_graficos_treino.py)) e o resultado no teste, em float e em INT8, em
`relatorios/segmentacao_teste.json`.

**Resultado no teste (186 fotos do Kaggle nunca vistas no treino, INT8):** Dice **0,39**, IoU **0,28**, 1 máscara
vazia. É um resultado fraco: a rede é minúscula (11 KB, só dois `MaxPool`, sem conexões de salto) e ainda estava
subindo na época 600 (melhor época: 581); treino e validação têm Dice parecido, ou seja, subajuste, não
sobreajuste. A acurácia por pixel que o script reportava antes passa de 98 % mesmo assim, porque o fundo domina a
imagem; Dice e IoU medem só a janela. O modelo antigo, medido nesse mesmo teste (que ele em boa parte viu no treino),
tinha Dice 0,35.

Os dois modelos são independentes e cabem juntos com folga no ESP32CAM:

| Modelo | Tamanho INT8 | Parâmetros |
|---|---|---|
| Segmentação (`modelos/modelo_esp32.tflite`) | 10,9 KB | — |
| Classificador de dígito (`modelos/modelo_digito.tflite`) | 81,5 KB | 72.442 |

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
Dryad, DOI [10.5061/dryad.7d7wm3860](https://doi.org/10.5061/dryad.7d7wm3860). Paper completo
salvo em [docs/s41597-026-06809-z (1).pdf](<docs/s41597-026-06809-z (1).pdf>).

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

Resultado (versão antiga do script, que usava as pastas `train` **e** `test`): 11.079 imagens aceitas →
**57.197 recortes de dígito** (ruído residual estimado em ~1-2%, bem mais limpo que o Kaggle). Isso multiplicou o
dataset de treino por ~35x e foi o que mais melhorou a acurácia (ver números corrigidos em
[relatorios/RESULTADOS.md](relatorios/RESULTADOS.md)).

> **As pastas `test` do Dryad agora ficam fora do treino.** O script usa só `train`
> (`CONJUNTOS`), apaga de `dataset/digits/` os recortes `dryad_*-digit_test_*` que versões antigas geraram e deixa
> `test` como teste independente: `python ../ocr/avaliar_teste_publico.py` lê essas pastas direto do Dryad
> (fatias iguais → `modelo_digito.tflite`, mesmo pré-processamento do firmware) e grava a linha `dryad_teste` em
> `../medicoes/ocr_teste.csv`. O `modelo_digito.tflite` versionado **já foi re-treinado** sem essas pastas (49.038
> recortes: 47.478 do Dryad `train` e 1.560 do Kaggle). Para reproduzir: `preparar_dataset_digitos.py`,
> `preparar_dataset_dryad.py` e `treinar_classificador_digitos.py`; o log de progresso fica em
> `relatorios/treino_classificador.log` e o histórico por época em `relatorios/historico_treino_classificador.csv`.
> A validação agora é dividida **por foto** ([divisao_por_foto.py](divisao_por_foto.py)): antes ela sorteava recorte a
> recorte, e recortes da mesma foto caíam no treino e na validação, o que inflava a acurácia.

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

Números oficiais em **[relatorios/RESULTADOS.md](relatorios/RESULTADOS.md)** — gerado por
`gerar_relatorio_resultados.py`, que reavalia `modelos/modelo_digito.h5`/`.tflite` já treinados
(sem re-treinar) e é reprodutível por qualquer pessoa que clonar o repo. Inclui matriz de
confusão e acurácia por dígito. É a fonte confiável, não os números soltos abaixo — ver a
nota importante logo depois.

Pra conferir visualmente, foto a foto, o que o modelo previu contra o valor real (em vez de
só a acurácia agregada), rode `verificar_predicoes_dominio.py` — gera uma imagem por foto de
domínio em `dataset/predicoes_dominio/`, com a foto original, cada recorte de dígito e o
par "real/previsto" (verde = acertou, vermelho = errou). Exemplo:
[campo_imagem_capturada_15_predicao.png](dataset/predicoes_dominio/campo_imagem_capturada_15_predicao.png).

Também há um teste com imagens **completamente novas** (nunca usadas em nenhuma etapa do
treino) em **[relatorios/TESTE_IMAGENS_NOVAS.md](relatorios/TESTE_IMAGENS_NOVAS.md)** — hidrômetros chineses de
marca/fonte de dígito nunca vista (4 fotos limpas) + fotos reais tiradas pela própria
ESP32CAM (2 fotos), gerado por `testar_imagens_novas.py`: 29/32 dígitos individuais
corretos (91%), 4 das 6 leituras completas (a `imagem_capturada_144` errou o segundo dígito, `1` lido como `0`).
Com o classificador anterior eram 30/32; a diferença é de um dígito, dentro do ruído de uma amostra tão pequena.

| Etapa | Acurácia geral (validação, 10 classes) | Acurácia nas fotos reais da ESP32CAM |
|---|---|---|
| **Fase A + Fase B (final, INT8)** | **95,4%** (validação por foto) | **100%** (24/24) |

> **Teste independente (pastas `test` do Dryad, 1.894 imagens):** 92,8 % de leituras exatas e 97,7 % dos dígitos
> com a Fase A + B; 92,4 % e 97,3 % só com a Fase A. A Fase B não prejudica e a diferença (8 leituras em 1.894) está
> no ruído. Ela foi mantida porque é a única parte do treino que vê o sensor da ESP32-CAM (sem ela, os 24 recortes
> de domínio dão 21 %). Ver [relatorios/RESULTADOS.md](relatorios/RESULTADOS.md).

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
> corrigidos ficaram parecidos com os antigos (96,9% vs 96,3%) — não porque o bug não
> importasse, mas porque o modelo de fato generaliza bem pras 10 classes, o que só dá pra
> afirmar agora que a validação está correta.

## Firmware / ferramenta de calibração no ESP32CAM real

Os dois modelos deste repositório (`modelos/modelo_esp32.tflite` de segmentação +
`modelos/modelo_digito.tflite` de classificação) **já rodam juntos numa ESP32CAM real**,
via TFLite Micro, numa ferramenta de debug/calibração em
[`test_images/debug_ocr_esp32cam/`](../test_images/debug_ocr_esp32cam/) (repositório
`Codigo-do-TCC2`, pasta irmã de `ModeloEDataset/` — não faz parte deste dataset/pipeline,
mas consome os artefatos dele diretamente: `modelo.h` e `modelo_digito.h` copiados pra lá).

**O que ela faz**, a cada 5 segundos: captura uma foto (160×120, cinza), roda a segmentação
pra achar a janela de dígitos, fatia essa janela em `N_FATIAS` pedaços (ajustável por
medidor — ver abaixo), classifica cada fatia, desenha o retângulo + linhas-guia na imagem
pra calibração visual, e manda tudo (imagem anotada + a leitura completa + métricas de
RAM/PSRAM/tempo) pela Serial USB.

**Testado em hardware real (AI-Thinker ESP32-CAM)** — não é só teoria:
- Câmera + segmentação + classificador de dígito rodando juntos, sem estourar os 4 MB de
  PSRAM (orçamento medido: ~19 KB câmera + 1.623.852 bytes arena de segmentação + 28.556 bytes
  de arena usada pelo classificador de dígito; `psram_free` = 1.289.292 bytes com as duas arenas
  alocadas). Dados em [`../medicoes/`](../medicoes/README.md).
- `N_FATIAS` é só um parâmetro de pós-processamento (divide a caixa detectada em N partes
  iguais) — **não precisa bater** com a convenção "5+3=8" usada pra montar o dataset de
  treino do classificador, já que o classificador só lê um dígito por vez. Calibrado pra
  **6** depois de conferir visualmente que o medidor de teste (marca Tianjin, leitura real
  "046663") tem 6 rodinhas pretas e nenhuma vermelha — ajuste essa constante pro medidor-alvo
  real (é só contar as rodinhas na imagem de debug).
- Achado real de performance: a inferência do modelo de **segmentação** demorou **~15,6s por
  frame** (mediana de 15.564 ms em 61 capturas) em hardware real (bem mais que os poucos milissegundos típicos de TFLite Micro em
  modelos pequenos) — provavelmente por rodar em kernels de referência puros em C, sem
  otimização pra Xtensa, num input relativamente grande (192×192). Isso é aceitável pra essa
  ferramenta de debug (roda a cada 5s de qualquer forma), mas é um ponto a otimizar antes de
  qualquer uso em produção (ver "Próximos passos").

**Todo o histórico de debugging real está documentado** no
[README daquela pasta](../test_images/debug_ocr_esp32cam/README.md) — inclui erros reais de
memória (`Failed to resize buffer`) que apareceram testando em hardware, o diagnóstico de
cada um, e a correção aplicada; útil como referência de troubleshooting caso o firmware
precise ser recompilado ou portado.

## Como rodar

```bash
# 1. Ambiente (Python 3.10 — TensorFlow não tem wheel estável pra 3.13 no Windows ainda)
python -m venv .venv
./.venv/Scripts/pip install -r requirements.txt

# 2. Prepara os datasets de dígito (nesta ordem, cada um soma ao mesmo dataset/digits/)
./.venv/Scripts/python preparar_dataset_digitos.py        # Kaggle
./.venv/Scripts/python preparar_dataset_dryad.py           # Dryad (requer a pasta local)
./.venv/Scripts/python preparar_dataset_dominio_esp32.py   # fotos reais da ESP32CAM (use --cartaz PASTA para as fotos de cartaz do TCC I)

# 3. Treina, converte e valida
./.venv/Scripts/python treinar_classificador_digitos.py

# 4. Gera o header C para o firmware (compatível com o uso antigo, agora com argumentos)
./.venv/Scripts/python gerar_header.py --tflite modelos/modelo_digito.tflite --header modelos/modelo_digito.h --array-name modelo_digito_tflite

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
| [gerar_relatorio_resultados.py](gerar_relatorio_resultados.py) | Reavalia o modelo já treinado e gera [relatorios/RESULTADOS.md](relatorios/RESULTADOS.md) + matriz de confusão (não re-treina) |
| [verificar_predicoes_dominio.py](verificar_predicoes_dominio.py) | Gera uma imagem por foto de domínio comparando dígito real vs. previsto (verificação visual) |
| [testar_imagens_novas.py](testar_imagens_novas.py) | Testa o modelo em imagens novas (`Imagens_2/`), nunca usadas no treino — gera [relatorios/TESTE_IMAGENS_NOVAS.md](relatorios/TESTE_IMAGENS_NOVAS.md) |
| `modelos/modelo_digito.h5` / `.tflite` / `.h` | Artefatos finais do classificador de dígito |

## Limitações conhecidas

- O conjunto de domínio real (24 recortes, 2 medidores) cobre só os dígitos
  `{0,1,2,3,7,8,9}` — faltam exemplos reais de `4,5,6`.
- A acurácia de domínio (100%, ver [relatorios/RESULTADOS.md](relatorios/RESULTADOS.md)) não tem fatia de teste
  separada — é otimista.
- Rotulagem automática (Kaggle e Dryad) depende de suposições e heurísticas auditáveis via
  os `*_report.csv`, mas não é 100% livre de ruído (~1-4% estimado).
- Dimensionamento exato de RAM/flash/latência em hardware real **já foi confirmado** — ver
  a seção "Firmware / ferramenta de calibração no ESP32CAM real" abaixo. Inferência da
  segmentação ficou bem mais lenta que o esperado (~15,6s por frame) — aceitável pra uma
  ferramenta de debug que roda a cada 5s, mas precisa de otimização antes de virar produção
  (ver "Firmware" para detalhes e hipóteses).

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
2. **Otimizar a latência da inferência de segmentação** (~15,6s/frame medido em hardware
   real — ver seção "Firmware" abaixo) antes de qualquer uso em produção: candidatos são
   reduzir a entrada do modelo de segmentação (192×192 é grande pra TFLite Micro sem
   aceleração de hardware), usar uma resolução intermediária menor, ou investigar se a
   biblioteca TFLite Micro instalada tem kernels otimizados pra Xtensa (vs. implementação de
   referência pura em C).
3. Migrar a lógica do firmware de debug (`test_images/debug_ocr_esp32cam/`) pra um firmware
   de produção: remover o desenho de retângulo/linhas-guia (só serve pra debug visual),
   adicionar tratamento de erro mais robusto, e decidir como/onde a leitura final é entregue
   (LoRaWAN? MQTT? outro meio já usado no projeto).
4. Opcional: se a acurácia de domínio (com teste real separado) ficar abaixo do esperado,
   reconsiderar usar também o conjunto de **detecção** do Dryad (46 mil imagens rotuladas)
   pra melhorar o modelo de segmentação, hoje treinado só com as 1244 imagens do Kaggle.

## Histórico de iterações (contexto do processo)

Registrado aqui porque explica *por que* o pipeline ficou do jeito que está, não só o
resultado final. **Os percentuais abaixo são os que foram medidos em cada etapa na época,
com o bug de shuffle/split descrito em "Resultados" ainda presente** (validação enviesada
pros dígitos 7/8/9) — servem pra entender a direção/magnitude relativa de cada mudança, não
como valores absolutos confiáveis. Os únicos números corrigidos e confiáveis são os da
versão final, em [relatorios/RESULTADOS.md](relatorios/RESULTADOS.md).

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
7. Integração real em hardware (`test_images/debug_ocr_esp32cam/`): os dois modelos rodando
   juntos numa ESP32CAM real via TFLite Micro, com dois bugs de memória reais (PSRAM)
   diagnosticados e corrigidos no processo (ver histórico de ajustes detalhado no README
   daquela pasta) — nenhum dos dois era o que a primeira hipótese sugeria, só apareceram
   claramente com logs reais de hardware, não dava pra prever só lendo o código.
8. Depois de rodar contra um medidor real (marca Tianjin, 6 dígitos), a leitura saiu errada
   porque `N_FATIAS` estava fixo em 8 (herdado da convenção do dataset de treino) — corrigido
   pra 6, ajustável por medidor-alvo (não é parâmetro do modelo, só de pós-processamento).
9. Usuário reportou "o leitor não reconhece o 0?" — na real, o dígito `0` é a classe com
   **melhor** acurácia (98,5%, ver `resultados_treino.json`). O problema era no script
   receptor em Python: `parse_metricas()` convertia qualquer valor numérico pra `int`,
   inclusive o campo `leitura` (uma string de dígitos, não um número) — `int("046663")`
   virava `46663`, comendo o zero à esquerda. Corrigido: `leitura` agora fica sempre como
   string.
