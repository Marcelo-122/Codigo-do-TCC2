# dados/teste/: conjunto de teste de hidrômetro físico

Conjunto **fixo e versionado** para medir o pipeline completo (segmentação → fatias → dígitos) em fotos da ESP32-CAM
de um **hidrômetro físico**, e não de um monitor exibindo imagens de hidrômetro (o caso de todas as fotos que o
repositório tinha até agora; ver "Origem das imagens" no [README principal](../../README.md)).


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

## O que o conjunto não cobre

- Os rótulos são lidos por uma pessoa; conferir as fotos mais borradas por uma segunda pessoa antes de congelar o
  conjunto. Depois de congelado, **não editar** (versionar uma nova versão em vez disso).
- A "borda" da avaliação é uma emulação em Python do firmware, não a acurácia medida na placa (ver
  [`ocr/README.md`](../../ocr/README.md)).
