# legado/

Primeira abordagem do enlace, **sem rádio real**: a ESP32-CAM manda os chunks por USB-serial, o PC
os remonta e, no caso do `mqtt_bridge.py`, injeta como uplinks num servidor ChirpStack. O ChirpStack
só serviu como simulador de teste e **saiu do trabalho**: o fluxo atual é Radioenge → rádio →
receptor LoRa32 → `reconstrutor.py` (veja o [README da raiz](../README.md), seção "Rede LoRaWAN").

Nada aqui é usado pelo fluxo atual. Fica no repositório como registro do protótipo e porque as
amostras (`raw_*.txt`) mostram o formato antigo. Os scripts foram ajustados só para continuarem
rodando a partir desta pasta (acham o `config.py` na raiz e os arquivos de dados ao lado deles).

| Arquivo | O que era |
|---|---|
| `esp32cam_jpeg_hex_chunks/` | Sketch: captura JPEG e manda `BEGIN,<bytes>,<chunks>` / `CHUNK,<i>,<len>,<hex>` / `END,<crc32>` pela serial (85 bytes por chunk) |
| `main.py` | Grava a saída serial desse sketch em `raw_image_data.txt` |
| `decode.py` | Remonta `image.jpg` a partir de `raw_data.txt` e confere o CRC32 (note: o `main.py` grava `raw_image_data.txt`, mas o `decode.py` lê `raw_data.txt`; renomeie para usar um capturado por você) |
| `mqtt_bridge.py` | Publica cada chunk como uplink no tópico MQTT do ChirpStack (precisa das variáveis `MQTT_*` e `CHIRPSTACK_*` do `.env` e do `paho-mqtt`) |
| `reconstrutor_antigo.py` | Cópia antiga do `reconstrutor.py` da raiz (formato de chunk anterior ao cabeçalho com id de leitura) |
| `raw_data.txt`, `raw_image_data.txt` | Capturas de exemplo (20.963 B, 247 blocos, CRC `70ADB229`, e uma segunda captura maior) |

O `mac_simulator.py` (simulador de gateway Semtech UDP) já havia sido removido antes.

Dependências deste diretório (`pip install -r legado/requirements.txt`): `pyserial` e `paho-mqtt`.
