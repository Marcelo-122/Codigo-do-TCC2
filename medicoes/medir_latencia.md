# Latência ponta a ponta (disparo no nó → dado disponível no servidor)

Script: [`latencia_ponta_a_ponta.py`](latencia_ponta_a_ponta.py). Saída: `latencia_ponta_a_ponta.csv` (uma linha por leitura).

> **Status:** a lógica foi testada com chunks LoRaWAN sintéticos (marcos de tempo, duplicados,
> leitura incompleta, modo auto). A parte de serial/threads **não foi testada em hardware**.

## O que é medido
Um único relógio, o do PC, que lê as duas seriais ao mesmo tempo:
- **Nó** (`TX_SERIAL_PORT`): fornece o disparo e a linha `[camera] JPEG ...`.
- **Receptor** (`RX_SERIAL_PORT`): fornece cada chunk LoRaWAN.

Tempos em ms desde o disparo: `t_ate_foto_ms`, `t_ate_primeiro_chunk_ms`, `t_ate_ultimo_chunk_ms`,
`t_envio_ms` (último − primeiro chunk) e **`t_ate_disponivel_ms`**, que é a latência ponta a ponta:
a imagem remontada no PC.

Definições adotadas (confirme que batem com a issue):
- **"Servidor"** = o PC que remonta a imagem a partir do receptor Heltec (é o que existe hoje no
  repositório). Se o destino passar a ser o ChirpStack, o marco final muda para a chegada no MQTT.
- **Disparo** no modo `capture` = instante em que o PC escreve `CAPTURE`. No modo `auto` = primeira
  linha do `setup()` após o despertar (`[boot] causa=timer`), cerca de 0,3 a 0,5 s depois do
  despertar real, porque o boot da ROM não aparece na serial.
- A incerteza dos timestamps é de poucos ms, desprezível frente a dezenas de segundos de envio.

## Como rodar
Pré-requisitos: `.env` com `TX_SERIAL_PORT`, `RX_SERIAL_PORT`, `LORA_APP_SKEY` (e `LORA_DEV_ADDR`),
nó gravado com o `transmissor_esp32cam.ino`, receptor com `receptor_lora32.ino`.
Feche monitores seriais e `reconstrutor.py`: as portas não podem ser compartilhadas.

```bash
python medicoes/latencia_ponta_a_ponta.py capture --n 30
```
O PC manda `CAPTURE` 30 vezes. Com ~15 chunks e 7 s entre chunks, cada leitura leva cerca de 2 minutos,
então espere ~1 hora.

```bash
python medicoes/latencia_ponta_a_ponta.py auto --n 30
```
Para medir o ciclo com deep sleep: o nó em `AUTO:<s>` com um FTDI só com TX/RX/GND no PC (ver
[`teste_deep_sleep.md`](teste_deep_sleep.md)). O script só escuta.

O script imprime uma linha por leitura e, no fim, mínimo, mediana, p95 e máximo das leituras completas.

## O que é esperado
- `t_ate_foto_ms` baixo: captura e compressão levam dezenas de ms (a câmera já está iniciada no modo `capture`).
- `t_ate_primeiro_chunk_ms` pouco acima de `t_ate_foto_ms`, o tempo do primeiro pacote no ar (~136 ms) e do AT.
- `t_envio_ms` ≈ `(chunks − 1) × 7000 ms` mais o tempo de cada resposta AT. **O intervalo de 7 s entre
  chunks domina a latência** do fluxo de imagem.
- Leituras com chunks perdidos ficam com `completo=0` e fora das estatísticas. Como o `RESEND` é manual,
  a taxa de incompletas é um resultado em si e deve ser reportada junto da latência.

## Fluxo OCR na borda (`--fluxo ocr`)
Para o nó com [`Rede/transmissor_ocr_esp32cam`](../Rede/transmissor_ocr_esp32cam/transmissor_ocr_esp32cam.ino), que manda
a leitura inteira em **um** uplink na FPort 2 (sem chunks nem JPEG):

```bash
python medicoes/latencia_ponta_a_ponta.py capture --n 30 --fluxo ocr
python medicoes/latencia_ponta_a_ponta.py auto --n 30 --fluxo ocr
```

- No modo `capture` o PC manda `LER` (no lugar de `CAPTURE`). No modo `auto` o disparo é o mesmo de antes
  (`[boot] causa=timer` ou `[auto] ligado`), e o nó em `AUTO` só é escutado.
- A leitura está completa quando o uplink chega ao receptor e é decodificado: `t_ate_disponivel_ms` é a latência
  ponta a ponta do fluxo OCR. `t_ate_primeiro_chunk_ms` e `t_ate_ultimo_chunk_ms` são o instante desse uplink,
  `t_envio_ms` é 0, e `chunks_total`/`chunks_recebidos` são 1/1.
- Colunas novas no CSV (vazias nas linhas de imagem): `t_ate_ocr_ms` (disparo até a linha `[ocr] leitura=...` do nó:
  câmera, modelos, segmentação e dígitos), `leitura` e `achou_caixa`. A coluna `fluxo` guarda `imagem` ou `ocr`. Como as
  colunas mudaram, um `latencia_ponta_a_ponta.csv` antigo é renomeado com a data e um novo começa.
- O id vem de `[ocr] enviando leitura id N` no log do nó; uplinks de outro id são ignorados. Sem essa linha (nó
  em `auto` que o PC começou a ouvir no meio), o script adota o id do primeiro uplink.
- Chunks de imagem (FPort 1) numa medição `--fluxo ocr`, e uplinks de leitura (FPort 2) numa medição de imagem, são
  ignorados.
- **Status:** o firmware de OCR não foi compilado com a toolchain do ESP32 nem testado em placa, e esta extensão do script
  foi testada só com frames sintéticos. O `reconstrutor.py --tx --fluxo ocr` mede a mesma coisa e grava em
  `transmissao_ocr.csv` ([`medir_transmissao.md`](medir_transmissao.md)); os dois abrem as mesmas portas e não rodam juntos.

## Limitações
- Sem `--fluxo ocr`, só cobre o **fluxo de imagem**. O fluxo de OCR na borda tem firmware (ver acima), mas ainda sem
  medições em placa.
- `--salvar-imagens PASTA` grava cada imagem e esse tempo entra em `t_ate_disponivel_ms`; deixe desligado
  para medir só a remontagem.
- No modo `capture` o nó fica sempre ligado; o tempo de acordar do deep sleep só aparece no modo `auto`.
