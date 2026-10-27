"""
enlace.py
Parâmetros e funções compartilhados pelos scripts do enlace LoRa
(reconstrutor.py, decode_lorawan.py, orchestrator.py).

Os valores abaixo precisam bater com o firmware:
  - Rede/transmissor_esp32cam/transmissor_esp32cam.ino  (CHUNK_DATA_SIZE, cabeçalho)
  - Rede/transmissor_ocr_esp32cam/transmissor_ocr_esp32cam.ino  (payload da FPort 2: a leitura)
  - Rede/receptor_lora32/receptor_lora32.ino            (formato "HEX:<bytes>|RSSI:<n>")
Configuração de rádio: AU915, canal fixo 915,9 MHz, DR6 = SF8 / BW 500 kHz.

Requisitos: pip install pycryptodome
"""

from __future__ import annotations

import re
import struct

from Crypto.Cipher import AES

# --- Parâmetros do enlace ----------------------------------------------------
CHUNK_DATA_SIZE = 175            # bytes de imagem por chunk (= CHUNK_DATA_SIZE do .ino)
HEADER_FMT = ">HHH"              # uint16 id da leitura + uint16 índice (base 0) + uint16 total, big-endian
HEADER_SIZE = struct.calcsize(HEADER_FMT)   # 6 bytes
FPORT = 1                        # AT+SENDB=01:...

# Fluxo OCR na borda (Rede/transmissor_ocr_esp32cam): um uplink por leitura, na FPort 2.
# Payload: [id hi][id lo][flags][dígitos em ASCII...]; flags = bit 7 (caixa achada) | nº de dígitos.
FPORT_LEITURA = 2                # AT+SENDB=02:...
LEITURA_HEADER_FMT = ">HB"       # uint16 id da leitura + uint8 flags
LEITURA_HEADER_SIZE = struct.calcsize(LEITURA_HEADER_FMT)   # 3 bytes
_DIGITOS_LEITURA = set(b"0123456789?-")   # '?' = fatia não classificada, '-' = sem caixa

# Rádio (AU915, canal fixo, DR6). Só informativos para os scripts: quem fixa esses valores é
# o firmware (AT+CHMASK / AT+DR no Radioenge, receptor_lora32.ino) e o texto da issue.
SF = 8                           # spreading factor
BW_KHZ = 500                     # largura de banda
FREQ_MHZ = 915.9                 # canal 64 do AU915
INTERVALO_ENVIO_S = 7.0          # = SEND_INTERVAL_MS do .ino, em segundos

# Linha que o receptor imprime na serial: HEX:<frame LoRaWAN em hex>|RSSI:<dBm>
LINE_RE = re.compile(r"HEX:([0-9A-Fa-f]+)\|RSSI:(-?\d+)")

# MHDR(1) + DevAddr(4) + FCtrl(1) + FCnt(2) + MIC(4); FPort e payload vêm depois
_TAMANHO_MINIMO_FRAME = 12


def decrypt_frmpayload(frm: bytes, key: bytes, dev_addr_frame: bytes, fcnt: int,
                       direction: int = 0) -> bytes:
    """Descriptografa o FRMPayload (AES-128 CTR do LoRaWAN).

    `dev_addr_frame` é o DevAddr exatamente como vem no frame (little-endian):
    é assim que o bloco A_i da especificação o usa."""
    cipher = AES.new(key, AES.MODE_ECB)
    out = bytearray()
    for i in range(1, (len(frm) + 15) // 16 + 1):
        a_block = bytes([0x01, 0, 0, 0, 0, direction]) + dev_addr_frame \
            + fcnt.to_bytes(4, "little") + bytes([0x00, i])
        s_block = cipher.encrypt(a_block)
        bloco = frm[(i - 1) * 16: i * 16]
        out.extend(b ^ s for b, s in zip(bloco, s_block))
    return bytes(out)


def parse_uplink(raw: bytes, app_skey: bytes, dev_addr_esperado: bytes | None = None) -> dict:
    """Separa um uplink LoRaWAN e descriptografa o FRMPayload.

    `dev_addr_esperado` (big-endian, como em AT+DADDR=?): se informado e o frame vier de
    outro dispositivo, levanta ValueError (evita montar a imagem com lixo de outra rede).
    Levanta ValueError também se o frame for curto demais."""
    if len(raw) < _TAMANHO_MINIMO_FRAME + 1:
        raise ValueError(f"frame curto demais ({len(raw)} bytes)")

    dev_addr_frame = raw[1:5]                       # little-endian, como no frame
    dev_addr = dev_addr_frame[::-1]                 # big-endian, como no AT+DADDR=?
    if dev_addr_esperado is not None and dev_addr != dev_addr_esperado:
        raise ValueError(f"DevAddr {dev_addr.hex()} diferente do configurado "
                         f"({dev_addr_esperado.hex()})")

    fctrl = raw[5]
    fcnt = raw[6] | (raw[7] << 8)
    idx = 8 + (fctrl & 0x0F)                        # pula FOpts
    if idx + 1 > len(raw) - 4:
        raise ValueError("frame sem FPort/payload")

    fport = raw[idx]
    frm_cifrado = raw[idx + 1:-4]                   # exclui o MIC (4 bytes finais)
    payload = decrypt_frmpayload(frm_cifrado, app_skey, dev_addr_frame, fcnt)

    return {
        "dev_addr": dev_addr.hex().upper(),
        "fcnt": fcnt,
        "fport": fport,
        "mic": raw[-4:].hex().upper(),
        "payload": payload,
    }


def montar_payload(leitura_id: int, indice: int, total: int, dados: bytes) -> bytes:
    """Monta o payload de um chunk (o mesmo que o firmware envia)."""
    return struct.pack(HEADER_FMT, leitura_id, indice, total) + dados


def parse_chunk(payload: bytes) -> tuple[int, int, int, bytes]:
    """Lê o cabeçalho binário e devolve (id da leitura, índice base 0, total, dados).

    O id da leitura é sorteado a cada CAPTURE: chunks de fotos diferentes nunca se misturam.
    Levanta ValueError se o payload não parecer um chunk válido."""
    if len(payload) < HEADER_SIZE:
        raise ValueError(f"payload curto demais ({payload.hex()})")
    leitura_id, indice, total = struct.unpack(HEADER_FMT, payload[:HEADER_SIZE])
    dados = payload[HEADER_SIZE:]
    if total == 0 or indice >= total:
        raise ValueError(f"cabeçalho inválido (índice {indice}, total {total})")
    if len(dados) > CHUNK_DATA_SIZE:
        raise ValueError(f"chunk com {len(dados)} bytes de dados (máximo {CHUNK_DATA_SIZE})")
    return leitura_id, indice, total, dados


def montar_payload_leitura(leitura_id: int, achou_caixa: bool, digitos: str) -> bytes:
    """Monta o payload da FPort 2 (o mesmo que o transmissor_ocr_esp32cam envia)."""
    flags = (0x80 if achou_caixa else 0x00) | len(digitos)
    return struct.pack(LEITURA_HEADER_FMT, leitura_id, flags) + digitos.encode("ascii")


def parse_leitura(payload: bytes) -> tuple[int, bool, str]:
    """Lê o payload da FPort 2 e devolve (id da leitura, caixa achada, dígitos).

    Levanta ValueError (mensagem começando com "leitura inválida") se o payload não bater
    com o formato: tamanho = 3 + nº de dígitos e só '0'-'9', '?' e '-' nos dígitos."""
    if len(payload) < LEITURA_HEADER_SIZE + 1:
        raise ValueError(f"leitura inválida: payload curto ({payload.hex()})")
    leitura_id, flags = struct.unpack(LEITURA_HEADER_FMT, payload[:LEITURA_HEADER_SIZE])
    n = flags & 0x7F
    dados = payload[LEITURA_HEADER_SIZE:]
    if n == 0 or len(dados) != n:
        raise ValueError(f"leitura inválida: {len(dados)} byte(s) de dígitos, o cabeçalho diz {n}")
    if any(b not in _DIGITOS_LEITURA for b in dados):
        raise ValueError("leitura inválida: caractere fora de 0-9, '?' e '-'")
    return leitura_id, bool(flags & 0x80), dados.decode("ascii")
