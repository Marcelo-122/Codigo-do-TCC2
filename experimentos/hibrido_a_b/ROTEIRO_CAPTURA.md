# Roteiro: capturar e rotular quadros 160x120 no modo de operação de B

Objetivo: montar o conjunto que falta para decidir se o leitor CTC de A (sobre a caixa da segmentação de
B) lê melhor que o fatiamento de B. As capturas de `test_images/` não servem para isso: são tomadas
amplas do mostrador, e B foi feito para a câmera colada na janela de dígitos (quadro de 160x120 quase
todo ocupado pelos dígitos, como em `test_images/debug_ocr_esp32cam/debug_frames/frame_33.jpg`).

## 1. Antes de começar (uma vez)

1. Se a câmera estiver montada de cabeça para baixo, acerte antes a orientação do quadro no calibrador
   (`Rede/calibrar_roi_esp32cam/`, tecla `r`). Ela fica gravada na placa e o `captura_quadros` a aplica ao
   ligar a câmera (imprime `[camera] orientacao: ...`), então os quadros já saem de pé.
2. Grave `captura_quadros/captura_quadros.ino` na ESP32-CAM: board "AI Thinker ESP32-CAM" (no core 3.0.7 a
   PSRAM já vem ligada). Não precisa da partição Huge APP nem de TensorFlow. Compila com o core 3.0.7.
3. Dependências do `capturar_quadros.py`: as de `requirements.txt` desta pasta (`opencv-python` com janelas,
   `numpy`, `pyserial` e `ai-edge-litert`, este só para mostrar a leitura na janela); o `.venv` desta pasta já tem
   tudo (`.venv/Scripts/python capturar_quadros.py ...`). O `teste_hibrido.py` continua no ambiente de
   `ModeloEDataset/requirements.txt` (Python 3.10). A porta serial sai de `TX_SERIAL_PORT` do `.env`, ou
   use `--porta COM5`. Ao abrir a porta, o script reinicia a placa (na ESP32-CAM-MB, abrir a porta sem esse
   reset deixava a placa em modo de gravação).
4. Feche o Monitor Serial do Arduino IDE (a porta só aceita um programa).

Por que não usar o `debug_ocr_esp32cam`: ele desenha o retângulo e as linhas-guia sobre o quadro e o manda
em JPEG qualidade 80. Cada imagem dele já vem alterada. Até 2026-11-18 ele também **lia os dígitos depois de
desenhar** as guias no mesmo buffer, então o classificador recebia as linhas brancas da borda e as cinzas entre as
fatias (efeito não medido); a ordem foi corrigida, mas as 61 capturas de `medicoes/` foram feitas com o erro.

## 2. Como capturar

```bash
python capturar_quadros.py --medidor tianjin_6 --luz dia
```

Para cada quadro: posicione o medidor, **digite a leitura que você vê nas rodas pretas** (zeros à
esquerda incluídos), e o script captura, grava `quadros_160x120/q_NNNN.png` (sem perdas) e acrescenta
uma linha ao `quadros_160x120.csv`. Comandos: `?` no lugar de uma roda parada entre dois números (a
foto fica fora da avaliação), `d` descarta o último quadro, `q` encerra, Enter em branco não faz nada.

Digitar a leitura ao vivo, olhando o medidor, evita rotular depois por foto borrada.

A janela que abre junto mostra o quadro ao vivo com a caixa da ROI (`--roi`, padrão `roi_fisico_1.json`) e a
leitura que o classificador faria. Se a caixa sair de cima dos dígitos, **a câmera se mexeu**: pare (`q`), recalibre
salvando com **outro nome** (`calibrar_roi_usb.py --nome roi_fisico_2`) e acrescente uma linha a
`posicoes_camera.csv` (`primeiro_quadro,roi,observacao`) com o primeiro quadro da posição nova. Recalibrar com o
mesmo nome sobrescreve a ROI das fotos anteriores (aconteceu em 2026-11-18; a ROI da posição A teve de ser
reconstruída em `roi_fisico_1_posicao_a.json`).

## 3. O que capturar (plano de amostragem)

| Item | Meta |
|---|---|
| Quadros utilizáveis (sem `?`) | **60, no mínimo 50** |
| Leituras distintas | **pelo menos 30** (não adianta repetir 046643 dez vezes) |
| Medidores diferentes | **2 ou mais**, com números de rodas diferentes (5, 6, 8) |
| Condições de luz | dia, noite e lâmpada: pelo menos 10 quadros em cada |
| Variação de posição | afastar/aproximar e deslocar a câmera um pouco entre quadros |
| Giro de cabeça para baixo | evite: a câmera tem orientação fixa |

Como trocar de leitura: com medidores físicos, gire a roda das unidades ou aguarde o consumo. Com a tela
do monitor, mostre cada imagem ampliada até a janela de dígitos encher o quadro (o jeito das capturas atuais
serve se você der zoom). As 35 leituras distintas já rotuladas em `fotos_para_rotular.csv` são um banco de
leituras para reproduzir na tela.

Mude `--medidor` e `--luz` ao trocar de situação (reinicie o script). As duas colunas ficam no manifesto
para a análise por medidor.

Por quê 50 a 60: um teste pareado (McNemar), supondo 40% de pares discordantes, detecta uma diferença de ~25
pontos com 80% de poder em cerca de 50 quadros. Para 20 pontos, ~75; para 15 pontos, ~140.

## 4. Rodar o teste

```bash
python teste_hibrido.py --manifesto quadros_160x120.csv
```

O recorte relevante é `seg_dev` (a caixa de B sobre o quadro 160x120, como no firmware); os leitores são
`B_Nverd` (B no melhor caso, com o número certo de rodas), `B_N6` (o `N_FATIAS` fixo do firmware),
`B_proj`, `A_orig`, `A_sint` e `A_sint_sim`. Os resultados saem em `resultados/resumo.md`.

## 5. Regra de decisão (fixada antes de rodar)

- O híbrido **segue** (reexportar o CTC sem `REDUCE_PROD` e testar na placa) se, no recorte `seg_dev`,
  `A_sint` fizer pelo menos **15 pontos** a mais que `B_Nverd` em leitura exata, com o limite inferior do IC
  de 95% da diferença acima de zero, e **não perder** em nenhum dos medidores.
- Se `A_sint` empatar ou perder, o híbrido é **descartado** e o texto registra "avaliado e descartado".
- Se a diferença for positiva mas menor que 15 pontos, vale mais dados antes de decidir.
- Comparar com `B_N6` só mostra o custo de errar o número de rodas, que é o motivo de ser do CTC: reporte,
  mas a decisão usa `B_Nverd`, que é B no melhor caso.
