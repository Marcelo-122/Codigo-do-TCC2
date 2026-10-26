# Cenário de enquadramento fixo (sem segmentação)

Gerado por `ocr/avaliar_roi_fixa.py`; protocolo no docstring do script. Fluxo nuvem (JPEG q90).

## Medidor `branco5` (12 fotos, 5 leituras, recorte fixo em y=246)

| Variante | ROI | Leituras exatas | Dígitos certos | Pior / melhor calibração (leituras) | Erro médio da ROI (px) |
|---|---|---|---|---|---|
| sem alinhar | caixa verdadeira de cada foto (oráculo) | 7/12 (58 %) | 49/60 (82 %) | - | 0 |
| sem alinhar | mediana de todas as leituras (50, 45, 103, 58) | 0/12 (0 %) | 23/60 (38 %) | - | 12.3 |
| sem alinhar | calibrada com UMA leitura, testada nas outras | 0/48 (0 %) | 94/240 (39 %) | 0 % / 0 % | 18.0 |
| alinhada | caixa verdadeira de cada foto (oráculo) | 8/12 (67 %) | 50/60 (83 %) | - | 0 |
| alinhada | mediana de todas as leituras (49, 44, 102, 57) | 0/12 (0 %) | 27/60 (45 %) | - | 11.9 |
| alinhada | calibrada com UMA leitura, testada nas outras | 0/48 (0 %) | 99/240 (41 %) | 0 % / 0 % | 17.4 |
| alinhada + votação | caixa verdadeira de cada foto (oráculo) | 8/12 (67 %) | 50/60 (83 %) | - | 0 |
| alinhada + votação | mediana de todas as leituras (49, 44, 102, 57) | 0/12 (0 %) | 27/60 (45 %) | - | 11.9 |
| alinhada + votação | calibrada com UMA leitura, testada nas outras | 0/48 (0 %) | 101/240 (42 %) | 0 % / 0 % | 17.4 |

## Medidor `tianjin6` (27 fotos, 14 leituras, recorte fixo em y=240)

| Variante | ROI | Leituras exatas | Dígitos certos | Pior / melhor calibração (leituras) | Erro médio da ROI (px) |
|---|---|---|---|---|---|
| sem alinhar | caixa verdadeira de cada foto (oráculo) | 14/27 (52 %) | 144/162 (89 %) | - | 0 |
| sem alinhar | mediana de todas as leituras (10, 49, 107, 67) | 3/27 (11 %) | 82/162 (51 %) | - | 3.4 |
| sem alinhar | calibrada com UMA leitura, testada nas outras | 24/351 (7 %) | 880/2106 (42 %) | 0 % / 28 % | 4.8 |
| alinhada | caixa verdadeira de cada foto (oráculo) | 23/27 (85 %) | 156/162 (96 %) | - | 0 |
| alinhada | mediana de todas as leituras (10, 46, 107, 64) | 5/27 (19 %) | 75/162 (46 %) | - | 3.5 |
| alinhada | calibrada com UMA leitura, testada nas outras | 90/351 (26 %) | 1055/2106 (50 %) | 0 % / 48 % | 4.9 |
| alinhada + votação | caixa verdadeira de cada foto (oráculo) | 25/27 (93 %) | 160/162 (99 %) | - | 0 |
| alinhada + votação | mediana de todas as leituras (10, 46, 107, 64) | 13/27 (48 %) | 103/162 (64 %) | - | 3.5 |
| alinhada + votação | calibrada com UMA leitura, testada nas outras | 105/351 (30 %) | 1129/2106 (54 %) | 0 % / 50 % | 4.9 |

## Tolerância ao erro da ROI (alinhada, todas as 39 fotos)

Erro aleatório uniforme de ±d px somado a cada coordenada da caixa verdadeira (média de 3 sorteios).

| d (px) | Leituras exatas, fatias iguais | Dígitos certos | Leituras exatas, votação | Dígitos certos |
|---|---|---|---|---|
| ±0 | 82 % | 92 % | 87 % | 95 % |
| ±1 | 71 % | 90 % | 81 % | 94 % |
| ±2 | 62 % | 88 % | 70 % | 91 % |
| ±3 | 51 % | 84 % | 64 % | 89 % |
| ±4 | 40 % | 78 % | 50 % | 83 % |
| ±6 | 20 % | 64 % | 26 % | 68 % |

## Como ler

- **Oráculo**: usa a caixa marcada à mão de cada foto (o melhor que a variante daria com a janela perfeita).
- **Mediana**: uma ROI única para o medidor, a mediana das caixas verdadeiras (calibrar com todas as fotos).
- **Uma leitura**: o caso realista de uma calibração de instalação com uma só foto; as taxas somam todas as
  fotos de teste de todas as calibrações possíveis, e a coluna mostra o pior e o melhor grupo de calibração.
- O erro da ROI é a média de |caixa verdadeira - ROI| nas quatro coordenadas, em pixels do quadro 160×120.

