# ROI fixa no hidrômetro físico (30 quadros rotulados)

Gerado por `avaliar_roi_fixa_fisico.py` em 2026-11-18. Medidor `fisico_1`, câmera parada, quadros 160x120 crus de `quadros_160x120.csv`: 33 quadros, 3 com `?` fora das contas, 26 leituras distintas de `000025` a `000052`, luz dia. Classificador `modelo_digito.tflite` (sha256 206755334fa3), INT8, sem segmentação, mesmas contas do `transmissor_ocr_esp32cam` em modo `roi`.

| Posição da câmera | A partir de | ROI | Caixa | Face | Realce na placa | Calibrada em | Quadros rotulados |
|---|---|---|---|---|---|---|---|
| A | q_0001.png | `roi_fisico_1_posicao_a.json` | `22,81,152,111` | 14-74 % | 0 | `000025` | 8 |
| B | q_0010.png | `roi_fisico_1.json` | `21,69,151,95` | 14-74 % | 0 | `000032` | 22 |

## Fluxo borda (quadro direto, como na placa)

| Pré-processamento | Leituras exatas | Dígitos | Dois últimos dígitos | Roda das unidades |
|---|---|---|---|---|
| sem pré-processamento | 2/30 (7 %; IC 95 % 2–21 %) | 136/180 (76 %) | 18/60 (30 %) | 11/30 (37 %) |
| só a face | 25/30 (83 %; IC 95 % 66–93 %) | 175/180 (97 %) | 55/60 (92 %) | 25/30 (83 %) |
| só o realce | 5/30 (17 %; IC 95 % 7–34 %) | 141/180 (78 %) | 25/60 (42 %) | 11/30 (37 %) |
| face + realce | 24/30 (80 %; IC 95 % 63–90 %) | 174/180 (97 %) | 54/60 (90 %) | 24/30 (80 %) |

## Fluxo nuvem (quadro depois do JPEG q90)

| Pré-processamento | Leituras exatas | Dígitos | Dois últimos dígitos | Roda das unidades |
|---|---|---|---|---|
| sem pré-processamento | 2/30 (7 %; IC 95 % 2–21 %) | 136/180 (76 %) | 18/60 (30 %) | 11/30 (37 %) |
| só a face | 25/30 (83 %; IC 95 % 66–93 %) | 175/180 (97 %) | 55/60 (92 %) | 25/30 (83 %) |
| só o realce | 5/30 (17 %; IC 95 % 7–34 %) | 143/180 (79 %) | 25/60 (42 %) | 11/30 (37 %) |
| face + realce | 23/30 (77 %; IC 95 % 59–88 %) | 173/180 (96 %) | 54/60 (90 %) | 24/30 (80 %) |

## Teste independente (fluxo borda)

Sem as fotos cuja leitura é a mesma usada na calibração da sua posição (a face e o realce foram escolhidos olhando essa leitura).

| Pré-processamento | Leituras exatas | Dígitos | Dois últimos dígitos | Roda das unidades |
|---|---|---|---|---|
| sem pré-processamento | 2/28 (7 %; IC 95 % 2–23 %) | 126/168 (75 %) | 16/56 (29 %) | 10/28 (36 %) |
| só a face | 23/28 (82 %; IC 95 % 64–92 %) | 163/168 (97 %) | 51/56 (91 %) | 23/28 (82 %) |
| só o realce | 5/28 (18 %; IC 95 % 8–36 %) | 131/168 (78 %) | 23/56 (41 %) | 10/28 (36 %) |
| face + realce | 22/28 (79 %; IC 95 % 60–90 %) | 162/168 (96 %) | 50/56 (89 %) | 22/28 (79 %) |

## Por posição da câmera (fluxo borda, configuração gravada na placa)

| Posição  | Leituras exatas | Dígitos | Dois últimos dígitos | Roda das unidades |
|---|---|---|---|---|
| A (`roi_fisico_1_posicao_a.json`) | 7/8 (88 %; IC 95 % 53–98 %) | 47/48 (98 %) | 15/16 (94 %) | 7/8 (88 %) |
| B (`roi_fisico_1.json`) | 18/22 (82 %; IC 95 % 61–93 %) | 128/132 (97 %) | 40/44 (91 %) | 18/22 (82 %) |

## Erros (fluxo borda, configuração gravada na placa)

| Quadro | Rótulo | Lido |
|---|---|---|
| q_0003.png | 000027 | 000020 |
| q_0012.png | 000034 | 000030 |
| q_0016.png | 000037 | 000030 |
| q_0021.png | 000041 | 000040 |
| q_0022.png | 000041 | 000040 |

Detalhe de cada quadro, fluxo e variante em `roi_fixa_fisico_por_foto.csv`.

**Limites:** um medidor e uma iluminação; os quatro primeiros dígitos são sempre 0 (por isso as colunas dos dois últimos e da roda das unidades); a face e o realce foram escolhidos neste mesmo medidor. O resultado mede a leitura com a câmera fixa e calibrada, não a generalização para outro hidrômetro (nas 21 fotos avulsas que o `dados/teste/` tinha antes, 12 delas de medidores de gás ou indefinidos, a mesma face e o realce pioraram a leitura).
