# Teste do deep sleep do nó (`Rede/transmissor_esp32cam`)

> O firmware **não foi compilado nem testado em placa** quando este roteiro foi escrito.
> Depois disso, o `transmissor_esp32cam` foi gravado e rodou um `AUTO:30` de 3 ciclos (2026-10-27): deep sleep
> confirmado pelo log (`DEEPSLEEP_RESET`, `causa=timer`, `ciclo` incrementando) e pela corrente (~159 mA acordado,
> ~24 mA dormindo, medidos com INA219). O passo 4 (`STOP`) e a medição de ≥ 30 ciclos seguem pendentes. O
> `transmissor_ocr_esp32cam` ainda não foi testado em placa.

## O que foi implementado

Três comandos novos pela serial (115200). Os antigos (`CAPTURE`, `RESEND`, `SEND`, `SENDALL`, `AT...`)
continuam como estavam, e o modo padrão no power-on continua sendo o interativo.

| Comando | Efeito |
|---|---|
| `SLEEP:<s>` | Deep sleep único de `<s>` segundos, sem captura. Serve para medir a corrente de sleep. |
| `AUTO[:<s>]` | Modo autônomo: captura, envia todos os chunks, entra em deep sleep por `<s>` s (padrão 30, `INTERVALO_PADRAO_S`; mínimo 10) e repete ao acordar. |
| `STOP` | Sai do modo autônomo. Só é lido durante `JANELA_STOP_MS` logo após cada despertar. No código atual a janela é 0, o que desliga o `STOP`; para este roteiro, ponha `1500`. |

Antes de dormir o firmware chama `esp_camera_deinit()`, coloca a câmera em power-down (GPIO32 em
nível alto) e apaga o flash (GPIO4), segurando os dois com `rtc_gpio_hold`. O contador de ciclos e o
modo autônomo ficam em memória RTC, que sobrevive ao deep sleep mas não a um power-on reset.
Para o modo autônomo já ligar no power-on, use `#define AUTO_AO_LIGAR 1`.

Cada ciclo termina com uma linha parseável, por exemplo:

```
[CICLO_FIM] ciclo=2 ok=1 chunks=15 falhas=0 jpeg_bytes=2640 t_ate_ciclo_ms=412 t_captura_ms=31 t_envio_ms=101800 t_ativo_ms=102300 sleep_s=60
```

## Roteiro

Material: ESP32-CAM com o Radioenge ligado como hoje, monitor serial (Arduino IDE ou
`python -m serial.tools.miniterm <COM> 115200`) e, se possível, o receptor com
`reconstrutor.py` aberto.

**1. Regressão (sem sleep).** Grave o sketch e reinicie.
- Esperado: `[boot] causa=power-on/reset ciclo=0 auto=0` e `[camera] pronta.`
- Envie `CAPTURE`. Esperado: a imagem chega ao receptor como antes.

**2. Sleep puro.** Envie `SLEEP:20`.
- Esperado: `[sleep] deep sleep por 20 s`, depois silêncio por ~20 s e então um novo boot com
  `[boot] causa=timer ciclo=0 auto=0`. O banner aparece mais rápido que no power-on, porque o
  `delay(1000)` só roda no power-on.
- Esperado: `[camera] pronta.` após acordar. Se aparecer `[camera] erro: 0x...`, o hold do GPIO32
  não foi liberado.
- O LED do flash deve ficar apagado durante o sleep.

**3. Ciclo autônomo curto.** Envie `AUTO:30`.
- Esperado: um envio completo da imagem, a linha `[CICLO_FIM] ... sleep_s=30`, 30 s de silêncio e
  um novo boot com `causa=timer ciclo=1 auto=1`, seguido de `[auto] ciclo 2 em 1500 ms; envie STOP para sair`.
- Esperado: `ciclo` incrementa a cada despertar (1, 2, 3...), o que prova que a memória RTC persiste.
- Esperado: `ok=1 falhas=0` e `chunks` igual ao do `CAPTURE` manual para o mesmo cenário.
- Esperado no receptor: uma imagem por ciclo. O id da leitura muda a cada ciclo, então as imagens não se misturam.
- Tempo: `t_envio_ms` ≈ `(chunks − 1) × 7000 ms` mais o tempo de resposta de cada comando AT.
  Com ~15 chunks são ~100 s, e **esse envio domina o tempo acordado** (a captura leva dezenas de ms).
  Isso é consequência dos 7 s entre chunks, não do sleep.

**4. Parar.** Quando aparecer `[auto] ciclo N em 1500 ms`, digite `STOP` e Enter.
- Esperado: `[auto] modo autônomo desligado` e o nó fica em modo interativo, sem dormir.
- A janela é curta de propósito. Se não conseguir digitar a tempo, aumente `JANELA_STOP_MS` para 5000 só para este teste,
  ou desligue e religue a alimentação (zera o modo, pois a memória RTC não sobrevive ao power-on).

**5. Corrente (Prova de que dorme de verdade).** Com amperímetro ou INA219 em série na alimentação de 5 V:
- Meça o ESP32-CAM acordado e parado, depois dentro do `SLEEP:60`.
- Esperado: queda **clara** (de dezenas de mA para poucos mA). Se a corrente dormindo ficar
  próxima da acordada, o chip não está entrando em deep sleep.
- Não espere microampères: o chip sozinho consome da ordem de µA, mas a placa AI-Thinker tem regulador
  e outros componentes que costumam deixar a corrente da placa em alguns mA. Esse valor medido é exatamente o que a H3 precisa.
- O Radioenge continua alimentado e entra na conta. Meça com ele ligado e desligado (ou só o ESP32)
  para separar as parcelas.

## Limitações conhecidas

- A cada ciclo, o período real é `t_ativo + sleep_s` (o sleep não compensa o tempo acordado).
- Entre chunks o nó fica em `delay(7000)` com a CPU ligada. Um light sleep ali reduziria o consumo do fluxo de imagem.
- A janela do `STOP` (`JANELA_STOP_MS`) entra no tempo ativo de cada ciclo. O código atual já está com `0`, o valor
  para medir o consumo de produção (com `AUTO_AO_LIGAR 1`, o nó também cicla sozinho no power-on).
- Este roteiro cobre o fluxo de imagem (`transmissor_esp32cam`). O fluxo "OCR na borda" (só a leitura trafega) tem firmware próprio,
  [`Rede/transmissor_ocr_esp32cam`](../Rede/transmissor_ocr_esp32cam/transmissor_ocr_esp32cam.ino), com o mesmo deep sleep
  (`AUTO`/`STOP`/`SLEEP`, memória RTC, hold de PWDN/flash) e o comando `LER` no lugar de `CAPTURE`. Os mesmos passos valem
  para ele (troque `CAPTURE` por `LER`; o `[CICLO_FIM]` traz `leitura=` e os tempos da inferência), mas ele **não foi
  compilado com a toolchain do ESP32 nem testado em placa**.
