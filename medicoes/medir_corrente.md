# Como medir a corrente do nó com o INA219

Mede o consumo do nó inteiro (ESP32-CAM + Radioenge) e calcula mAh por leitura e autonomia.
O INA219 vai **em série na alimentação** e uma segunda placa (o logger) lê o INA219 e manda os dados ao PC.

## Material
- Módulo INA219 (shunt R100 = 0,1 Ω) e uma segunda placa com I2C para o logger (um ESP32 DevKit serve; Arduino Uno também, com baud menor).
- A bateria (ou fonte) que o nó usará de verdade. O critério de pronto pede o mesmo hardware e a mesma bateria nos dois fluxos.
- Fios curtos e, junto ao nó, um capacitor de 100–470 µF entre alimentação e GND (a ESP32-CAM sofre brownout nos picos de TX).
- Um adaptador USB-serial (FTDI) **só com TX, RX e GND** para ler o log do nó. Não ligue o 5 V dele.

## Montagem

```
Bateria/Fonte (+) ──► Vin+ ┐
                           │ INA219 (shunt 0,1 Ω)
 5V do nó  ◄───────── Vin- ┘      (ESP32-CAM e Radioenge alimentados a partir daqui)
Bateria/Fonte (−) ───────────────► GND do nó ──► GND do INA219 ──► GND do logger

Logger 3V3 → INA219 VCC      Logger GPIO21 → SDA      Logger GPIO22 → SCL
```

Pontos que mais dão problema:
1. **Nada de USB alimentando o nó durante a medição.** Se o 5 V do USB também alimentar a ESP32-CAM, a corrente passa por fora do shunt e a medida fica errada.
2. **GND comum** entre fonte, nó, INA219 e logger.
3. O Radioenge precisa estar ligado depois do shunt para entrar na conta. Para separar as parcelas, repita a medição com ele desconectado.
4. Vin+ e Vin- não são intercambiáveis: a corrente entra por Vin+.

## Preparação (uma vez)

1. Instale a biblioteca **Adafruit INA219** no Arduino IDE e grave [`ina219_logger/ina219_logger.ino`](ina219_logger/ina219_logger.ino) no logger.
2. **Offset:** com o nó desligado (Vin- sem carga), capture 10 s. A corrente que o script mostrar é o offset do INA219 (da ordem de 1 mA com 0,1 Ω). Use esse valor em `--offset-ma`.
3. **Conferência:** alimente um resistor de 100 Ω (≈ 50 mA a 5 V) pelo INA219 e compare com um multímetro em série. Se divergir mais de ~2%, o shunt do seu módulo não é 0,1 Ω: ajuste `R_SHUNT_OHM` em `corrente.py`.

   ```bash
   python corrente.py capturar COM5 corrente/offset.csv
   ```
   (Ctrl+C depois de 10 s; o script mostra quantas amostras gravou.)

Resolução: a leitura sai da tensão do shunt (passo de 10 µV), então 0,1 mA por passo. A incerteza real é de ~1 mA pelo offset e ~1% pelo shunt. Por isso a corrente de sleep medida com esse módulo é confiável só acima de uns 2 mA.

## Medições

Registre a **linha completa** de cada captura (nome do arquivo + comando), para saber depois como foi medido.

**A. Sleep.** Com o nó em `SLEEP:60` (deep sleep, ver [`teste_deep_sleep.md`](teste_deep_sleep.md)):

```bash
python corrente.py capturar COM5 corrente/sleep.csv     # deixe ~40 s e dê Ctrl+C
python corrente.py analisar corrente/sleep.csv --offset-ma 0.4
```
Vale a linha "Nivel de sleep". Para esta medição o script reclama que não há 2 ciclos; o nível de sleep aparece antes disso.

**B. Ciclos completos.** Comece o logger e depois mande `AUTO:60` ao nó (ou deixe `AUTO_AO_LIGAR 1` e `JANELA_STOP_MS = 0` para o consumo de produção). Capture pelo menos 3 ciclos para testar e **≥ 30 ciclos** para o critério de pronto. Copie do log do nó o `[CICLO_FIM]` de um ciclo para pegar `t_ate_ciclo_ms`, `t_captura_ms`, `t_envio_ms`:

```bash
python corrente.py analisar corrente/auto60.csv --offset-ma 0.4 \
    --init-s 0.41 --captura-s 0.03 --envio-s 101.8 \
    --bateria-mah 2000 --png corrente/auto60.png
```
(os tempos do exemplo são ilustrativos; os `--*-s` são os do `[CICLO_FIM]` divididos por 1000.)

Saída esperada: uma linha por ciclo com `periodo_s`, `ativo_s`, `mAh`, corrente média ativa e em sleep, pico e corrente média em cada estado (init+câmera, captura, envio), e no fim `mAh por leitura` com desvio, mais a autonomia para a bateria informada.

## Como interpretar

- **mAh por leitura** é o número do critério de pronto: a carga de um ciclo inteiro, do despertar ao próximo, incluindo o sleep.
- **Sleep:** deve ficar claramente abaixo da corrente do nó acordado e parado. Se ficar próxima, o chip não está entrando em deep sleep.
- **Envio (TX):** no fluxo de imagem domina o tempo ativo (`t_envio_ms` ≈ `(chunks − 1) × 7 s`). Picos curtos acima da média marcam cada pacote de ~136 ms.
- A autonomia do script é um limite superior: não considera eficiência do regulador, auto-descarga nem queda de capacidade da bateria com temperatura.

## O que enviar ("valor e como mediu")

Um exemplo do formato que serve:

> Sleep: 5,2 mA, medido com INA219 (shunt 0,1 Ω), 500 Hz, média de 30 s, offset de 0,4 mA descontado, nó = ESP32-CAM + Radioenge alimentados em 5 V pela bateria X.

E por fluxo: nº de ciclos, mAh por leitura (média e desvio) e o arquivo CSV.

## Fluxo de OCR na borda

O mesmo procedimento vale, mas o firmware do nó com OCR + envio só da leitura ainda não existe. Quando existir, meça igual e compare os mAh por leitura dos dois fluxos.
