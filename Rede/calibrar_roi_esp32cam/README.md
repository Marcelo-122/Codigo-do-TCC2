# calibrar_roi_esp32cam

Ferramenta de bancada para posicionar a ROI (caixa dos dígitos) do hidrômetro com a ESP32-CAM já montada.
O quadro aparece **ao vivo** no PC, no mesmo formato que o firmware de OCR captura (`PIXFORMAT_GRAYSCALE`,
`FRAMESIZE_QQVGA`, 160×120). Os pixels vão crus, sem JPEG, então a caixa desenhada vale direto para o
`lerDigitos()`. Por padrão tudo passa pelo **cabo USB**; a página web pelo Wi-Fi é opcional.

## Uso pelo cabo USB (padrão)

1. Arduino IDE: placa **AI Thinker ESP32-CAM** (no core 3.0.7 a PSRAM já vem ligada; não há opção no menu),
   **Erase All Flash Before Sketch Upload: Disabled**. Não precisa de biblioteca extra. Grave
   `calibrar_roi_esp32cam.ino` como está (`USAR_WIFI 0`).
2. Feche o Monitor Serial da IDE (a porta só abre em um programa) e rode, na raiz do repositório:
   ```bash
   experimentos/hibrido_a_b/.venv/Scripts/python Rede/calibrar_roi_esp32cam/calibrar_roi_usb.py --nome roi_fisico_1
   ```
   A porta vem de `TX_SERIAL_PORT` do `.env` (ou `--porta COM5`). O script precisa de `opencv-python` (a versão
   com janelas: a `opencv-python-headless` do `ocr/requirements.txt` dá "The function is not implemented" no
   `namedWindow`), `numpy` e `pyserial`; o `.venv` de `experimentos/hibrido_a_b` já tem os três. Para montar outro:
   `pip install opencv-python numpy pyserial`.
3. Na janela:
   - arraste para desenhar a caixa; arraste dentro dela para mover;
   - setas movem 1 px; `a`/`d` e `j`/`l` mexem nas bordas direita e esquerda, `w`/`s` e `i`/`k` nas de baixo e
     de cima; `+`/`-` mudam o número de dígitos (N);
   - as linhas amarelas são as fatias que o firmware recorta, e a tira de baixo mostra cada fatia em 28×28,
     como o modelo recebe;
   - **r** alterna a orientação do quadro (normal, girada 180°, invertida na vertical, espelhada); acerte isso
     **antes** de desenhar a caixa: os dígitos têm de aparecer de pé e na ordem certa, porque o classificador só
     lê dígitos de pé (ver "Orientação do quadro" abaixo);
   - **z**/**x** e **c**/**v** ajustam a face da roda e **e** liga o realce (ver "Face da roda e realce" abaixo); a
     tira de baixo mostra o que o classificador recebe e o dígito que ele lê em cada fatia;
   - **espaço** congela o quadro para ajustar com calma;
   - **g** grava a ROI, a face e o realce na NVS da placa e salva `<nome>.json` e `<nome>.png` em `experimentos/hibrido_a_b/`
     (mude com `--saida`); **q** sai.

Cada quadro leva ~1,7 s para chegar (19.200 bytes a 115200 baud).

## Uso pela página web (opcional, `USAR_WIFI 1`)

O PC precisa enxergar redes de **2,4 GHz** (a ESP32 não tem 5 GHz; uma placa Wi-Fi configurada como
`802.11a/n/ac` não vê a rede da placa).

1. Mude `#define USAR_WIFI 0` para `1` e grave.
2. Rede (escolha uma):
   - **Sem configurar nada**: a placa cria a rede `Hidrometro-ROI` (senha `hidrometro`, canal 6). Conecte o PC
     nela e abra <http://192.168.4.1>.
   - **Na sua rede**: crie `wifi_local.h` nesta pasta (já está no `.gitignore`):
     ```c
     #define WIFI_SSID  "minha-rede"
     #define WIFI_SENHA "minha-senha"
     ```
     Abra <http://hidrometro.local> ou o IP que aparece no monitor serial (115200). Se a placa não
     conectar em 15 s, ela cria a rede própria acima.
3. Na página: arraste no vídeo para desenhar a caixa (setas movem 1 px, Shift+setas mudam o tamanho), ajuste
   **dígitos** (N), use **Congelar** se precisar e clique em **Salvar no ESP32**, **Baixar JSON** e
   **Baixar foto (PNG)**.

Nos dois modos: gire o hidrômetro ou a câmera até os dígitos ficarem paralelos às bordas da caixa. O firmware
de OCR não corrige inclinação.

## Orientação do quadro

Com a câmera montada de cabeça para baixo (ou com um sensor que já sai espelhado), os dígitos chegam virados e o
classificador não os lê. A correção vai no próprio sensor (`set_vflip` e `set_hmirror`), então o quadro já sai
de pé para todo mundo. Ela é escolhida no calibrador (tecla `r`, ou pela serial `GIRAR v h`) e gravada na NVS.
O `captura_quadros`, os dois transmissores (`transmissor_ocr_esp32cam` e `transmissor_esp32cam`) e o
`debug_ocr_esp32cam` aplicam a mesma orientação ao ligar a câmera e imprimem
`[camera] orientacao: vflip=... hmirror=...`. Assim a ROI, desenhada em pixels, vale igual em todos eles. Sem
nada salvo, nenhum deles mexe na orientação.

Na bancada de 2026-11-17 (ESP32-CAM AI-Thinker com o hidrômetro físico), a orientação certa foi **invertida na
vertical** (`vflip=1`, `hmirror=0`). Girar 180° deixava os dígitos espelhados, porque este sensor já sai
espelhado na horizontal.

Ao trocar a orientação no calibrador, a caixa é levada para a posição correspondente, mas a ROI gravada antes
deixa de valer: confira e grave de novo com `g`.

## Onde a ROI fica

- **NVS**, namespace `roi`, chaves `x0`, `y0`, `x1`, `y1`, `n` (int) e `valida` (bool), mais a orientação em
  `vflip` e `hmirror` (bool; o `APAGAR` apaga só a ROI e mantém a orientação) e o pré-processamento em `fa`, `fb`
  e `realce` (int). Coordenadas no quadro
  160×120; `x1`/`y1` são exclusivos, como no `lerDigitos()`. A NVS sobrevive a reset, a deep sleep e a gravar
  outro sketch por cima (desde que *Erase All Flash Before Sketch Upload* esteja desligado; a NVS fica em
  `0x9000` em todos os esquemas de partição padrão, inclusive *Huge APP*).
- **JSON** baixado: `{"caixa": [x0, y0, x1, y1], "n_digitos": N, "quadro": [160, 120], "fatias": [...], ...}`,
  o mesmo campo `caixa` de `ModeloEDataset/calibracao_manual/*.json`.
- **Serial**: `ROI` imprime a salva, `APAGAR` apaga, `IP` mostra o endereço, `QUADRO` manda um quadro cru
  (`<FRAME_START>` + 19.200 bytes + `<FRAME_END>`), `SALVAR x0 y0 x1 y1 n [fa fb realce]` grava a ROI (sem os três últimos, mantém os atuais), `GIRO` imprime a
  orientação e `GIRAR v h` (0 ou 1 cada; `1 1` = 180°) muda e grava.
- **JSON** salvo pelo `calibrar_roi_usb.py`: o mesmo formato, mais `vflip`, `hmirror`, `face_pct`, `realce` e
  `leitura_no_pc` (o que o classificador leu no quadro salvo).

## Face da roda e realce (pré-processamento por medidor)

Cada fatia da caixa pega a roda **e** a barra escura entre as rodas (e os dois-pontos). O classificador foi
treinado com o dígito ocupando a fatia inteira, então essas bordas o confundem: no hidrômetro físico da bancada
(2026-11-17, leitura `000024`), sem pré-processamento ele leu `000000` em 7 de 7 quadros. Por isso o calibrador
grava também:

- **face** (`fa`, `fb`): a parte de cada fatia, em % da largura, em que fica o número. Só ela vai ao classificador.
  No `calibrar_roi_usb.py`, `z`/`x` mexem no início e `c`/`v` no fim (passos de 2 %), e as linhas azuis mostram a
  face de cada fatia;
- **realce** (`realce`): 1 = equalização de histograma da face antes de reduzir para 28×28 (tecla `e`).

A janela mostra o que o classificador recebe e o **dígito lido em cada fatia, ao vivo**: ajuste até a leitura
bater com o visor e grave com `g`. Na bancada, com `face 14-74 %` e realce, os 3 quadros tirados com a luz nova
leram `000024`; os 4 quadros com a luz anterior leram `000006` (sem pré-processamento, os 7 liam `000000`). É uma
amostra de **uma leitura só**: o ganho de acurácia ainda precisa ser medido em várias leituras (roteiro em
`experimentos/hibrido_a_b/ROTEIRO_CAPTURA.md`).

**Os valores não servem para outro medidor.** Nas 21 fotos de outros hidrômetros de `dados/teste/` (caixa marcada à
mão), a mesma face 14-74 % com realce piorou a leitura (de 36 % para 30 % dos dígitos; com os tons invertidos nas
fotos de fundo escuro, de 56 % para 41 %), e o realce piorou em todas as faces testadas. Face e realce são escolhidos
por medidor e por iluminação, olhando a leitura ao vivo; os padrões (fatia inteira, sem realce) mantêm o
comportamento anterior.

As contas são inteiras e iguais nos dois lados: `pipeline_nuvem.entrada_fatia()` (PC) e `lerDigitos()`/
`classificarFatia()` do `transmissor_ocr_esp32cam` (placa). As funções em C do firmware, compiladas no PC, deram
as mesmas entradas 28×28 que o Python, pixel a pixel, em 2.442 fatias (13 quadros, 43 configurações).

## Como o firmware de OCR usa a ROI

O `transmissor_ocr_esp32cam` lê da NVS a caixa, o `n`, a face e o realce ao ligar e imprime
`[roi] modo=roi caixa=... n=... face=...-... realce=...`. Com ROI salva, ele **não roda a segmentação** (nem carrega
o modelo dela): fatia a caixa em `n` partes, recorta a face de cada uma, aplica o realce e classifica. Sem ROI salva
(ou com valores inválidos), volta ao comportamento anterior (segmentação, `N_FATIAS` = 6, fatia inteira, sem realce)
e imprime `[roi] modo=seg`. A linha `[ocr] leitura=...` termina com `modo=roi` ou `modo=seg`. O comando `ROI` na
serial mostra o que foi carregado.

Num teste de bancada (2026-11-18), em modo ROI, a linha `[ocr] leitura=` apareceu 2,3 a 2,9 s depois do `LER`
(com a segmentação eram ≈ 18 s). É uma observação, não a medição formal: latência e energia sem a segmentação
ainda precisam ser medidas com os scripts de `medicoes/`.

Se a câmera ou o hidrômetro se mexerem, refaça a calibração: a ROI está em pixels do quadro 160×120 e não se ajusta
sozinha (na bancada, um deslocamento de ≈ 30 px depois da calibração deixou a caixa fora dos dígitos). O mesmo vale se
o firmware de OCR mudar de resolução ou formato de câmera.
