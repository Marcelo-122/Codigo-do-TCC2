# Teste do deep sleep do nó (`Rede/transmissor_esp32cam`)

> O firmware **não foi compilado nem testado em placa** quando este roteiro foi escrito.
> O item "Deep sleep implementado" só vale depois do passo 4 abaixo. Se não compilar,
> cole o erro do Arduino IDE e eu corrijo.

## O que foi implementado

Três comandos novos pela serial (115200). Os antigos (`CAPTURE`, `RESEND`, `SEND`, `SENDALL`, `AT...`)
continuam como estavam, e o modo padrão no power-on continua sendo o interativo.

| Comando | Efeito |
|---|---|
| `SLEEP:<s>` | Deep sleep único de `<s>` segundos, sem captura. Serve para medir a corrente de sleep. |
| `AUTO[:<s>]` | Modo autônomo: captura, envia todos os chunks, entra em deep sleep por `<s>` s (padrão 600, mínimo 10) e repete ao acordar. |
| `STOP` | Sai do modo autônomo. Só é lido numa janela de 1,5 s (`JANELA_STOP_MS`) logo após cada despertar. |

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
  não foi liberado: me mande o log.
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
  próxima da acordada, o chip não está entrando em deep sleep: me mande o log serial.
- Não espere microampères: o chip sozinho consome da ordem de µA, mas a placa AI-Thinker tem regulador
  e outros componentes que costumam deixar a corrente da placa em alguns mA. Esse valor medido é exatamente o que a H3 precisa.
- O Radioenge continua alimentado e entra na conta. Meça com ele ligado e desligado (ou só o ESP32)
  para separar as parcelas.

## O que me enviar

Cole, de um `AUTO:30` com pelo menos 3 ciclos:
1. As linhas `[boot]` e `[CICLO_FIM]` de cada ciclo.
2. Se o item 2 ou o 3 falhar, o log completo do ciclo que falhou.
3. Corrente em sleep e acordado (valor e como mediu).

Com isso eu atualizo o `medicoes/README.md` e marcamos o item como feito, ou ajusto o firmware.

## Limitações conhecidas

- A cada ciclo, o período real é `t_ativo + sleep_s` (o sleep não compensa o tempo acordado).
- Entre chunks o nó fica em `delay(7000)` com a CPU ligada. Um light sleep ali reduziria o consumo do fluxo de imagem.
- A janela de 1,5 s para o `STOP` entra no tempo ativo de cada ciclo. Para medir consumo de produção,
  ponha `JANELA_STOP_MS = 0` (e use `AUTO_AO_LIGAR 1`).
- O fluxo "OCR na borda" (só a leitura trafega) ainda não existe no firmware do nó. Este deep sleep cobre só o fluxo de imagem.
