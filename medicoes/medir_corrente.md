# Como medir a corrente do nó com o INA219

Mede o consumo do nó inteiro (ESP32-CAM + Radioenge) e calcula mAh por leitura e autonomia.
O INA219 vai **em série na alimentação** e uma segunda placa (o logger) lê o INA219 e manda os dados ao PC.

## Material
- Módulo INA219 (shunt R100 = 0,1 Ω) e uma segunda placa com I2C para o logger: um **Arduino Uno** (A4/A5, 100 amostras/s a 115200 baud). Um ESP32-S3 foi tentado no início e abandonado (suspeita de mau contato no breadboard); o [`ina219_logger.ino`](ina219_logger/ina219_logger.ino) ainda compila para ESP32 (500 amostras/s a 921600 baud), mas este guia usa o Uno.
- Na bancada, o 5 V vem do **USB da ESP32-CAM-MB** e passa pelo INA219 antes de chegar à ESP32-CAM; a mesma MB dá a serial do nó (sem FTDI). Para a autonomia de produção, a bateria que o nó usará de verdade; o critério de pronto pede o mesmo hardware e a mesma bateria nos dois fluxos.
- Fios curtos e, junto ao nó, um capacitor de 100–470 µF entre o lado Vin− (5 V depois do shunt) e GND (a ESP32-CAM sofre brownout nos picos de TX). Um de 100 µF / 50 V, ligado no Vin− e no GND do logger, foi usado.
- Com bateria no lugar do USB da MB: um adaptador USB-serial (FTDI) **só com TX, RX e GND** para ler o log do nó. Não ligue o 5 V dele.

## Montagem

Ligações do nó (pinout confirmado na bancada):

| De | Para |
|---|---|
| ESP32-CAM GPIO3, GPIO1, GPIO0 | mesmos pinos da ESP32-CAM-MB (serial e gravação) |
| ESP32-CAM GND (2 pinos) | GND da MB |
| ESP32-CAM 5V | **INA219 Vin−** (o fio de 5V da MB não vai mais direto) |
| 5V da MB | **INA219 Vin+** |
| Radioenge GND | GND da ESP32-CAM |
| Radioenge PB7 / PB6 | GPIO14 / GPIO15 da ESP32-CAM |
| Radioenge VCC | 3V3 da ESP32-CAM (fica depois do shunt) |

```
5V da MB ───────────► Vin+ ┐
                           │ INA219 (shunt 0,1 Ω)
 5V da ESP32-CAM ◄──── Vin- ┘      (ESP32-CAM e Radioenge alimentados a partir daqui)
GND da MB ───────────► GND do nó ──► GND do INA219 ──► GND do logger
(com bateria: Bateria (+) no lugar do 5V da MB e Bateria (−) no lugar do GND da MB)
```

Ligações do INA219 ao logger:

| INA219 | Arduino Uno |
|---|---|
| VCC | 5V (barra POWER, embaixo) |
| GND | GND (barra POWER) |
| SDA | A4 |
| SCL | A5 |

O INA219 aceita de 3 a 5,5 V, então o `VCC` no 5V do Uno é adequado. Use o lado macho dos jumpers nos furos fêmea do Uno.

Pontos que mais dão problema:
1. **Todo o 5 V do nó tem que passar pelo INA219.** O USB da MB pode ficar ligado (é a fonte e a serial), mas o fio de 5V da MB à ESP32-CAM tem que ser o do INA219, e nenhum outro caminho de 5V pode chegar à ESP32-CAM (nem ela encaixada nos headers da MB). Se o `bus_V` for 0 com o nó ligado, o nó está recebendo 5V por outro caminho.
2. **GND comum** entre MB, nó, INA219 e logger. O GND do logger tem que ir ao GND do nó, mesmo com os dois no mesmo PC.
3. O Radioenge precisa estar ligado depois do shunt para entrar na conta (aqui ele sai do 3V3 da ESP32-CAM). Para separar as parcelas, repita a medição com ele desconectado.
4. Vin+ e Vin- não são intercambiáveis: a corrente entra por Vin+.

## Preparação (uma vez)

1. Instale a biblioteca **Adafruit INA219** (e a Adafruit BusIO, que ela pede) no Arduino IDE e grave [`ina219_logger/ina219_logger.ino`](ina219_logger/ina219_logger.ino) no Uno: placa *Arduino Uno*, A4/A5, **115200 baud**, amostra a cada 10 ms. Abra o Serial Monitor a 115200 para conferir as linhas `t_us,shunt_mV,bus_V`, e feche-o antes de capturar (a porta só abre em um programa por vez).
   - O logger imprime `# INA219 nao encontrado: confira SDA/SCL/VCC/GND` uma vez e trava se não achar o módulo. Confira SDA em `A4`, SCL em `A5`, e meça ~5 V entre `VCC` e `GND` **do próprio módulo** (escala DCV 20 do multímetro). 0 V quer dizer que o fio de alimentação ou o de GND não chega.
2. **Offset:** com o nó desligado (Vin- sem carga), capture 10 s. A corrente que o script mostrar é o offset do INA219 (da ordem de 1 mA com 0,1 Ω). Use esse valor em `--offset-ma`. Na montagem com o Uno, o logger leu `shunt_mV = 0.00` e `bus_V = 0.000` sem o nó, ou seja, offset abaixo da resolução (0,1 mA): use `--offset-ma 0.0`.
3. **Conferência:** alimente um resistor de 100 Ω (≈ 50 mA a 5 V) pelo INA219 e compare com um multímetro em série. Se divergir mais de ~2%, o shunt do seu módulo não é 0,1 Ω: ajuste `R_SHUNT_OHM` em `corrente.py`.

   ```bash
   python corrente.py capturar COM5 corrente/offset.csv --baud 115200
   ```
   (Passe sempre `--baud 115200` com o Uno; o padrão do script é 921600. Ctrl+C depois de 10 s; o script mostra quantas amostras gravou.)
4. **Primeira leitura com o nó ligado:** com o logger rodando e o USB da MB plugado, `bus_V` deve ficar perto de 4,7 a 5 V e `shunt_mV` acima de zero. Com a ESP32-CAM e o Radioenge parados, mediu-se `shunt_mV ≈ 7,7` (≈ 77 mA) e `bus_V ≈ 4,90 V`.

Resolução: a leitura sai da tensão do shunt (passo de 10 µV), então 0,1 mA por passo. A incerteza real é de ~1 mA pelo offset e ~1% pelo shunt. Por isso a corrente de sleep medida com esse módulo é confiável só acima de uns 2 mA.

## Medições

Registre a **linha completa** de cada captura (nome do arquivo + comando), para saber depois como foi medido.

**A. Sleep.** Com o nó em `SLEEP:60` (deep sleep, ver [`teste_deep_sleep.md`](teste_deep_sleep.md)):

```bash
python corrente.py capturar COM5 corrente/sleep.csv --baud 115200     # deixe ~40 s e dê Ctrl+C
python corrente.py analisar corrente/sleep.csv --offset-ma 0.0
```
Vale a linha "Nivel de sleep". Para esta medição o script reclama que não há 2 ciclos; o nível de sleep aparece antes disso.
O subcomando `sleep` faz isso direto (usa o maior trecho de sono da captura e descarta 2 s em cada ponta):

```bash
python corrente.py sleep corrente/sleep.csv --offset-ma 0.0
```

**A2. Sleep com e sem o Radioenge** (separa o que é do módulo e o que é da placa). Faça as duas capturas em seguida, na mesma
bancada: primeiro `corrente/sleep_com_radioenge.csv` e depois `corrente/sleep_sem_radioenge.csv`, cada uma com o nó em
`SLEEP:60` e ~2 min de captura. Para a segunda, desligue o nó e desconecte do Radioenge o **VCC (3V3)** e os dois fios da
UART (GPIO14 e GPIO15), deixando só o GND: com a UART ligada e o módulo sem alimentação, a corrente pode entrar por
ele e falsear a medida. A diferença entre as duas é a corrente do Radioenge parado.

**B. Ciclos completos.** Comece o logger e depois mande `AUTO:60` ao nó (ou deixe `AUTO_AO_LIGAR 1` e `JANELA_STOP_MS = 0` para o consumo de produção). Capture pelo menos 3 ciclos para testar e **≥ 30 ciclos** para o critério de pronto. Copie do log do nó o `[CICLO_FIM]` de um ciclo para pegar `t_ate_ciclo_ms`, `t_captura_ms`, `t_envio_ms`:

```bash
python corrente.py analisar corrente/auto60.csv --offset-ma 0.0 \
    --init-s 0.41 --captura-s 0.03 --envio-s 101.8 \
    --bateria-mah 2000 --png corrente/auto60.png --min-sleep-s 5
```
(os tempos do exemplo são ilustrativos; os `--*-s` são os do `[CICLO_FIM]` divididos por 1000.)

Cuidados que apareceram na prática:
- **O `analisar` só funciona com o nó em `AUTO`.** Ele acha os ciclos pelos trechos de sleep e aborta com `Menos de 2 trechos de sleep` se o nó nunca dorme (modo `CAPTURE`, `reconstrutor.py --tx`). Por isso a corrente se mede com o nó em `AUTO` e a medição de PDR/latência com `--tx`, em corridas separadas.
- **N ciclos completos pedem N + 1 trechos de sleep** (um ciclo vai de um despertar ao seguinte): 30 ciclos de ~172 s (142,8 s acordado + 30 s de sleep) são ~90 min de captura. O primeiro ciclo, parcial, não conta.
- **Configuração do transmissor.** `Rede/transmissor_esp32cam/transmissor_esp32cam.ino` está hoje com `AUTO_AO_LIGAR 1`, `INTERVALO_PADRAO_S = 30` e `JANELA_STOP_MS = 0` (consumo de produção: o nó cicla sozinho ao receber energia e não aceita `STOP`; para parar, desplugue o USB da MB). Para o `reconstrutor.py --tx` e para o dia a dia, volte para `0`, `600` e `1500`. O `mAh por leitura` vale para o intervalo de sleep usado: para outro `T` em segundos, ≈ carga acordado + corrente de sleep × `T` / 3600.
- **Câmera desligada após a captura.** No modo `AUTO` o transmissor de imagem chama `desligarCamera()` (`esp_camera_deinit()` + PWDN) logo depois de gerar o JPEG, porque a câmera ligada durante os ~140 s de envio custava ~80 mA. Essa alteração **ainda não foi medida em placa**; a medição de referência abaixo é de antes dela.
- Dê um nome diferente a cada captura (`teste.csv`, `teste_cam_off.csv`, `auto30_30ciclos.csv`...): o `capturar` sobrescreve o arquivo, e um arquivo só com o cabeçalho (20 bytes) quer dizer que a captura não gravou nada.

Saída esperada: uma linha por ciclo com `periodo_s`, `ativo_s`, `mAh`, corrente média ativa e em sleep, pico e corrente média em cada estado (init+câmera, captura, envio), e no fim `mAh por leitura` com desvio, mais a autonomia para a bateria informada.

## Como interpretar

- **mAh por leitura** é o número do critério de pronto: a carga de um ciclo inteiro, do despertar ao próximo, incluindo o sleep.
- **Sleep:** deve ficar claramente abaixo da corrente do nó acordado e parado. Se ficar próxima, o chip não está entrando em deep sleep.
- **Envio (TX):** no fluxo de imagem domina o tempo ativo (`t_envio_ms` ≈ `(chunks − 1) × 7 s`). Picos curtos acima da média marcam cada pacote de ~136 ms.
- A autonomia do script é um limite superior: não considera eficiência do regulador, auto-descarga nem queda de capacidade da bateria com temperatura.
- A corrente de sleep medida **inclui o Radioenge**, que fica alimentado durante o deep sleep da ESP32-CAM. Para separar as parcelas, meça um `SLEEP:60` com o Radioenge desconectado.

## Medição de referência (teste curto, câmera ligada durante o envio)

Antes de desligar a câmera após a captura, um teste curto no modo `AUTO:30` (2026-10-27, Uno a 100 Hz, `corrente/teste_1.csv`, 1.024 s, tensão média 4,874 V, `JANELA_STOP_MS = 1500`) deu, com 4 ciclos completos:

```bash
python corrente.py analisar corrente/teste_1.csv --offset-ma 0.0 --init-s 2.699 --captura-s 0.01 --envio-s 139.7 --min-sleep-s 5
```

| Grandeza | Valor |
|---|---|
| `mAh por leitura` | **6,62** (desvio 0,005 mAh, n = 4; sleep de 30 s) |
| Período do ciclo | 172,1 s (≈ 142,7 s acordado + 30 s de sleep) |
| Corrente média acordado | ≈ 162 mA (base de ≈ 159 mA entre os chunks) |
| Corrente em sleep | ≈ 24,1 mA (p5 23,2 / p95 25,2), incluindo o Radioenge |
| Pico | ≈ 297 mA |
| Antes de iniciar a câmera | ≈ 77 mA (o degrau até ~159 mA aparece quando a câmera inicia) |

Leitura: o consumo é dominado pela espera de 7 s entre chunks com CPU e câmera ligadas (≈ 95% da carga do ciclo); os picos de TX somam ≈ 2%. Como são só 4 ciclos e o firmware mudou depois (câmera desligada), **isto é referência de "antes da otimização", não o resultado do critério de pronto** (≥ 30 ciclos). Guarde o `teste_1.csv` para comparar.

## O que enviar ("valor e como mediu")

Um exemplo do formato que serve:

> Sleep: 5,2 mA, medido com INA219 (shunt 0,1 Ω), 500 Hz, média de 30 s, offset de 0,4 mA descontado, nó = ESP32-CAM + Radioenge alimentados em 5 V pela bateria X.

E por fluxo: nº de ciclos, mAh por leitura (média e desvio) e o arquivo CSV.

## Fluxo de OCR na borda

O mesmo procedimento vale com o firmware [`Rede/transmissor_ocr_esp32cam`](../Rede/transmissor_ocr_esp32cam/transmissor_ocr_esp32cam.ino)
(OCR + envio só da leitura em um uplink na FPort 2), e dá para comparar os mAh por leitura dos dois fluxos. Ele **não foi
compilado com a toolchain do ESP32 nem testado em placa**: faça primeiro `LER` e `AUTO:30` por 3 ciclos, como
em [`teste_deep_sleep.md`](teste_deep_sleep.md), antes de gastar uma hora de captura.

Mesmo `AUTO`, mesmo deep sleep e mesma linha `[CICLO_FIM]`, mas com outros campos de tempo (os valores abaixo são
ilustrativos, não medidos):

```
[CICLO_FIM] ciclo=2 ok=1 chunks=1 falhas=0 leitura=046663 achou=1 t_ate_ciclo_ms=1210 t_captura_ms=10
            t_modelos_ms=... t_seg_ms=... t_digitos_ms=... t_envio_ms=... t_ativo_ms=... sleep_s=30
```

O `corrente.py` só conhece três estados (init+câmera, captura, envio); mapeie assim para o OCR:

| Opção do `analisar` | Valor (do `[CICLO_FIM]`, em segundos) |
|---|---|
| `--init-s` | `t_ate_ciclo_ms` (boot + câmera) |
| `--captura-s` | `t_captura_ms + t_modelos_ms + t_seg_ms + t_digitos_ms` (captura e processamento; a linha "captura" do resultado passa a ser esse bloco) |
| `--envio-s` | `t_envio_ms` (um uplink, ~1 s) |

A câmera é desligada logo depois da captura, antes da inferência, para não gastar a corrente dela durante os ~18 s de
processamento. O fluxo de imagem desliga a câmera no modo `AUTO` da mesma forma (alteração ainda não medida em placa).
Para ler o resultado no PC, use o `reconstrutor.py` ou o `latencia_ponta_a_ponta.py` com `--fluxo ocr`
([`medir_transmissao.md`](medir_transmissao.md), [`medir_latencia.md`](medir_latencia.md)).
