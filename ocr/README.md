# ocr/: lado da nuvem e conjunto de teste comum

Contém o **servidor de leitura** (`pipeline_nuvem.py`), a avaliação borda × nuvem (`avaliar.py`), o conjunto de
teste com gabarito (`teste_comum/`) e o teste de viabilidade de OCR genérico (`colab_poc/`).

## Decisão: o que roda no servidor

O servidor roda **os mesmos modelos do Pipeline B** (segmentação `modelo_esp32.tflite` + classificador
`modelo_digito.tflite`, de `ModeloEDataset/modelos/`) com a mesma lógica do firmware
(`test_images/debug_ocr_esp32cam/`). Assim, a única diferença entre os dois fluxos é onde a conta é feita e o
que trafega pelo enlace:

| Fluxo | Na ESP32-CAM | No enlace LoRa | No servidor |
|---|---|---|---|
| borda | captura 160×120 cinza, roda os dois modelos | só a leitura (poucos bytes) | recebe a leitura |
| nuvem | captura 160×120 cinza, codifica JPEG q90 | ~30 pacotes de 175 bytes (≈ 5,2 KB) | remonta o JPEG e roda os dois modelos |

Isso muda a pergunta de pesquisa de "OCR de borda contra OCR de nuvem" para "**onde** rodar o OCR" (bytes
transmitidos, latência, energia), porque a acurácia dos dois lados vem do mesmo modelo. O Tesseract foi só um
teste de viabilidade (`colab_poc/`) e não faz parte dos pipelines avaliados.

## Como o servidor acha a janela dos dígitos

Não usa o modelo de segmentação (que não funciona fora do enquadramento calibrado, ver os resultados abaixo). Com a
câmera fixa, a janela dos dígitos cai sempre na mesma região do quadro: ela é calibrada **uma vez** na instalação (ROI
em pixels do quadro 160×120) e o servidor endireita a inclinação (Hough) e lê as N fatias dessa ROI. O fluxo previsto é
`--alinhar --roi x0,y0,x1,y1`, opcionalmente com `--votar`. A ROI precisa de precisão de cerca de ±1 a ±2 px (ver
"Enquadramento físico fixo"). O firmware de debug (`test_images/debug_ocr_esp32cam/`) serve para posicionar a câmera.

## Uso

```bash
pip install -r ocr/requirements.txt          # Python 3.13 (testado), na raiz do repositório
python ocr/pipeline_nuvem.py foto.jpg --digitos 6 --modo nuvem
python ocr/pipeline_nuvem.py foto.jpg --digitos 6 --modo borda --debug caixa.png
python ocr/pipeline_nuvem.py foto.jpg --digitos 6 --alinhar      # endireita a inclinação (Hough) antes de ler
python ocr/avaliar.py                         # roda o conjunto de teste e grava ocr/teste_comum/resultados/
python ocr/avaliar_roi_fixa.py                # cenário de câmera parada (ROI fixa, sem segmentação) e curva de tolerância
```

`--digitos` é o número de rodinhas do medidor (o `N_FATIAS` do firmware, calibrado por medidor). Fotos em
retrato (as de `teste_comum/` chegam como 480×640 por causa da orientação EXIF) precisam de `--centro-y`, a
altura da janela dos dígitos: o código recorta uma faixa 4:3 em vez de esticar a imagem.

## Conjunto de teste comum (`teste_comum/`)

39 fotos de `test_images/` (fotos tiradas com a ESP32-CAM de um monitor que exibe medidores), 19 leituras
distintas, 2 modelos de medidor (`branco5`, 5 dígitos; `tianjin6`, 6 dígitos). Critérios de escolha: sem
rotação de 90° ou 180° e **sem rodinha entre dois números** (por isso só 39 das 152 fotos). Nenhuma foto é
idêntica às usadas no treino de B (conferido por hash; os nomes de arquivo se repetem, o conteúdo não).

- `gabarito.csv`: leitura real, número de dígitos, medidor, confiança, `centro_y` (enquadramento) e
  `caixa_manual` (janela dos dígitos, só para o diagnóstico).
- **O gabarito foi lido por inspeção visual de fotos borradas** e precisa de conferência humana. As leituras
  marcadas `media` (9 quadros) têm o último dígito menos nítido. `gerar_verificacao.py` gera folhas em
  `verificacao/` com a leitura escrita sobre cada foto, para conferir a olho.

## Resultados (`teste_comum/resultados/RESULTADOS.md`)

| Fluxo | Leituras exatas | Dígitos certos |
|---|---|---|
| borda (segmentação do modelo) | 0/39 | 44/222 (20 %) |
| nuvem (segmentação do modelo) | 0/39 | 42/222 (19 %) |
| borda, caixa manual (diagnóstico) | 23/39 (59 %) | 195/222 (88 %) |
| nuvem, caixa manual (diagnóstico) | 23/39 (59 %) | 194/222 (87 %) |
| nuvem, endireitada no servidor, segmentação do modelo | 0/39 | 39/222 (18 %) |
| nuvem, endireitada no servidor, caixa manual (diagnóstico) | 29/39 (74 %) | 200/222 (90 %) |

1. **Com a segmentação do modelo, B não leu nenhuma das 39 fotos.** A caixa que ela devolve cobre quase o
   mostrador inteiro (mediana 125×85 em 160×120), não a janela dos dígitos (≈ 97×18).
2. **Com a janela certa, fatiamento e classificador acertam 88 % dos dígitos e 59 % das leituras.** O gargalo é
   a segmentação, não o classificador.
3. **O JPEG q90 quase não afeta a leitura:** 23/39 nos dois fluxos com caixa manual, e 194 contra 195 dígitos.
4. **Isso coincide com o firmware real.** Nas primeiras capturas em hardware a caixa também era enorme e a leitura
   errada (`02650090`, `300061`; ver `medicoes/debug_metricas.csv`); só depois de posicionar a câmera à mão, com a
   janela dos dígitos ocupando o quadro, a caixa encolheu (`30,51 → 149,75`) e a leitura estabilizou em `046663`.
   Rodar este pipeline nos frames reais 33–44 do firmware (que vêm com a caixa desenhada por cima, então é uma
   conferência aproximada) dá caixas próximas da registrada e lê `046663` ou `026663`, as mesmas duas leituras
   que a placa alternou.

## O que mais se testou para melhorar a leitura

Todos com a caixa marcada à mão (o oráculo) e o quadro 160×120, em scripts de análise que **não estão no
repositório**; só o alinhamento virou código (`--alinhar`, e os fluxos `*_alinhada` de `avaliar.py`).

| Ideia | Resultado |
|---|---|
| **Endireitar a fileira** (as fotos têm de -3° a -9° de inclinação). O ângulo vem das linhas de Hough, sem usar a caixa: erro mediano de 0,4° contra o ângulo medido na janela, 35 de 39 quadros dentro de 2° | **Ajuda**: 59 % → 74 % das leituras, 88 % → 90 % dos dígitos. Alinhando na foto original (como numa câmera montada reta) vai a 77 % |
| Endireitar e depois usar a segmentação do modelo | **Não ajuda**: a caixa do modelo continua com cerca de 85 px de altura (a janela tem 18) e 0/39 |
| Localizar a janela por um "pente" de bordas verticais periódicas, sem o modelo | **Falha**: IoU mediano 0,35 com a janela real, 0/39 leituras |
| Cortar nas divisórias reais (programação dinâmica sobre o perfil de colunas) em vez de fatias iguais | **Piora**: 62 % das leituras no melhor caso (divisória clara) contra 72 % das fatias iguais, e 21 % com a polaridade escura |
| Achar cada dígito por componentes conectados (OpenCV), sem caixa | **Falha**: 2/39 leituras; em 32 dos 39 quadros nem acha uma fileira de N dígitos (o dígito encosta na borda da célula) |
| Procurar, para cada dígito, a posição e a largura em que o classificador fica mais confiante | Ganho pequeno (+2 a +6 pontos de dígitos com erro na caixa de 2 a 5 px) a 15× o custo |
| Votar entre 5 caixas deslocadas ±2 px | Ajuda com a caixa imprecisa (49 % → 62 % com erro de ±2 px), a 5× o custo do classificador |
| Redução por média, bilinear ou contraste por fatia | Sem efeito (±2 dígitos em 222) |

**O que falta é achar a janela dos dígitos** (a caixa). Com ela marcada à mão e o quadro endireitado, a leitura
chega a 74 % das leituras e 90 % dos dígitos; sem ela, 0 %. Os erros que sobram estão no último dígito (rodinha
girando) e em fotos de contraste muito baixo (`00285`).

## Enquadramento físico fixo (janela numa região conhecida, sem segmentação)

`avaliar_roi_fixa.py` (resultado completo em `teste_comum/resultados/ROI_FIXA.md`). Por medidor, o recorte da foto é
fixo e a região da janela (ROI) é calibrada **uma vez**, com as fotos de uma leitura, e usada nas outras leituras do
mesmo medidor, repetindo com cada leitura como calibração. Fluxo nuvem (JPEG q90), quadro endireitado.

| Medidor | ROI | Leituras exatas | Dígitos certos |
|---|---|---|---|
| `tianjin6` (27 fotos, 14 leituras) | caixa verdadeira de cada foto (oráculo), com votação | 81 % | 96 % |
| `tianjin6` | uma ROI única (mediana), com votação | 37 % | 64 % |
| `tianjin6` | calibrada com uma leitura, com votação (pior 0 %, melhor 48 %) | 28 % | 53 % |
| `branco5` (12 fotos, 5 leituras) | caixa verdadeira de cada foto (oráculo) | 75 % | 90 % |
| `branco5` | qualquer ROI fixa | 0 % | 33–38 % |

**Por que a ROI fixa rende tão pouco aqui:** as fotos são de um monitor cujo zoom e posição mudam de uma leitura
para outra, então a ROI errada tem 3,5 a 5 px de erro médio em `tianjin6` e 12 a 18 px em `branco5`. Não é uma
montagem fixa de verdade; é um cenário pessimista. A curva abaixo mostra o que importa: quanto erro a leitura aguenta.

| Erro da ROI (±d px por coordenada) | Fatias iguais (leituras / dígitos) | Com votação entre 5 caixas |
|---|---|---|
| ±0 | 74 % / 90 % | 77 % / 94 % |
| ±1 | 74 % / 91 % | 78 % / 93 % |
| ±2 | 62 % / 87 % | 70 % / 90 % |
| ±3 | 56 % / 85 % | 67 % / 89 % |
| ±4 | 47 % / 79 % | 62 % / 85 % |
| ±6 | 25 % / 64 % | 34 % / 71 % |

**Leitura:** a ROI precisa ter cerca de **±1 a ±2 px de precisão no quadro 160×120** (um dígito tem ~16 px de largura) para
ficar na faixa de 70 a 78 % das leituras; acima de ±4 px a leitura cai rápido. A votação compensa uns 3 px de erro, ao
custo de rodar o classificador 5 vezes. A montagem mecânica (ou uma calibração que refine a ROI com vários quadros)
precisa chegar a essa precisão.

**Conferência com a calibração manual do autor** (`caixas_esp32_exemplo.json`, fora do repositório; script
`pipeline_nuvem.py` com caixa, rotação e `caixa_final` por foto): nas 5 fotos do JSON, lidas com o `.tflite` INT8 de B,
5/5 saem certas em 640×480, 320×240 e 160×120, e 4/5 em 160×120 com JPEG q90. Com a janela exata, a resolução não é o
limite. As rotações marcadas à mão (83°, 94° e 82° nas fotos 102, 122 e 124, que implicam −7°, +4° e −8° de inclinação)
batem com as estimativas automáticas por Hough (−5,5°, +3° e −9°) com diferença de até 1,5°.

## Limites

- A "borda" é uma **emulação** em Python: o quadro 160×120 vem da redução de uma foto 640×480, não do sensor, e os
  kernels são os de referência do TFLite, não a TFLM do ESP32. Os números comparam os dois fluxos entre si; não são
  a acurácia no hardware.
- O enquadramento (`centro_y`) e a `caixa_manual` foram escolhidos à mão. A caixa manual é um **oráculo** (limite
  superior do que a segmentação poderia dar), não um resultado do pipeline.
- O conjunto é pequeno, com poucas leituras distintas (19), de um monitor e de dois medidores, e várias fotos são
  quadros repetidos da mesma leitura. Não representa hidrômetros em campo.
- Não se simula perda de pacotes: o JPEG chega inteiro.
