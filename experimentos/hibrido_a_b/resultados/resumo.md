# Resultado do teste híbrido (gerado por teste_hibrido.py)

Leitura exata = número igual ao gabarito, ignorando zeros à esquerda. IC = intervalo de Wilson de 95%. CER = distância de edição / tamanho do gabarito.


## dominio_B / recorte `manual`

| Leitor | n | sem recorte | leitura exata | IC 95% | CER médio |
|---|---|---|---|---|---|
| B_Nverd | 3 | 0 | 3 (100%) | 44%–100% | 0.00 |
| B_proj | 3 | 0 | 3 (100%) | 44%–100% | 0.00 |
| B_N8 | 3 | 0 | 3 (100%) | 44%–100% | 0.00 |
| B_N6 | 3 | 0 | 0 (0%) | 0%–56% | 0.44 |
| A_orig | 3 | 0 | 0 (0%) | 0%–56% | 0.41 |
| A_sint | 3 | 0 | 0 (0%) | 0%–56% | 0.45 |
| A_sint_sim | 3 | 0 | 0 (0%) | 0%–56% | 0.37 |

## dominio_B / recorte `seg_dev`

| Leitor | n | sem recorte | leitura exata | IC 95% | CER médio |
|---|---|---|---|---|---|
| B_Nverd | 3 | 0 | 0 (0%) | 0%–56% | 1.00 |
| B_proj | 3 | 0 | 0 (0%) | 0%–56% | 1.00 |
| B_N8 | 3 | 0 | 0 (0%) | 0%–56% | 1.00 |
| B_N6 | 3 | 0 | 0 (0%) | 0%–56% | 0.90 |
| A_orig | 3 | 0 | 0 (0%) | 0%–56% | 0.95 |
| A_sint | 3 | 0 | 0 (0%) | 0%–56% | 0.90 |
| A_sint_sim | 3 | 0 | 0 (0%) | 0%–56% | 0.90 |

## dominio_B / recorte `seg_rect`

| Leitor | n | sem recorte | leitura exata | IC 95% | CER médio |
|---|---|---|---|---|---|
| B_Nverd | 3 | 1 | 0 (0%) | 0%–56% | 0.95 |
| B_proj | 3 | 1 | 0 (0%) | 0%–56% | 0.95 |
| B_N8 | 3 | 1 | 0 (0%) | 0%–56% | 0.95 |
| B_N6 | 3 | 1 | 0 (0%) | 0%–56% | 0.79 |
| A_orig | 3 | 1 | 0 (0%) | 0%–56% | 0.90 |
| A_sint | 3 | 1 | 0 (0%) | 0%–56% | 0.90 |
| A_sint_sim | 3 | 1 | 0 (0%) | 0%–56% | 0.94 |

## kaggle_heldout_A_viu_B / recorte `gt_blackout`

| Leitor | n | sem recorte | leitura exata | IC 95% | CER médio |
|---|---|---|---|---|---|
| B_Nverd | 43 | 0 | 14 (33%) | 20%–47% | 0.28 |
| B_proj | 43 | 0 | 18 (42%) | 28%–57% | 0.23 |
| B_N8 | 43 | 0 | 14 (33%) | 20%–47% | 0.28 |
| B_N6 | 43 | 0 | 0 (0%) | 0%–8% | 0.61 |
| A_orig | 43 | 0 | 20 (47%) | 33%–61% | 0.12 |
| A_sint | 43 | 0 | 24 (56%) | 41%–70% | 0.10 |
| A_sint_sim | 43 | 0 | 28 (65%) | 50%–78% | 0.07 |

## kaggle_heldout_A_viu_B / recorte `gt_rect`

| Leitor | n | sem recorte | leitura exata | IC 95% | CER médio |
|---|---|---|---|---|---|
| B_Nverd | 43 | 0 | 24 (56%) | 41%–70% | 0.14 |
| B_proj | 43 | 0 | 28 (65%) | 50%–78% | 0.10 |
| B_N8 | 43 | 0 | 24 (56%) | 41%–70% | 0.14 |
| B_N6 | 43 | 0 | 0 (0%) | 0%–8% | 0.55 |
| A_orig | 43 | 0 | 24 (56%) | 41%–70% | 0.11 |
| A_sint | 43 | 0 | 27 (63%) | 48%–76% | 0.07 |
| A_sint_sim | 43 | 0 | 33 (77%) | 62%–87% | 0.05 |

## kaggle_heldout_A_viu_B / recorte `seg_rect`

| Leitor | n | sem recorte | leitura exata | IC 95% | CER médio |
|---|---|---|---|---|---|
| B_Nverd | 43 | 1 | 3 (7%) | 2%–19% | 0.91 |
| B_proj | 43 | 1 | 2 (5%) | 1%–15% | 0.92 |
| B_N8 | 43 | 1 | 3 (7%) | 2%–19% | 0.91 |
| B_N6 | 43 | 1 | 0 (0%) | 0%–8% | 0.79 |
| A_orig | 43 | 1 | 3 (7%) | 2%–19% | 0.68 |
| A_sint | 43 | 1 | 4 (9%) | 4%–22% | 0.64 |
| A_sint_sim | 43 | 1 | 3 (7%) | 2%–19% | 0.66 |

## kaggle_heldout_ambos / recorte `gt_blackout`

| Leitor | n | sem recorte | leitura exata | IC 95% | CER médio |
|---|---|---|---|---|---|
| B_Nverd | 205 | 0 | 47 (23%) | 18%–29% | 0.49 |
| B_proj | 205 | 0 | 47 (23%) | 18%–29% | 0.49 |
| B_N8 | 205 | 0 | 47 (23%) | 18%–29% | 0.49 |
| B_N6 | 205 | 0 | 0 (0%) | 0%–2% | 0.70 |
| A_orig | 205 | 0 | 130 (63%) | 57%–70% | 0.13 |
| A_sint | 205 | 0 | 140 (68%) | 62%–74% | 0.13 |
| A_sint_sim | 205 | 0 | 136 (66%) | 60%–72% | 0.13 |

## kaggle_heldout_ambos / recorte `gt_rect`

| Leitor | n | sem recorte | leitura exata | IC 95% | CER médio |
|---|---|---|---|---|---|
| B_Nverd | 205 | 0 | 49 (24%) | 19%–30% | 0.48 |
| B_proj | 205 | 0 | 49 (24%) | 19%–30% | 0.48 |
| B_N8 | 205 | 0 | 49 (24%) | 19%–30% | 0.48 |
| B_N6 | 205 | 0 | 0 (0%) | 0%–2% | 0.69 |
| A_orig | 205 | 0 | 118 (58%) | 51%–64% | 0.19 |
| A_sint | 205 | 0 | 128 (62%) | 56%–69% | 0.18 |
| A_sint_sim | 205 | 0 | 122 (60%) | 53%–66% | 0.19 |

## kaggle_heldout_ambos / recorte `seg_rect`

| Leitor | n | sem recorte | leitura exata | IC 95% | CER médio |
|---|---|---|---|---|---|
| B_Nverd | 205 | 12 | 0 (0%) | 0%–2% | 0.98 |
| B_proj | 205 | 12 | 0 (0%) | 0%–2% | 0.98 |
| B_N8 | 205 | 12 | 0 (0%) | 0%–2% | 0.98 |
| B_N6 | 205 | 12 | 2 (1%) | 0%–3% | 0.87 |
| A_orig | 205 | 12 | 9 (4%) | 2%–8% | 0.77 |
| A_sint | 205 | 12 | 9 (4%) | 2%–8% | 0.76 |
| A_sint_sim | 205 | 12 | 10 (5%) | 3%–9% | 0.73 |

## kaggle_treino_A / recorte `gt_blackout`

| Leitor | n | sem recorte | leitura exata | IC 95% | CER médio |
|---|---|---|---|---|---|
| B_Nverd | 250 | 0 | 72 (29%) | 24%–35% | 0.41 |
| B_proj | 250 | 0 | 71 (28%) | 23%–34% | 0.41 |
| B_N8 | 250 | 0 | 72 (29%) | 24%–35% | 0.41 |
| B_N6 | 250 | 0 | 0 (0%) | 0%–2% | 0.66 |
| A_orig | 250 | 0 | 199 (80%) | 74%–84% | 0.06 |
| A_sint | 250 | 0 | 200 (80%) | 75%–84% | 0.06 |
| A_sint_sim | 250 | 0 | 204 (82%) | 76%–86% | 0.06 |

## kaggle_treino_A / recorte `gt_rect`

| Leitor | n | sem recorte | leitura exata | IC 95% | CER médio |
|---|---|---|---|---|---|
| B_Nverd | 250 | 0 | 89 (36%) | 30%–42% | 0.36 |
| B_proj | 250 | 0 | 93 (37%) | 31%–43% | 0.36 |
| B_N8 | 250 | 0 | 89 (36%) | 30%–42% | 0.36 |
| B_N6 | 250 | 0 | 0 (0%) | 0%–2% | 0.65 |
| A_orig | 250 | 0 | 183 (73%) | 67%–78% | 0.11 |
| A_sint | 250 | 0 | 185 (74%) | 68%–79% | 0.11 |
| A_sint_sim | 250 | 0 | 185 (74%) | 68%–79% | 0.11 |

## kaggle_treino_A / recorte `seg_rect`

| Leitor | n | sem recorte | leitura exata | IC 95% | CER médio |
|---|---|---|---|---|---|
| B_Nverd | 250 | 15 | 4 (2%) | 1%–4% | 0.93 |
| B_proj | 250 | 15 | 5 (2%) | 1%–5% | 0.93 |
| B_N8 | 250 | 15 | 4 (2%) | 1%–4% | 0.93 |
| B_N6 | 250 | 15 | 0 (0%) | 0%–2% | 0.82 |
| A_orig | 250 | 15 | 19 (8%) | 5%–12% | 0.71 |
| A_sint | 250 | 15 | 19 (8%) | 5%–12% | 0.70 |
| A_sint_sim | 250 | 15 | 16 (6%) | 4%–10% | 0.69 |

## manifesto / recorte `seg_dev` (35 leituras distintas)

| Leitor | n | sem recorte | leitura exata | IC 95% | CER médio |
|---|---|---|---|---|---|
| B_Nverd | 97 | 2 | 0 (0%) | 0%–4% | 1.15 |
| B_proj | 97 | 2 | 0 (0%) | 0%–4% | 1.15 |
| B_N8 | 97 | 2 | 0 (0%) | 0%–4% | 1.67 |
| B_N6 | 97 | 2 | 0 (0%) | 0%–4% | 1.24 |
| A_orig | 97 | 2 | 0 (0%) | 0%–4% | 0.97 |
| A_sint | 97 | 2 | 0 (0%) | 0%–4% | 0.97 |
| A_sint_sim | 97 | 2 | 0 (0%) | 0%–4% | 0.97 |

## manifesto / recorte `seg_rect` (35 leituras distintas)

| Leitor | n | sem recorte | leitura exata | IC 95% | CER médio |
|---|---|---|---|---|---|
| B_Nverd | 97 | 20 | 0 (0%) | 0%–4% | 1.06 |
| B_proj | 97 | 20 | 0 (0%) | 0%–4% | 1.06 |
| B_N8 | 97 | 20 | 0 (0%) | 0%–4% | 1.28 |
| B_N6 | 97 | 20 | 0 (0%) | 0%–4% | 1.09 |
| A_orig | 97 | 20 | 0 (0%) | 0%–4% | 0.98 |
| A_sint | 97 | 20 | 0 (0%) | 0%–4% | 0.96 |
| A_sint_sim | 97 | 20 | 0 (0%) | 0%–4% | 0.95 |

## novas / recorte `manual`

| Leitor | n | sem recorte | leitura exata | IC 95% | CER médio |
|---|---|---|---|---|---|
| B_Nverd | 6 | 0 | 4 (67%) | 30%–90% | 0.07 |
| B_proj | 6 | 0 | 4 (67%) | 30%–90% | 0.07 |
| B_N8 | 6 | 0 | 0 (0%) | 0%–39% | 1.00 |
| B_N6 | 6 | 0 | 2 (33%) | 10%–70% | 0.40 |
| A_orig | 6 | 0 | 1 (17%) | 3%–56% | 0.24 |
| A_sint | 6 | 0 | 0 (0%) | 0%–39% | 0.26 |
| A_sint_sim | 6 | 0 | 2 (33%) | 10%–70% | 0.15 |

## novas / recorte `seg_dev`

| Leitor | n | sem recorte | leitura exata | IC 95% | CER médio |
|---|---|---|---|---|---|
| B_Nverd | 6 | 0 | 0 (0%) | 0%–39% | 0.91 |
| B_proj | 6 | 0 | 0 (0%) | 0%–39% | 0.91 |
| B_N8 | 6 | 0 | 0 (0%) | 0%–39% | 1.67 |
| B_N6 | 6 | 0 | 0 (0%) | 0%–39% | 1.21 |
| A_orig | 6 | 0 | 0 (0%) | 0%–39% | 1.00 |
| A_sint | 6 | 0 | 0 (0%) | 0%–39% | 1.00 |
| A_sint_sim | 6 | 0 | 0 (0%) | 0%–39% | 0.92 |

## novas / recorte `seg_rect`

| Leitor | n | sem recorte | leitura exata | IC 95% | CER médio |
|---|---|---|---|---|---|
| B_Nverd | 6 | 2 | 0 (0%) | 0%–39% | 0.94 |
| B_proj | 6 | 2 | 0 (0%) | 0%–39% | 0.94 |
| B_N8 | 6 | 2 | 0 (0%) | 0%–39% | 1.39 |
| B_N6 | 6 | 2 | 0 (0%) | 0%–39% | 1.00 |
| A_orig | 6 | 2 | 0 (0%) | 0%–39% | 1.00 |
| A_sint | 6 | 2 | 0 (0%) | 0%–39% | 0.94 |
| A_sint_sim | 6 | 2 | 0 (0%) | 0%–39% | 0.94 |

## IoU da máscara prevista pela segmentação de B contra a máscara de gabarito

| Conjunto | n | IoU mediano | IoU médio | fotos com IoU > 0,5 |
|---|---|---|---|---|
| kaggle_heldout_ambos | 205 | 0.31 | 0.30 | 45 (22%) |
| kaggle_heldout_A_viu_B | 43 | 0.40 | 0.38 | 16 (37%) |
| kaggle_treino_A | 250 | 0.35 | 0.33 | 70 (28%) |
