# dados/teste/: conjunto de teste de hidrômetro físico

Conjunto **fixo e versionado** para medir o pipeline completo em fotos da ESP32-CAM de um **hidrômetro físico**, e não
de um monitor exibindo imagens de hidrômetro (ver "Origem das imagens" no [README principal](../../README.md)).

## O que tem (2026-11-18)

| Fotos | Origem | Rótulos | ROI |
|---|---|---|---|
| 30, `fisico_1_q_*.png` | bancada de 2026-11-18: medidor `fisico_1`, câmera fixa (posições A e B), 26 leituras de `000025` a `000052`, luz lateral difusa; quadros 160×120 crus, cópia de `experimentos/hibrido_a_b/quadros_160x120/` (sem os 3 com a roda entre dois números) | completos: `medidor`, `iluminacao`, `angulo` e `caixa` (a ROI calibrada) | calibrada uma vez por posição, em `roi_calibrada.csv` (caixa, `n`, face da roda, realce, JSON de origem) |
| 9, `esp32_*.jpg` | fotos avulsas de 27/10, medidores diferentes | só `leitura` e `n_digitos` | marcada à mão em `roi_manual.csv` |

As 12 fotos de medidores de gás (11, com marcações como "G6", "Pmax", "1 imp = 0,01 m³" e "Vn … dm³") e uma
indefinida (painel com kWh ou m³/h) que estavam aqui foram para `dados/teste_outros_medidores/`, com os rótulos e as
ROIs manuais, e uma coluna `tipo`. Elas não entram nas avaliações.

## Avaliações

| Script | Pipeline | Linhas em `medicoes/ocr_teste.csv` | Resultado (2026-11-18) |
|---|---|---|---|
| `python ocr/avaliar_roi_calibrada.py` | **adotado**: ROI calibrada uma vez, sem segmentação, com e sem votação | `fisico_roi_calibrada`, `fisico_roi_calibrada_votacao` | 25/30 leituras, 97,2 % dos dígitos, CER 0,028, na borda e na nuvem; o mesmo com votação |
| `python ocr/avaliar_pipeline.py --conjunto fisico` | segmentação do modelo (descartada) | `fisico` | 2/39 (borda), 0/39 (nuvem) |
| `python ocr/avaliar_roi_manual.py` | ROI marcada à mão, fatia inteira | `fisico_roi_manual*` | 4/39 (6/39 com votação) |

A "borda" é emulada em Python com as mesmas contas do firmware; a equivalência com a placa foi medida à parte nas 30
fotos da bancada (`experimentos/hibrido_a_b/resultados/PLACA_X_PC.md`: 33/33 leituras iguais).


## Como montar

1. **Fotografar** com a ESP32-CAM (`test_images/grab_image.py` salva as capturas) o medidor físico, com a câmera
   fixada como ficará na instalação. Variar de propósito: iluminação (luz do dia, luz artificial, pouca luz,
   reflexo no vidro), pequenas variações de ângulo e, se o medidor estiver em uso, o consumo ao longo dos dias
   (para cobrir dígitos diferentes; o conjunto de domínio atual não tem exemplos reais de 4, 5 e 6). Evitar fotos
   com a rodinha entre dois números, que não têm rótulo certo. Se houver mais de um medidor, 5 a 10 fotos de cada.
2. Copiar os JPEGs **sem editar** para `imagens/` e **nunca** reaproveitar para treino ou ajuste (nem para
   calibrar caixa de recorte do classificador): este conjunto só mede.
3. Preencher `rotulos.csv`, uma linha por foto (a leitura é a que se vê no medidor, com zeros à esquerda):

   | Coluna | Conteúdo |
   |---|---|
   | `arquivo` | nome do arquivo em `imagens/` |
   | `leitura` | dígitos das rodinhas, do jeito que aparecem (ex.: `046663`) |
   | `n_digitos` | número de rodinhas lidas (tem que ser o tamanho de `leitura`) |
   | `medidor` | identificador do medidor (ex.: `tianjin6`) |
   | `origem` | sempre `fisico` |
   | `iluminacao` | rótulo livre: `dia`, `lampada`, `penumbra`, `reflexo`, ... (opcional) |
   | `angulo` | rótulo livre: `reto`, `+5`, `-8`, ... (opcional) |
   | `centro_y` | só para foto maior que 4:3 paisagem (retrato): linha da janela dos dígitos; vazio nas demais |
   | `caixa` | janela dos dígitos `x0,y0,x1,y1` no **quadro 160×120**; opcional, mas sem ela a foto fica fora do Dice/IoU |
   | `observacao` | texto livre |

   Para ler a `caixa`: `python dados/gerar_grades.py` grava em `grades/` cada quadro 160×120 ampliado com uma
   grade de coordenadas (e o retângulo, se a `caixa` já estiver preenchida, para conferir).
4. Avaliar: `python ocr/avaliar_pipeline.py --conjunto fisico` grava as linhas `fisico` em
   [`medicoes/ocr_teste.csv`](../../medicoes/ocr_teste.csv) (leitura exata, acurácia por dígito, CER, Dice/IoU, borda e
   nuvem) e o detalhe por foto em `medicoes/ocr_teste_por_imagem_fisico.csv`.

## ROI marcada à mão (`roi_manual.csv`)

Para ler o conjunto sem o modelo de segmentação, como numa instalação com a câmera fixa, cada foto tem em
`roi_manual.csv` a inclinação da fileira (`angulo_graus`, aplicada ao quadro 160×120 por `pipeline_nuvem.alinhar`), a
janela dos dígitos no quadro já girado (`caixa`), a polaridade da janela (`fundo`: `claro` = dígitos escuros, `escuro` =
dígitos claros) e de onde veio o ângulo (`hough` ou `manual`). As marcações foram feitas pela geometria (bordas da
janela e centros dos roletes) antes de rodar a leitura, e ainda precisam ser conferidas por outra pessoa;
`conferencia_roi_manual.png` desenha cada caixa com as fatias e o dígito lido.

    python ocr/avaliar_roi_manual.py

grava as linhas `fisico_roi_manual*` em `medicoes/ocr_teste.csv` e o detalhe por foto em
`medicoes/ocr_teste_por_imagem_fisico_roi_manual.csv`. Em 2026-11-08, com as 21 fotos avulsas de então (12 delas
de gás, depois separadas), deu 2/21 leituras e 37 % dos dígitos (fluxo nuvem), e 3/21 e 56 % invertendo os tons das
fotos de fundo escuro. Com o conjunto atual (39 fotos de hidrômetro), 4/39 leituras e 76 % dos dígitos; a inversão
não muda nada, porque as fotos de fundo escuro eram as de gás. As 30 fotos da bancada entram aqui com a caixa da ROI
calibrada, ângulo 0 e fundo claro.

## O que o conjunto não cobre

- Os rótulos são lidos por uma pessoa; conferir as fotos mais borradas por uma segunda pessoa antes de congelar o
  conjunto. Depois de congelado, **não editar** (versionar uma nova versão em vez disso).
- A "borda" da avaliação é uma emulação em Python do firmware, não a acurácia medida na placa (ver
  [`ocr/README.md`](../../ocr/README.md)).
