# Cenário de enquadramento fixo (sem segmentação)

Gerado por `ocr/avaliar_roi_fixa.py`; protocolo no docstring do script. Fluxo nuvem (JPEG q90).

## Medidor `branco5` (12 fotos, 5 leituras, recorte fixo em y=246)

| Variante | ROI | Leituras exatas | Dígitos certos | Pior / melhor calibração (leituras) | Erro médio da ROI (px) |
|---|---|---|---|---|---|
| sem alinhar | caixa verdadeira de cada foto (oráculo) | 9/12 (75 %) | 54/60 (90 %) | - | 0 |
| sem alinhar | mediana de todas as leituras (50, 45, 103, 58) | 0/12 (0 %) | 23/60 (38 %) | - | 12.3 |
| sem alinhar | calibrada com UMA leitura, testada nas outras | 0/48 (0 %) | 79/240 (33 %) | 0 % / 0 % | 18.0 |
| alinhada | caixa verdadeira de cada foto (oráculo) | 9/12 (75 %) | 52/60 (87 %) | - | 0 |
| alinhada | mediana de todas as leituras (49, 44, 102, 57) | 0/12 (0 %) | 19/60 (32 %) | - | 11.9 |
| alinhada | calibrada com UMA leitura, testada nas outras | 0/48 (0 %) | 84/240 (35 %) | 0 % / 0 % | 17.4 |
| alinhada + votação | caixa verdadeira de cada foto (oráculo) | 9/12 (75 %) | 54/60 (90 %) | - | 0 |
| alinhada + votação | mediana de todas as leituras (49, 44, 102, 57) | 0/12 (0 %) | 19/60 (32 %) | - | 11.9 |
| alinhada + votação | calibrada com UMA leitura, testada nas outras | 0/48 (0 %) | 81/240 (34 %) | 0 % / 0 % | 17.4 |

## Medidor `tianjin6` (27 fotos, 14 leituras, recorte fixo em y=240)

| Variante | ROI | Leituras exatas | Dígitos certos | Pior / melhor calibração (leituras) | Erro médio da ROI (px) |
|---|---|---|---|---|---|
| sem alinhar | caixa verdadeira de cada foto (oráculo) | 11/27 (41 %) | 139/162 (86 %) | - | 0 |
| sem alinhar | mediana de todas as leituras (10, 49, 107, 67) | 2/27 (7 %) | 86/162 (53 %) | - | 3.4 |
| sem alinhar | calibrada com UMA leitura, testada nas outras | 42/351 (12 %) | 931/2106 (44 %) | 0 % / 32 % | 4.8 |
| alinhada | caixa verdadeira de cada foto (oráculo) | 20/27 (74 %) | 150/162 (93 %) | - | 0 |
| alinhada | mediana de todas as leituras (10, 46, 107, 64) | 9/27 (33 %) | 98/162 (60 %) | - | 3.5 |
| alinhada | calibrada com UMA leitura, testada nas outras | 84/351 (24 %) | 1049/2106 (50 %) | 0 % / 48 % | 4.9 |
| alinhada + votação | caixa verdadeira de cada foto (oráculo) | 22/27 (81 %) | 155/162 (96 %) | - | 0 |
| alinhada + votação | mediana de todas as leituras (10, 46, 107, 64) | 10/27 (37 %) | 104/162 (64 %) | - | 3.5 |
| alinhada + votação | calibrada com UMA leitura, testada nas outras | 98/351 (28 %) | 1110/2106 (53 %) | 0 % / 48 % | 4.9 |

## Tolerância ao erro da ROI (alinhada, todas as 39 fotos)

Erro aleatório uniforme de ±d px somado a cada coordenada da caixa verdadeira (média de 3 sorteios).

| d (px) | Leituras exatas, fatias iguais | Dígitos certos | Leituras exatas, votação | Dígitos certos |
|---|---|---|---|---|
| ±0 | 74 % | 90 % | 77 % | 94 % |
| ±1 | 74 % | 91 % | 78 % | 93 % |
| ±2 | 62 % | 87 % | 70 % | 90 % |
| ±3 | 56 % | 85 % | 67 % | 89 % |
| ±4 | 47 % | 79 % | 62 % | 85 % |
| ±6 | 25 % | 64 % | 34 % | 71 % |

## Como ler

- **Oráculo**: usa a caixa marcada à mão de cada foto (o melhor que a variante daria com a janela perfeita).
- **Mediana**: uma ROI única para o medidor, a mediana das caixas verdadeiras (calibrar com todas as fotos).
- **Uma leitura**: o caso realista de uma calibração de instalação com uma só foto; as taxas somam todas as
  fotos de teste de todas as calibrações possíveis, e a coluna mostra o pior e o melhor grupo de calibração.
- O erro da ROI é a média de |caixa verdadeira - ROI| nas quatro coordenadas, em pixels do quadro 160×120.

