"""
analise_tempo_no_ar.py
Calcula número de pacotes, tempo no ar e tempo total de envio de uma imagem pelo enlace
LoRa (AU915, DR6 = SF8 / BW 500 kHz, canal fixo), a partir do tamanho do JPEG.

Uso:
    python analise_tempo_no_ar.py                    # tabela padrão (referência + amostras)
    python analise_tempo_no_ar.py --imagem 2574      # um tamanho específico (repetível)
    python analise_tempo_no_ar.py --sf 8 --bw 500 --bloco 100 --intervalo 7
    python analise_tempo_no_ar.py --verificar        # confere a fórmula com valores de referência

Fórmula: Semtech AN1200.13 (tempo no ar do LoRa), com cabeçalho explícito, CRC ligado,
CR 4/5 e preâmbulo de 8 símbolos (uplink LoRaWAN).
O tamanho do bloco padrão vem de enlace.py (mesmo valor do firmware).
"""

import argparse
import math

import enlace

# --- Tamanho de referência da imagem (JPEG cinza 160x120, qualidade 90) --------------
# Capturas reais da ESP32-CAM (Rede/transmissor_esp32cam, JPEG_QUALITY = 90),
# 4 capturas, todas recebidas completas: 2460, 3705, 4209, 4184 B
#   -> média 3640 B (o tamanho varia com a cena)
# PoC (poc_diminuicao_imagem/output.txt, q90, imagens 160x120): 3151, 3310 B
#   -> média 3231 B
# Média das duas médias: 3435 B; +25% de margem, arredondado: 4300 B
# (acima de toda amostra medida; a maior foi 4209 B).
# Com q80 (medido antes): reais 1940, 2574, 2578 B; PoC 2585, 2675 B.
CAPTURAS_REAIS = (2460, 3705, 4209, 4184)
POC_Q90 = (3151, 3310)
TAMANHO_REFERENCIA = 4300

# --- Camada LoRaWAN -----------------------------------------------------------------
# PHYPayload = MHDR(1) + DevAddr(4) + FCtrl(1) + FCnt(2) + FPort(1) + FRMPayload + MIC(4)
OVERHEAD_LORAWAN = 13
PREAMBULO = 8        # símbolos (uplink LoRaWAN)
CODING_RATE = 1      # 1 = 4/5
CRC_LIGADO = True    # uplink LoRaWAN leva CRC no payload
CABECALHO_EXPLICITO = True


def tempo_no_ar_ms(payload_phy: int, sf: int, bw_hz: float, preambulo: int = PREAMBULO) -> float:
    """Tempo no ar (ms) de um pacote LoRa com `payload_phy` bytes na camada física."""
    t_sym = (2 ** sf) / bw_hz
    de = 1 if t_sym > 0.016 else 0        # low data rate optimize
    num = (8 * payload_phy - 4 * sf + 28
           + (16 if CRC_LIGADO else 0)
           - (0 if CABECALHO_EXPLICITO else 20))
    n_payload = 8 + max(math.ceil(num / (4 * (sf - 2 * de))) * (CODING_RATE + 4), 0)
    return (preambulo + 4.25 + n_payload) * t_sym * 1000


def analisar(imagem_bytes: int, sf: int, bw_hz: float, bloco: int, intervalo_s: float) -> dict:
    """Pacotes, tempo no ar e tempo total para enviar `imagem_bytes`."""
    n = math.ceil(imagem_bytes / bloco)
    ultimo = imagem_bytes - (n - 1) * bloco
    frm = lambda dados: dados + enlace.HEADER_SIZE          # FRMPayload = cabeçalho + dados
    t_cheio = tempo_no_ar_ms(OVERHEAD_LORAWAN + frm(bloco), sf, bw_hz)
    t_ultimo = tempo_no_ar_ms(OVERHEAD_LORAWAN + frm(ultimo), sf, bw_hz)
    t_radio_s = ((n - 1) * t_cheio + t_ultimo) / 1000
    return {
        "imagem": imagem_bytes,
        "pacotes": n,
        "payload_cheio": frm(bloco),
        "ms_por_pacote": t_cheio,
        "radio_s": t_radio_s,
        "total_s": (n - 1) * intervalo_s + t_ultimo / 1000,   # com o intervalo entre envios
    }


def verificar() -> None:
    """Confere a fórmula com o valor de referência publicado em
    https://d-central.tech/lora-airtime-calculator/ (fórmula da Semtech AN1200.13):
    SF11, 250 kHz, CR 4/5, payload de 16 B, preâmbulo de 16, CRC ligado, cabeçalho
    explícito -> 23 símbolos de payload e 354,304 ms.
    Confere também a conta à mão do SF8 / 500 kHz usado no enlace."""
    obtido = tempo_no_ar_ms(16, sf=11, bw_hz=250e3, preambulo=16)
    ok = abs(obtido - 354.304) < 0.001
    print(f"SF11/250 kHz, 16 B, preâmbulo 16: {obtido:.3f} ms (esperado 354.304) -> {'OK' if ok else 'FALHOU'}")

    # SF8/500 kHz, FRMPayload de 104 B (4 de cabeçalho + 100 de dados) = 117 B de PHY:
    # Tsym = 0,512 ms; payload = 8 + ceil((8*117-32+28+16)/32)*5 = 8 + 30*5 = 158 símbolos;
    # tempo = (8 + 4,25 + 158) * 0,512 = 87,2 ms
    obtido = tempo_no_ar_ms(OVERHEAD_LORAWAN + 104, sf=8, bw_hz=500e3)
    ok2 = abs(obtido - 87.168) < 0.001
    print(f"SF8/500 kHz, 117 B de PHY: {obtido:.3f} ms (conta à mão 87.168) -> {'OK' if ok2 else 'FALHOU'}")
    if not (ok and ok2):
        raise SystemExit(1)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sf", type=int, default=8, help="spreading factor (padrão 8)")
    ap.add_argument("--bw", type=float, default=500, help="largura de banda em kHz (padrão 500)")
    ap.add_argument("--bloco", type=int, default=enlace.CHUNK_DATA_SIZE,
                    help=f"bytes de imagem por pacote (padrão {enlace.CHUNK_DATA_SIZE}, de enlace.py)")
    ap.add_argument("--intervalo", type=float, default=7.0,
                    help="intervalo entre pacotes em s (padrão 7, igual ao firmware)")
    ap.add_argument("--imagem", type=int, action="append",
                    help="tamanho do JPEG em bytes (repetível); sem isso, usa a referência e as amostras")
    ap.add_argument("--verificar", action="store_true", help="confere a fórmula e sai")
    a = ap.parse_args()

    if a.verificar:
        verificar()
        return

    bw_hz = a.bw * 1000
    if a.imagem:
        linhas = [("", s) for s in a.imagem]
    else:
        linhas = [("referência", TAMANHO_REFERENCIA)]
        linhas += [("captura real", s) for s in CAPTURAS_REAIS]
        linhas += [("PoC q90", s) for s in POC_Q90]

    print(f"SF{a.sf} / BW {a.bw:g} kHz, bloco de {a.bloco} B (+{enlace.HEADER_SIZE} B de cabeçalho, "
          f"+{OVERHEAD_LORAWAN} B LoRaWAN), intervalo {a.intervalo:g} s\n")
    print("| Imagem | JPEG (B) | Pacotes | Payload (B) | Tempo no ar/pacote (ms) "
          "| Tempo total de rádio (s) | Tempo total com intervalo (s) |")
    print("|---|---:|---:|---:|---:|---:|---:|")
    for nome, tamanho in linhas:
        r = analisar(tamanho, a.sf, bw_hz, a.bloco, a.intervalo)
        print(f"| {nome} | {r['imagem']} | {r['pacotes']} | {r['payload_cheio']} | "
              f"{r['ms_por_pacote']:.1f} | {r['radio_s']:.2f} | {r['total_s']:.0f} |")


if __name__ == "__main__":
    main()
