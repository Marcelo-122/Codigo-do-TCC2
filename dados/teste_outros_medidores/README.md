# dados/teste_outros_medidores/: fotos que não são de hidrômetro

12 fotos da ESP32-CAM que estavam em `dados/teste/` e foram separadas em 2026-11-18 porque não são de hidrômetro
(ver a issue do conjunto físico):

- **11 de medidores de gás** (tipo diafragma): têm marcações como "G6"/"G2,5", "Pmax", "1 imp = 0,01 m³",
  "Vn … dm³" (volume cíclico) e "Classe 1,5";
- **1 indefinida** (`esp32_24.jpg`): o painel traz kWh ou m³/h e "US-3,0"; não dá para confirmar que é hidrômetro.

`rotulos.csv` e `roi_manual.csv` têm as mesmas colunas de `dados/teste/`, com as linhas que eram dessas fotos; o
`rotulos.csv` ganhou a coluna `tipo` (`gás` ou `indefinido`) e o motivo da classificação em `observacao`. Nenhum
script de avaliação lê esta pasta. Os números antigos do conjunto físico com 21 fotos (por exemplo, 2/21 leituras
com a segmentação) misturavam estas fotos com as de hidrômetro.
