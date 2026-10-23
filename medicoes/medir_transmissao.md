# Medição do enlace LoRa (PDR, tempo de rádio, latência)

Scripts: [`reconstrutor.py`](../reconstrutor.py) (medição principal) e [`orchestrator.py`](../orchestrator.py),
os dois usando [`registro.py`](../registro.py). Saída: `transmissao.csv` (uma linha por leitura, acumulada
entre execuções), `logs/<execução>/` e `imagens/`.

> **Status:** a lógica (contagem de perdas, duplicatas, FCnt, PDR, latência, timeouts, reconexão da
> serial, formato dos arquivos) foi testada com nó e receptor **simulados** (59 verificações, sem
> hardware). **Nada disso foi rodado ainda com as placas.** Antes de valer como dado do TCC, faça
> uma execução curta (`--envios 1`) e confira a linha do CSV contra o que o nó imprimiu.

## Como rodar

Feche o Monitor Serial da IDE e qualquer outro programa que use as portas (uma porta serial só abre
em um programa). `.env` com `TX_SERIAL_PORT`, `RX_SERIAL_PORT`, `LORA_APP_SKEY` e `LORA_DEV_ADDR`.

```bash
# Medição da issue: o PC dispara CAPTURE, lê nó e receptor e repete 30 vezes a 50 m
python reconstrutor.py --tx --envios 30 --distancia 50 --rotulo "pátio, antena 2 dBi"

# Só escutando (CAPTURE enviado por outro terminal); latência menos precisa, ver abaixo
python reconstrutor.py --distancia 50
```

Fixe a distância, anote o ambiente no `--rotulo` e rode uma execução por distância. Com o intervalo de
7 s entre chunks e ~25 chunks, cada envio leva cerca de 3 minutos (`python analise_tempo_no_ar.py`).
Trinta envios dão **cerca de 1h30 por distância**.

`--tx` espera cada leitura terminar (imagem completa, ou o nó informar que acabou de enviar, mais 3 s
de folga), aguarda `--pausa-s` (10 s) e dispara a seguinte. Sem `RESEND`: uma leitura com blocos
perdidos fica registrada como `incompleta`, e isso é parte do resultado (PDR da leitura).
A política de perda (reenvio automático com limite) é um passo separado da issue.

## O que cada execução grava

`medicoes/logs/<AAAAMMDD_HHMMSS>[_rotulo]/`

| Arquivo | Conteúdo |
|---|---|
| `meta.json` | Quando e onde rodou: comando, host, versões de Python e pyserial, commit do git (e se havia alterações), parâmetros do enlace, portas, contadores finais, motivo do fim |
| `eventos.jsonl` | Um JSON por evento: `run_inicio`, `disparo`, `capture_enviado`, `foto`, `imagem_completa`, `leitura_encerrada` (com a linha inteira do CSV), `tx_ocupado`/`tx_falhou`/`tx_concluido`, `falha_camera`, `serial_erro`/`serial_reaberta`, `rodada`/`send` (orquestrador), `run_fim` |
| `chunks.csv` | **Todo frame recebido**, aceito ou não: instante, status, leitura, índice, total, RSSI, FCnt, diferença de FCnt, frames perdidos antes dele, FPort, tamanho |
| `serial_rx.txt` | Todas as linhas do receptor, com instante (DevAddr mascarado) |
| `serial_tx.txt` | Todas as linhas do nó, com instante (só com `--tx` e no orquestrador) |

Status em `chunks.csv`: `novo`, `duplicado`, `duplicado_divergente` (mesmo índice, bytes diferentes),
`total_divergente`, `ignorado` (frame de outro dispositivo, curto demais, cabeçalho inválido...),
`outra_leitura` (atraso de outra foto, com `--tx`), `pos_encerramento` (chunk de leitura já fechada).

`medicoes/imagens/<execução>_L<id>.jpg` é a imagem completa; `..._parcial.jpg` tem zeros nos blocos que
faltam. O SHA-256 da completa vai no CSV.

## Colunas de `transmissao.csv`

| Coluna | Significado |
|---|---|
| `run_id`, `leitura_id` | Execução e id da foto (o mesmo do cabeçalho dos chunks e do log do nó) |
| `distancia_m`, `rotulo`, `modo` | `--distancia`, `--rotulo`; `modo` = `tx_controlado`, `so_receptor` ou `orquestrador` |
| `status` | `completa`, `completa_jpeg_invalido` (todos os blocos, mas sem marcadores FFD8/FFD9), `incompleta`, `sem_dados` |
| `motivo_fim` | `completa`, `tx_concluido`, `nova_leitura`, `timeout_inatividade`, `timeout_leitura`, `sem_foto` (nó não respondeu ao CAPTURE), `falha_captura`, `interrompido`, `erro_serial`, `fim_da_execucao` |
| `inicio`, `fim` | Instantes ISO 8601 com fuso |
| `sf`, `bw_khz`, `chunk_bytes`, `intervalo_envio_s` | Parâmetros do enlace gravados com a linha |
| `jpeg_bytes`, `jpeg_valido` | Tamanho do JPEG (pelo nó, se incompleta) e conferência dos marcadores |
| `total_blocos`, `blocos_unicos`, `blocos_faltando` | Blocos da imagem, recebidos sem repetição, e índices que faltam (separados por `;`) |
| `frames_validos`, `duplicados`, `duplicados_divergentes`, `total_divergente`, `tamanho_anomalo` | Contadores de qualidade dos frames desta leitura |
| `blocos_enviados`, `blocos_enviados_base` | Frames que o nó mandou ao ar. Base `tx`: tentativas menos "ocupado" no log do nó (exato). Base `fcnt`: frames distintos recebidos mais as lacunas de FCnt (**não** vê perdas antes do primeiro nem depois do último frame recebido) |
| `pdr_leitura` | `blocos_unicos / total_blocos`: quanto da imagem chegou |
| `pdr_enlace` | Frames distintos recebidos / `blocos_enviados`: taxa de entrega por transmissão |
| `fcnt_perdidos`, `fcnt_repetidos`, `fcnt_reinicios` | Lacunas, repetições e saltos (> 1000) do contador de frames do nó |
| `rssi_min_dbm`, `rssi_medio_dbm`, `rssi_max_dbm` | RSSI dos frames válidos (medido pelo receptor) |
| `tempo_radio_s`, `tempo_radio_base` | Soma do **tempo no ar calculado** (Semtech AN1200.13, `analise_tempo_no_ar.py`) dos frames enviados (`tx`) ou recebidos (`rx`). Não é medido no ar |
| `t_foto_s`, `t_primeiro_chunk_s` | Do disparo até a linha `[camera] JPEG` e até o primeiro chunk (só com disparo) |
| `t_envio_s` | Primeiro chunk → último chunk inédito |
| `latencia_s`, `latencia_base` | Imagem completa menos o disparo (`disparo`: instante em que o PC escreveu `CAPTURE`/primeiro `SEND`) ou, sem controle do nó, menos o primeiro chunk (`primeiro_chunk`, subestima: falta captura e compressão). Vazia se incompleta |
| `tx_tentativas`, `tx_ocupado`, `tx_falhas`, `tx_ok_reportado` | Contagens do log do nó (`[chunk ... tent N]`, `[aviso] ... ocupado`, `[ERRO] ... falhou`, `[envio] concluido: N ok`) |
| `imagem_arquivo`, `imagem_sha256` | Caminho relativo a `medicoes/` e hash |

## Limitações e cuidados

- **Um único relógio**: o do PC. O erro dos instantes é o intervalo de consulta da serial (alguns ms) mais o
  atraso da USB, desprezível diante de dezenas de segundos de envio. O nó não tem relógio sincronizado.
- **Disparo**: instante em que o PC escreve o comando, não o instante em que o nó o recebe.
- **Perdas invisíveis no modo `fcnt`**: um frame perdido logo no início ou no fim da leitura não deixa lacuna.
  Use `--tx` para o PDR do enlace exato. O contador de FCnt também conta uplinks que o nó mande fora da imagem.
- **Tempo de rádio é calculado**, não medido (precisaria de analisador de espectro ou do tempo no ar
  reportado pelo módulo).
- **Frames de outras redes** no mesmo canal aparecem como `ignorado` e não entram no PDR.
- **Segredos**: o `registro.py` não grava `LORA_DEV_ADDR` nem `LORA_APP_SKEY`; os frames do receptor vão para
  `serial_rx.txt` com o DevAddr mascarado (`XXXXXXXX`). Por isso os logs podem ser versionados.
- **Queda de USB** durante a medição: o script tenta reabrir a porta por ~20 s e registra `serial_erro` /
  `serial_reaberta`; os frames desse intervalo viram lacuna de FCnt. Passando disso, encerra com `erro_serial` e
  grava o que tem.
- **DTR/RTS**: as portas são abertas com DTR/RTS desligados para **não resetar** o nó nem o receptor (o
  `orchestrator.py` antigo resetava e esperava 3 s). Se alguma placa só funcionar depois de resetar, aperte o botão.
- **Relação com `latencia_ponta_a_ponta.py`**: aquele script (issue de métricas e energia) mede a latência dos
  dois fluxos com a mesma definição de disparo, em `latencia_ponta_a_ponta.csv`. Os dois abrem as mesmas portas:
  **não rodem ao mesmo tempo**. Para o enlace, `transmissao.csv` tem tudo o que a issue pede (PDR, tempo de rádio e
  latência); os números de latência dos dois devem bater.
- O que **não** está aqui: política de perda (`RESEND` automático com limite) e envio real de ≥ 30 leituras.
