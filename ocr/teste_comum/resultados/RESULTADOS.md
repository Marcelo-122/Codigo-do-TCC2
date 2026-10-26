# Resultados: Pipeline B, borda emulada × nuvem

Gerado por `ocr/avaliar.py`. Conjunto: `ocr/teste_comum/` (fotos da ESP32-CAM de um monitor).
A borda é uma **emulação** em Python (ver o docstring de `ocr/avaliar.py`); os números
comparam os dois fluxos entre si e **não** são a acurácia no hardware.

## Resumo

Os fluxos `*_caixa_manual` são **diagnóstico**: pulam a segmentação e usam a caixa marcada à mão. Os `*_alinhada` endireitam o quadro no servidor antes de ler (ângulo estimado sem a caixa).

| Fluxo | Leituras exatas | Dígitos certos | Sem caixa | Caixa mediana (L×A, de 160×120) |
|---|---|---|---|---|
| borda | 0/39 (0 %) | 34/222 (15 %) | 0 | 130×90 |
| nuvem | 0/39 (0 %) | 35/222 (16 %) | 0 | 129×90 |
| borda_caixa_manual | 18/39 (46 %) | 189/222 (85 %) | 0 | 97×18 |
| nuvem_caixa_manual | 18/39 (46 %) | 189/222 (85 %) | 0 | 97×18 |
| nuvem_alinhada | 0/39 (0 %) | 41/222 (18 %) | 0 | 126×90 |
| nuvem_alinhada_caixa_manual | 32/39 (82 %) | 205/222 (92 %) | 0 | 97×18 |

## Custo de transmissão

Imagem JPEG q90 remontada no servidor: mediana 5224 bytes (3368–5749), 30 pacotes LoRa de 175 bytes. A borda enviaria só a leitura (poucos bytes, 1 pacote).

## Por medidor

| Medidor | Fluxo | Leituras exatas | Dígitos certos |
|---|---|---|---|
| branco5 | borda | 0/12 | 11/60 (18 %) |
| branco5 | nuvem | 0/12 | 11/60 (18 %) |
| branco5 | borda_caixa_manual | 7/12 | 48/60 (80 %) |
| branco5 | nuvem_caixa_manual | 7/12 | 49/60 (82 %) |
| branco5 | nuvem_alinhada | 0/12 | 13/60 (22 %) |
| branco5 | nuvem_alinhada_caixa_manual | 9/12 | 48/60 (80 %) |
| tianjin6 | borda | 0/27 | 23/162 (14 %) |
| tianjin6 | nuvem | 0/27 | 24/162 (15 %) |
| tianjin6 | borda_caixa_manual | 11/27 | 141/162 (87 %) |
| tianjin6 | nuvem_caixa_manual | 11/27 | 140/162 (86 %) |
| tianjin6 | nuvem_alinhada | 0/27 | 28/162 (17 %) |
| tianjin6 | nuvem_alinhada_caixa_manual | 23/27 | 157/162 (97 %) |

## Por confiança do gabarito

| Confiança | Fluxo | Leituras exatas |
|---|---|---|
| alta | borda | 0/30 |
| alta | nuvem | 0/30 |
| alta | borda_caixa_manual | 13/30 |
| alta | nuvem_caixa_manual | 13/30 |
| alta | nuvem_alinhada | 0/30 |
| alta | nuvem_alinhada_caixa_manual | 25/30 |
| media | borda | 0/9 |
| media | nuvem | 0/9 |
| media | borda_caixa_manual | 5/9 |
| media | nuvem_caixa_manual | 5/9 |
| media | nuvem_alinhada | 0/9 |
| media | nuvem_alinhada_caixa_manual | 7/9 |

## Concordância borda × nuvem

Leitura idêntica nos dois fluxos em 10/39 imagens.

## Por imagem

| Imagem | Real | Lido (borda) | Lido (nuvem) | Caixa da segmentação (nuvem) | Lido (caixa manual) | Lido (alinhada, caixa manual) |
|---|---|---|---|---|---|---|
| 13 | 00399 | 71073 | 10000 | 35,42,125,116 | 00399 | 00399 |
| 15 | 00399 | 01070 | 74120 | 25,42,125,116 | 00399 | 00399 |
| 17 | 00399 | 04000 | 74120 | 26,42,125,116 | 00399 | 00399 |
| 19 | 00285 | 07300 | 70705 | 41,47,106,113 | 90305 | 03300 |
| 22 | 00285 | 70000 | 70001 | 40,47,100,115 | 00305 | 03000 |
| 24 | 00285 | 70001 | 70703 | 42,47,106,115 | 00305 | 03000 |
| 30 | 058112 | 050737 | 050737 | 5,22,132,116 | 058112 | 058112 |
| 31 | 058112 | 050737 | 050737 | 5,22,132,116 | 058112 | 058112 |
| 32 | 058112 | 050737 | 050737 | 5,22,132,116 | 058112 | 058112 |
| 51 | 027535 | 550515 | 552505 | 5,21,147,118 | 027539 | 027535 |
| 52 | 027535 | 005015 | 005015 | 6,21,148,117 | 027534 | 027535 |
| 55 | 027543 | 553007 | 553007 | 5,27,145,117 | 027593 | 027543 |
| 56 | 027543 | 553007 | 553007 | 5,27,145,117 | 027593 | 027543 |
| 61 | 027571 | 553017 | 553007 | 5,25,145,117 | 027571 | 027571 |
| 63 | 027571 | 555417 | 553077 | 5,25,145,117 | 027571 | 027571 |
| 64 | 027571 | 555177 | 553017 | 5,25,145,117 | 027571 | 027571 |
| 65 | 027587 | 555014 | 555015 | 5,26,145,117 | 027587 | 027587 |
| 66 | 027587 | 555014 | 553047 | 5,25,145,117 | 027587 | 027587 |
| 69 | 027632 | 542214 | 542210 | 5,20,145,118 | 027632 | 027632 |
| 70 | 021167 | 050302 | 050314 | 6,19,136,118 | 021165 | 021167 |
| 71 | 021167 | 050314 | 050302 | 5,19,137,118 | 021165 | 021167 |
| 72 | 021171 | 250731 | 250734 | 5,29,138,116 | 021711 | 041111 |
| 73 | 021171 | 050734 | 553134 | 10,29,138,116 | 021011 | 021111 |
| 76 | 021224 | 054010 | 551030 | 9,29,138,116 | 021201 | 021204 |
| 77 | 021224 | 054010 | 551030 | 10,28,138,116 | 021201 | 021204 |
| 78 | 021235 | 257030 | 257030 | 10,27,138,116 | 021230 | 021235 |
| 79 | 021235 | 050030 | 050130 | 9,27,138,117 | 021237 | 021235 |
| 80 | 021317 | 220030 | 251030 | 9,26,138,117 | 021307 | 021317 |
| 102 | 046663 | 025535 | 025535 | 5,23,138,117 | 046603 | 046663 |
| 105 | 046671 | 525717 | 525717 | 6,25,138,118 | 046602 | 046671 |
| 108 | 046671 | 525717 | 525717 | 6,25,138,118 | 046602 | 046671 |
| 109 | 000528 | 535119 | 127574 | 5,13,135,118 | 000528 | 000528 |
| 110 | 000528 | 530710 | 550706 | 5,22,136,118 | 000528 | 000528 |
| 120 | 00338 | 70017 | 70002 | 56,47,140,116 | 00338 | 00338 |
| 121 | 00338 | 74072 | 77072 | 56,47,136,116 | 00338 | 00338 |
| 122 | 00042 | 71072 | 07072 | 52,48,150,116 | 00042 | 00042 |
| 123 | 00042 | 71070 | 07070 | 52,48,151,116 | 00042 | 00042 |
| 124 | 00926 | 01071 | 71705 | 52,45,151,116 | 90928 | 00926 |
| 125 | 00926 | 01075 | 71779 | 54,45,147,116 | 90929 | 00926 |

As imagens com a caixa e as fatias desenhadas estão em `caixas_nuvem_*.jpg` (segmentação do modelo) e `caixas_nuvem_alinhada_caixa_manual_*.jpg` (caixa manual, quadro endireitado).
