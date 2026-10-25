# Resultados: Pipeline B, borda emulada × nuvem

Gerado por `ocr/avaliar.py`. Conjunto: `ocr/teste_comum/` (fotos da ESP32-CAM de um monitor).
A borda é uma **emulação** em Python (ver o docstring de `ocr/avaliar.py`); os números
comparam os dois fluxos entre si e **não** são a acurácia no hardware.

## Resumo

Os fluxos `*_caixa_manual` são **diagnóstico**: pulam a segmentação e usam a caixa marcada à mão. Os `*_alinhada` endireitam o quadro no servidor antes de ler (ângulo estimado sem a caixa).

| Fluxo | Leituras exatas | Dígitos certos | Sem caixa | Caixa mediana (L×A, de 160×120) |
|---|---|---|---|---|
| borda | 0/39 (0 %) | 44/222 (20 %) | 0 | 125×85 |
| nuvem | 0/39 (0 %) | 42/222 (19 %) | 0 | 125×84 |
| borda_caixa_manual | 23/39 (59 %) | 195/222 (88 %) | 0 | 97×18 |
| nuvem_caixa_manual | 23/39 (59 %) | 194/222 (87 %) | 0 | 97×18 |
| nuvem_alinhada | 0/39 (0 %) | 39/222 (18 %) | 3 | 118×84 |
| nuvem_alinhada_caixa_manual | 29/39 (74 %) | 200/222 (90 %) | 0 | 97×18 |

## Custo de transmissão

Imagem JPEG q90 remontada no servidor: mediana 5224 bytes (3368–5749), 30 pacotes LoRa de 175 bytes. A borda enviaria só a leitura (poucos bytes, 1 pacote).

## Por medidor

| Medidor | Fluxo | Leituras exatas | Dígitos certos |
|---|---|---|---|
| branco5 | borda | 0/12 | 16/60 (27 %) |
| branco5 | nuvem | 0/12 | 17/60 (28 %) |
| branco5 | borda_caixa_manual | 9/12 | 54/60 (90 %) |
| branco5 | nuvem_caixa_manual | 9/12 | 54/60 (90 %) |
| branco5 | nuvem_alinhada | 0/12 | 6/60 (10 %) |
| branco5 | nuvem_alinhada_caixa_manual | 9/12 | 53/60 (88 %) |
| tianjin6 | borda | 0/27 | 28/162 (17 %) |
| tianjin6 | nuvem | 0/27 | 25/162 (15 %) |
| tianjin6 | borda_caixa_manual | 14/27 | 141/162 (87 %) |
| tianjin6 | nuvem_caixa_manual | 14/27 | 140/162 (86 %) |
| tianjin6 | nuvem_alinhada | 0/27 | 33/162 (20 %) |
| tianjin6 | nuvem_alinhada_caixa_manual | 20/27 | 147/162 (91 %) |

## Por confiança do gabarito

| Confiança | Fluxo | Leituras exatas |
|---|---|---|
| alta | borda | 0/30 |
| alta | nuvem | 0/30 |
| alta | borda_caixa_manual | 18/30 |
| alta | nuvem_caixa_manual | 18/30 |
| alta | nuvem_alinhada | 0/30 |
| alta | nuvem_alinhada_caixa_manual | 24/30 |
| media | borda | 0/9 |
| media | nuvem | 0/9 |
| media | borda_caixa_manual | 5/9 |
| media | nuvem_caixa_manual | 5/9 |
| media | nuvem_alinhada | 0/9 |
| media | nuvem_alinhada_caixa_manual | 5/9 |

## Concordância borda × nuvem

Leitura idêntica nos dois fluxos em 4/39 imagens.

## Por imagem

| Imagem | Real | Lido (borda) | Lido (nuvem) | Caixa da segmentação (nuvem) | Lido (caixa manual) | Lido (alinhada, caixa manual) |
|---|---|---|---|---|---|---|
| 13 | 00399 | 40747 | 40120 | 40,42,113,111 | 00399 | 00399 |
| 15 | 00399 | 40100 | 40143 | 40,42,124,108 | 00399 | 00399 |
| 17 | 00399 | 40749 | 40749 | 40,42,115,108 | 00399 | 00399 |
| 19 | 00285 | 00000 | 00000 | 70,48,75,51 | 00055 | 00000 |
| 22 | 00285 | 00000 | 00000 | 70,48,75,51 | 00005 | 00005 |
| 24 | 00285 | 00000 | 00000 | 70,50,74,51 | 00005 | 00005 |
| 30 | 058112 | 252100 | 254030 | 5,22,130,116 | 058112 | 058112 |
| 31 | 058112 | 252034 | 252100 | 5,25,130,116 | 058112 | 058112 |
| 32 | 058112 | 252000 | 252234 | 5,23,131,116 | 058112 | 058114 |
| 51 | 027535 | 220010 | 521000 | 10,30,145,116 | 027534 | 027535 |
| 52 | 027535 | 002000 | 521010 | 10,30,145,116 | 027534 | 027535 |
| 55 | 027543 | 504435 | 001105 | 6,30,145,116 | 027543 | 027543 |
| 56 | 027543 | 504435 | 101105 | 6,30,145,116 | 027543 | 027543 |
| 61 | 027571 | 504700 | 504784 | 6,32,145,116 | 027571 | 027571 |
| 63 | 027571 | 504000 | 554784 | 6,32,145,116 | 027571 | 027571 |
| 64 | 027571 | 500510 | 400200 | 6,28,131,116 | 027571 | 027571 |
| 65 | 027587 | 007700 | 504004 | 6,32,145,114 | 027587 | 027587 |
| 66 | 027587 | 004034 | 007704 | 6,31,145,114 | 027587 | 027587 |
| 69 | 027632 | 031704 | 002700 | 20,20,145,111 | 027632 | 027632 |
| 70 | 021167 | 037030 | 329050 | 10,20,136,108 | 021160 | 021167 |
| 71 | 021167 | 230130 | 329050 | 10,20,136,108 | 021160 | 021167 |
| 72 | 021171 | 242334 | 250304 | 10,32,135,116 | 021740 | 044104 |
| 73 | 021171 | 034330 | 240310 | 10,32,136,116 | 021540 | 021100 |
| 76 | 021224 | 322004 | 245000 | 10,32,138,116 | 021201 | 001014 |
| 77 | 021224 | 322004 | 245000 | 10,32,138,116 | 021201 | 001014 |
| 78 | 021235 | 905030 | 071050 | 10,35,137,116 | 021030 | 021235 |
| 79 | 021235 | 205030 | 751030 | 10,35,136,115 | 021030 | 021235 |
| 80 | 021317 | 220731 | 225130 | 10,30,135,115 | 021301 | 021317 |
| 102 | 046663 | 202450 | 505525 | 12,27,135,116 | 046663 | 046663 |
| 105 | 046671 | 005402 | 055228 | 11,27,136,116 | 046674 | 046670 |
| 108 | 046671 | 005027 | 055228 | 10,27,137,116 | 046674 | 046670 |
| 109 | 000528 | 204530 | 004531 | 5,25,125,115 | 000528 | 000528 |
| 110 | 000528 | 004531 | 200220 | 5,16,125,115 | 000528 | 000528 |
| 120 | 00338 | 45044 | 40741 | 73,47,131,105 | 00338 | 00338 |
| 121 | 00338 | 04044 | 73011 | 65,47,130,103 | 00338 | 00338 |
| 122 | 00042 | 74072 | 03000 | 60,48,140,103 | 00042 | 00042 |
| 123 | 00042 | 14075 | 09000 | 60,48,141,105 | 00042 | 00042 |
| 124 | 00926 | 14012 | 04000 | 46,46,148,116 | 00926 | 00926 |
| 125 | 00926 | 04022 | 04000 | 46,46,148,116 | 00926 | 00926 |

As imagens com a caixa e as fatias desenhadas estão em `caixas_nuvem_*.jpg` (segmentação do modelo) e `caixas_nuvem_alinhada_caixa_manual_*.jpg` (caixa manual, quadro endireitado).
