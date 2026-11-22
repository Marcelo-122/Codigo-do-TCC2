# Teste híbrido: leitor CTC de A sobre os recortes de B

Pergunta: o leitor CRNN+CTC do Pipeline A (`TreinoEModelosOCRNaBorda/`) lê melhor que o fatiamento
em N partes + classificador de dígito do Pipeline B (`ModeloEDataset/`)? E, ligado à segmentação de B,
o conjunto funciona de ponta a ponta?

`teste_hibrido.py` roda tudo no PC com os `.tflite` INT8 (os mesmos que iriam para a placa). Os
resultados completos estão em `resultados/resumo.md` e `resultados/leituras.csv`.

## Como rodar

Python 3.10 com as versões de `ModeloEDataset/requirements.txt` (TensorFlow 2.16.1). Em Windows, crie o
venv em um caminho curto: o pip falha com caminhos longos.

```bash
python teste_hibrido.py                          # Kaggle + fotos de Imagens_2 e do domínio de B
python teste_hibrido.py --gerar-manifesto ../../../test_images fotos_para_rotular.csv
python teste_hibrido.py --manifesto fotos_para_rotular.csv
```

## ROI fixa no hidrômetro físico (2026-11-18)

Os quadros de `quadros_160x120/` (capturados com `capturar_quadros.py`, câmera parada diante do hidrômetro
`fisico_1`) também servem para medir o pipeline B no modo da instalação: ROI calibrada, sem segmentação.
`avaliar_roi_fixa_fisico.py` lê cada quadro com a ROI da posição da câmera (`posicoes_camera.csv`: a câmera se mexeu
uma vez e foi recalibrada, então há duas ROIs) e gera `resultados/ROI_FIXA_FISICO.md`:

| Pré-processamento (fluxo borda) | Leituras exatas (30 quadros) |
|---|---|
| sem pré-processamento | 2/30 (7 %) |
| **só a face da roda (configuração final, gravada na placa)** | **25/30 (83 %; IC 95 % 66–93 %)** |
| face + realce (como foi calibrado) | 24/30 (80 %; IC 95 % 63–90 %) |

O que decide é recortar a face da roda; o realce não acrescentou nada neste conjunto e foi desligado
(`realce 0` na placa e nos dois JSONs da ROI, que guardam o valor da calibração em `realce_na_calibracao`). Os erros estão todos na roda
das unidades: na configuração final (só a face), `7`, `4` e `1` lidos como `0` (5 quadros; com face + realce, também
`9` lido como `3`). Um medidor e uma luz: não mede a generalização para outro
hidrômetro.

```bash
.venv/Scripts/python avaliar_roi_fixa_fisico.py      # na raiz: experimentos/hibrido_a_b/.venv/Scripts/python experimentos/hibrido_a_b/avaliar_roi_fixa_fisico.py
```

**Na placa, com as mesmas imagens.** `comparar_placa_pc.py` manda cada quadro pela serial ao
`transmissor_ocr_esp32cam` (comando `LERQ x0 y0 x1 y1 n fa fb realce`, com a ROI da posição do quadro), que lê com o
mesmo `lerDigitos()` do OCR real, e compara com o PC (`resultados/PLACA_X_PC.md`). Em 2026-11-18, com a
configuração final (só a face): **33/33 leituras iguais** e 25/30 certas nos dois; as saídas int8 do classificador
diferiram até 18 (kernels esp-nn na placa × kernels otimizados do LiteRT no PC), sem mudar nenhum dígito. Nenhum
dos dois lados usa os kernels de referência: no ai-edge-litert 2.3.0, desligar o XNNPACK
(`BUILTIN_WITHOUT_DEFAULT_DELEGATES`, como no `pipeline_nuvem.py`) dá as mesmas leituras que o `BUILTIN` com XNNPACK.
Em 2026-11-20, o `avaliar_roi_fixa_fisico.py` rodado com os kernels de referência (`BUILTIN_REF`) mudou 4 das 264
leituras, todas nas variantes descartadas ("só o realce" e "sem pré-processamento"); a configuração final e o
"face + realce" ficaram iguais. Com o realce ligado, a
mesma comparação tinha dado 33/33 iguais e 24/30 certas. O classificador levou 1,92 s
para as 6 fatias na placa. Os quadros foram capturados pela câmera do nó e rotulados olhando o visor; a placa leu
cada um com a mesma função usada nas leituras da câmera.

## Resultados (execução de 25/10/2026)

Leitura exata = número igual ao gabarito, ignorando zeros à esquerda. Entre parênteses, o IC de 95%.

**Leitor isolado**, recorte perfeito (máscara de gabarito), 205 fotos do Kaggle fora do treino do CTC
de A e fora das 195 fotos aceitas por B:

| Leitor | Leitura exata |
|---|---|
| A, CTC com sintéticos | 68% (62–74) |
| A, CTC original | 63% (57–70) |
| B, fatiamento em 8 partes iguais | 23% (18–29) |
| B, fatiamento em 6 partes iguais | 0% (0–2) |

**Fotos novas com recorte feito à mão** (6 fotos, intervalo de confiança muito largo):
B com o N correto 4/6, A 0–2/6, B com N errado 0–2/6.

**Ponta a ponta com a segmentação de B** (`seg_rect` e `seg_dev`): todos os leitores ficam entre 0% e
9%. A máscara de B tem IoU mediano de 0,31 contra o gabarito, mesmo no Kaggle que ela viu no treino.

**Fotos novas rotuladas** (`manifesto`: 97 fotos utilizáveis, 35 leituras distintas, as capturas de
`test_images/` rotuladas à mão; as demais ficaram com `?` por roda em trânsito ou foram descartadas):
**0 acertos de 97 em todos os leitores**, com recorte automático de B (`seg_dev` e `seg_rect`). Esse
resultado não compara os leitores: essas capturas são tomadas amplas do mostrador inteiro, e o firmware
de B foi feito para a câmera colada na janela de dígitos (o quadro de 160x120 do firmware, em
`test_images/debug_ocr_esp32cam/debug_frames/frame_33.jpg`, é quase só a janela). Num quadro desse tipo
o harness reproduz o firmware: a caixa de B sai justa (23x110) e, com a leitura real 046663, B_Nverd,
B_proj, A_sint e A_sint_sim acertam e A_orig e B_N8 erram (um único quadro, não vale como estatística).

Para comparar de verdade os leitores falta um conjunto de quadros de 160x120 no modo de operação de B,
rotulados.

## Cuidados ao ler

- O Kaggle é do mesmo domínio em que A treinou (medidores russos). Fora dele (`novas`, n = 6), A não
  ganha de B.
- B usa fatiamento igual, como no firmware. A acurácia por dígito do classificador de B nesses recortes
  é de 65% (posicional, 8 dígitos), muito abaixo dos 96,9% da validação dele. O recorte da máscara tem
  margens e as rodas não ficam em partes iguais.
- Os gabaritos do Kaggle vêm do nome do arquivo, e a fração perde zeros à direita (`273_47` é 273,470).
  Os scripts de A (`zfill(7)`) e de B (`zfill(3)` na fração) tratam isso de forma diferente: ~10% das
  fotos do Kaggle (128 de 1244) têm fração com menos de 3 dígitos. Aqui o gabarito é completado à
  direita.
- A divisão de validação de A foi reproduzida (seed 42, 80/20 por rótulo). Conferência: o CTC original
  dá 32,5% de acerto exato, no estilo de A, nos recortes dessa divisão; A registrou 37,9%.
- O pré-processamento do `simulador_extracao_dual.py` de A (preenche com o fundo, normaliza) difere do
  usado no treino (preenche com zero). No Kaggle a diferença é pequena (±3 pontos).
