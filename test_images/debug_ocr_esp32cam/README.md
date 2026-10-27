# Ferramenta de debug/calibração física da câmera + leitura completa

Firmware + script Python **novos**, sem mexer em nada que já existia no
repositório. Objetivo original: ajudar a posicionar fisicamente a ESP32CAM
olhando pra onde o modelo de segmentação acha que está a janela de dígitos.
Agora também roda o **segundo modelo** (classificador de dígito) e monta a
leitura completa do hidrômetro (ex.: `"007704"`).

A cada 5 segundos a ESP32CAM:
1. Captura uma imagem (160×120, tons de cinza).
2. Roda o modelo de **segmentação** (`modelo.h`, TFLite Micro on-device)
   numa versão redimensionada pra 192×192 (entrada do modelo), achando o
   retângulo onde estão os dígitos.
3. Fatia esse retângulo em `N_FATIAS` pedaços de largura igual e roda o
   modelo **classificador de dígito** (`modelo_digito.h`) em cada fatia,
   montando a leitura completa. `N_FATIAS` é ajustado pro medidor-alvo
   real, **não** precisa bater com a convenção "5+3=8" usada pra montar o
   dataset de treino do classificador (ver `preparar_dataset_digitos.py`)
   — o classificador só sabe ler um dígito por vez, quem decide quantas
   fatias fazer é este firmware. Ajustado pra **6** depois de conferir na
   imagem de debug que o medidor de teste (Tianjin, leitura "046663") tem
   6 rodinhas pretas e nenhuma vermelha — se calibrar contra outro medidor,
   é só contar as rodinhas na imagem e atualizar essa constante.
4. Desenha o retângulo + linhas-guia na imagem, e manda tudo — imagem
   anotada + a leitura + métricas (RAM, PSRAM, tempos de cada etapa,
   temperatura etc.) — pela Serial USB, no mesmo estilo simples que
   `grab_image.py` já usa (marcadores de texto `<IMG_START>`/`<IMG_END>`).

**Onde ver a leitura:** ela aparece de duas formas — direto no Monitor
Serial (`Leitura: 007704`) e como uma coluna nova `leitura` em
`medicoes/debug_metricas.csv` na raiz do repositório (o `grab_image_debug.py`
já lê qualquer `chave=valor` da linha de métricas e monta o CSV
dinamicamente a partir das chaves que aparecerem).

Se a segmentação não achar nenhuma caixa naquele frame, a leitura vem como
`"--------"` (8 traços) — sinal claro de "não deu pra tentar", em vez de
inventar uma leitura sem base nenhuma.

## Como usar

1. **Arduino IDE**: instale uma biblioteca de TensorFlow Lite Micro pra
   ESP32 (`TensorFlowLite_ESP32` no Library Manager, ou o port mais novo
   `Chirale_TensorFlowLite`/`tflite-micro` da Espressif — qualquer uma que
   exponha os headers em `tensorflow/lite/micro/...`). Selecione a board
   **"AI Thinker ESP32-CAM"** com **PSRAM: Enabled**.
2. Abra `debug_ocr_esp32cam.ino` (nesta pasta) no Arduino IDE e grave na
   ESP32CAM, exatamente como você já faz com os outros `.ino` do projeto.
3. No PC, rode `grab_image_debug.py` (ajuste `PORTA_SERIAL` pro seu COM,
   igual você já faz no `grab_image.py` original).
4. Segure a ESP32CAM na posição desejada; a cada 5s um novo
   `debug_frame_latest.jpg` é escrito nesta pasta — abra num visualizador de
   imagens que atualize sozinho (ou dê refresh manual) e vá ajustando a
   posição até a janela de dígitos real do hidrômetro cair dentro do
   retângulo/linhas desenhados.
5. `../../medicoes/debug_metricas.csv` acumula uma linha por captura com todas as
   métricas — RAM livre, PSRAM livre, tempo de captura/inferência/encode,
   temperatura do chip, se achou a caixa ou não, coordenadas da caixa, etc.
6. Histórico completo de frames fica em `debug_frames/frame_N.jpg`, caso
   quiera revisar depois.

## Estado dos testes em hardware

**Testado em placa real** (AI-Thinker ESP32-CAM, 240 MHz, 4 MB de PSRAM): o
sketch compila, os dois modelos (segmentação + classificador de dígito)
rodam juntos e a leitura sai pela serial. A evidência está em
[`medicoes/debug_metricas.csv`](../../medicoes/debug_metricas.csv) (61
capturas de 2026-09-27, ver [`medicoes/README.md`](../../medicoes/README.md)):
`arena_digito_bytes` = 28.556 e `leitura=046663` repetida no medidor de teste.
Este firmware de debug **não** tem deep sleep nem foi medido em corrente. O consumo e o deep sleep do nó
foram testados em `Rede/transmissor_esp32cam` (30 ciclos do fluxo de imagem); o consumo e a latência ponta a ponta
do fluxo de OCR na borda seguem pendentes (ver [`medicoes/README.md`](../../medicoes/README.md)).

Os pontos abaixo são os que mais costumam precisar de ajuste **ao recompilar
com outra biblioteca/versão**:

- **Caminhos de `#include` do TFLite Micro** — variam entre as bibliotecas
  disponíveis (`TensorFlowLite_ESP32` vs `Chirale_TensorFlowLite` vs
  `tflite-micro` oficial). Se o compilador não achar
  `tensorflow/lite/micro/micro_interpreter.h` e afins, é o primeiro lugar
  pra olhar — pode ser só trocar o nome do header ou instalar outra
  biblioteca.
- **Tamanho do tensor arena** (`TENSOR_ARENA_SIZE = 2 MB`, alocado da
  PSRAM): a estimativa inicial de 1 MB ficou pequena na prática — testado
  em hardware real, `AllocateTensors()` precisou de ~1,55 MB. Ajustado pra
  2 MB com folga (ver "Histórico de ajustes" abaixo). Se ainda faltar
  memória, o log Serial no `setup()` avisa e é só aumentar de novo.
- **`fmt2jpg()`** (de `img_converters.h`, parte da biblioteca
  `esp32-camera` que os outros `.ino` do projeto já usam) — a assinatura
  usada aqui é a mais comum, mas confira contra a versão instalada se não
  compilar de primeira.
- **Tamanho do `DIGIT_ARENA_SIZE` (768 KB, classificador de dígito)** —
  foi extrapolado a partir do maior tensor intermediário medido em Python
  (~110 KB), e a medição em placa mostrou que está **superdimensionado**:
  `arena_digito_bytes` = 28.556 em todas as capturas. Dá para reduzi-lo e
  liberar PSRAM. Se `[tflite] digito: AllocateTensors falhou` aparecer, é só
  aumentar essa constante (o log já diferencia qual dos dois modelos
  falhou).
- **Operadores do resolver do classificador** (`AddConv2D/AddMaxPool2D/
  AddShape/AddStridedSlice/AddPack/AddReshape/AddFullyConnected/
  AddSoftmax`) — conferidos por introspecção do `modelo_digito.tflite`; com
  mais operadores que o de segmentação (8 em vez de 4), é o ponto mais
  provável de quebrar se a versão da biblioteca mudar.
- **Operadores do resolver** (`AddConv2D/AddMaxPool2D/AddTransposeConv/
  AddLogistic`) — conferidos por introspecção direta do
  `modelo_esp32.tflite` (script Python, ver
  `ModeloEDataset/` no branch `ocr`), então esses 4 deveriam bastar; se
  aparecer erro tipo "didn't find op", é sinal de que o modelo mudou desde
  a última vez que isso foi conferido.

## Histórico de ajustes

**Tentativa 1** (log real do usuário): câmera inicializava ("[camera] pronta"),
mas em seguida `[tflite] AllocateTensors falhou` com o driver da câmera
reportando `Failed to resize buffer. Requested: 1622016, available: 1046872,
missing: 575144` — ou seja, algo já tinha consumido a maior parte dos 4 MB de
PSRAM antes mesmo do tensor arena ser alocado. Causa mais provável: a chamada
`sensor->set_framesize()` logo após `esp_camera_init()` (copiada de
`transmissor_esp32cam.ino`, onde ela é necessária por causa do modo JPEG)
força o driver a manter o buffer antigo alocado enquanto tenta alocar um
novo — sem folga de PSRAM pros dois ao mesmo tempo. Corrigido:
- Removida essa chamada redundante (o `frame_size` já vai certo dentro do
  `config` passado pro `esp_camera_init`).
- `camera_config_t config = {};` (zerado explicitamente, em vez de deixar
  campos não usados com lixo da pilha) + `fb_location`/`grab_mode`
  explícitos.
- Resolução de captura reduzida de QVGA (320×240) pra QQVGA (160×120), com
  folga extra de PSRAM — o modelo redimensiona pra 192×192 de qualquer
  jeito, então a perda de detalhe não deveria importar pro objetivo de
  calibração visual.

**Tentativa 2** (log real, depois da correção acima): o log novo mostrou que
a hipótese da Tentativa 1 estava só parcialmente certa. A câmera agora só
consome **19.216 bytes** de PSRAM (`[psram] livre apos esp_camera_init:
4172908 (era 4192124 antes)`) — as mudanças da Tentativa 1 (remover o
resize redundante, zerar o config, reduzir pra QQVGA) claramente ajudaram e
valeu a pena mantê-las. Mas o mesmo erro `Failed to resize buffer.
Requested: 1622016, available: 1046872` continuou aparecendo, só que agora
sabemos que vem de **dentro do `AllocateTensors()` do TFLite Micro**, não
do driver da câmera — "available: 1046872" bate com o `TENSOR_ARENA_SIZE`
de 1 MB que eu tinha reservado (menos um pouco de overhead do
interpretador), e "Requested: 1622016" é o quanto o modelo realmente
precisa (~1,55 MB) — minha estimativa inicial (baseada só no maior tensor
intermediário isolado, ~288 KB) não levou em conta que o TFLite Micro
mantém vários tensores intermediários vivos ao mesmo tempo nessa
arquitetura tipo U-Net. Corrigido: `TENSOR_ARENA_SIZE` de 1 MB → 2 MB
(folga confortável acima dos ~1,55 MB medidos, dentro dos ~4,17 MB de
PSRAM livre depois da câmera).

Depois desta segunda correção, testado em hardware real e funcionou:
`arena_usado_bytes` reportado foi exatamente 1.623.852 — batendo com o
`Requested: 1622016` do erro anterior (a diferença de ~1.800 bytes é
overhead do próprio interpretador), confirmando que a estimativa de 2 MB
tinha folga suficiente.

**Tentativa 3** (segundo modelo, testado em hardware em 2026-09-27): com a
segmentação funcionando, adicionamos o classificador de dígito
(`modelo_digito.h`) como um segundo interpretador TFLite Micro
independente (`DIGIT_ARENA_SIZE = 768 KB`, própria alocação de PSRAM), que
roda uma vez por fatia da caixa detectada (8 fatias nas primeiras
capturas, 6 depois da calibração) e monta a leitura completa. Orçamento de
PSRAM medido: câmera (~19 KB) + arena de segmentação (2 MB) + arena de dígito
(768 KB) deixam `psram_free` = 1.289.292 bytes (~1,29 MB) em todas as
capturas. O classificador usou só 28.556 bytes de arena
(`arena_digito_bytes`) e levou ~2 s por frame com 6 fatias
(`t_digitos_ms`, mediana 1.995 ms).

## Depois de calibrar a posição

Esta ferramenta já faz a leitura completa (segmentação + classificação de
dígito), mas ainda não é o firmware final de produção — ela roda os dois
modelos em sequência a cada 5s só pra fins de debug/calibração, sem se
preocupar com robustez (ex.: não faz múltiplas leituras e vota a mais
provável, não trata glare/desfoque na captura, não persiste a leitura em
lugar nenhum além do CSV/Serial). Depois de confirmar que a posição física
da câmera está boa e a leitura sai consistente foto após foto, o próximo
passo (fora do escopo deste arquivo) é migrar essa mesma lógica pra um
firmware de produção — sem a parte de desenhar retângulo/linhas-guia (só
precisa disso pra debug visual), com tratamento de erro mais robusto, e
decidindo como/onde a leitura final deve ser entregue (LoRaWAN? MQTT?
outro meio já usado no projeto).
