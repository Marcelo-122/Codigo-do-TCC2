"""Placa x PC nas mesmas imagens: manda os quadros capturados para a ESP32-CAM e compara a leitura com a do PC.

Cada quadro de `quadros_160x120.csv` vai pela serial para o `transmissor_ocr_esp32cam` (comando `LERQ`), com a ROI da
posição da câmera em que foi tirado (`posicoes_camera.csv`, como no `avaliar_roi_fixa_fisico.py`). A placa lê com o
mesmo `lerDigitos()` do OCR real (TFLite Micro, kernels do esp-nn) e devolve a leitura e as 10 saídas int8 de cada
fatia; o PC faz a mesma leitura com o `pipeline_nuvem.py` (ai-edge-litert, kernels de referência). O teste isola o
cálculo: mesmos pixels, mesma ROI, mesmo modelo; só muda onde a conta é feita. Não cobre a câmera ao vivo.

Pré-requisito: `transmissor_ocr_esp32cam` gravado na placa; feche monitores seriais. Nada é enviado pelo rádio.

Uso (na raiz do repositório):
    experimentos/hibrido_a_b/.venv/Scripts/python experimentos/hibrido_a_b/comparar_placa_pc.py
Saídas: resultados/PLACA_X_PC.md e resultados/placa_x_pc_por_foto.csv (nesta pasta).
"""
import argparse
import csv
import datetime
import re
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import serial

PASTA = Path(__file__).resolve().parent
RAIZ = PASTA.parents[1]
sys.path.insert(0, str(RAIZ / "ocr"))
sys.path.insert(0, str(PASTA))
import pipeline_nuvem as pn  # noqa: E402
from avaliar_roi_fixa_fisico import carregar_rois, roi_do_quadro  # noqa: E402

RE_SAIDAS = re.compile(rb"\[lerq\] saidas=([-\d,;]+)\r?\n\[lerq\] leitura=(\S+) t_digitos_ms=(\d+)")


def porta_padrao():
    sys.path.insert(0, str(RAIZ))
    import config  # config.py fica na raiz do repositório
    return config.require("TX_SERIAL_PORT")


def abrir(porta):
    ser = serial.Serial(porta, 115200, timeout=0.2)
    # Reset limpo na ESP32-CAM-MB (abrir a porta sem isso pode deixar a placa em modo de gravação)
    ser.dtr = False
    ser.rts = True
    time.sleep(0.2)
    ser.rts = False
    buf, fim = b"", time.time() + 10
    while time.time() < fim and b"Comandos:" not in buf:
        buf += ser.read(ser.in_waiting or 1)
    if b"Comandos:" not in buf:
        sys.exit("A placa não respondeu como o transmissor_ocr_esp32cam. Grave esse firmware e confira a porta.")
    time.sleep(2)   # deixa terminar o boot (câmera, ROI)
    ser.reset_input_buffer()
    return ser


def ler_na_placa(ser, quadro, caixa, n, face, realce):
    ser.reset_input_buffer()
    ser.write(f"LERQ {caixa[0]} {caixa[1]} {caixa[2]} {caixa[3]} {n} {face[0]} {face[1]} {realce}\n".encode())
    buf, fim = b"", time.time() + 10
    while b"[lerq] mande o quadro" not in buf and b"[lerq] erro" not in buf and time.time() < fim:
        buf += ser.read(ser.in_waiting or 1)
    if b"[lerq] mande o quadro" not in buf:
        raise IOError(f"a placa não pediu o quadro: {buf[-200:]!r}")
    ser.write(np.ascontiguousarray(quadro, np.uint8).tobytes())
    buf, fim = b"", time.time() + 30
    while time.time() < fim:
        buf += ser.read(ser.in_waiting or 1)
        m = RE_SAIDAS.search(buf)
        if m:
            saidas = [[int(v) for v in f.split(b",")] for f in m.group(1).split(b";")]
            return m.group(2).decode(), saidas, int(m.group(3))
        if b"[lerq] erro" in buf and buf.endswith(b"\n"):
            raise IOError(buf[buf.index(b"[lerq] erro"):].decode(errors="replace").strip())
    raise TimeoutError("a placa não devolveu a leitura")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--porta", help="porta da ESP32-CAM (padrão: TX_SERIAL_PORT do .env)")
    ap.add_argument("--manifesto", default=str(PASTA / "quadros_160x120.csv"))
    ap.add_argument("--roi", default=str(PASTA / "roi_fisico_1.json"))
    ap.add_argument("--posicoes", default=str(PASTA / "posicoes_camera.csv"))
    a = ap.parse_args()
    sys.stdout.reconfigure(errors="replace")

    rois = carregar_rois(a.manifesto, a.roi, a.posicoes)
    with open(a.manifesto, encoding="utf-8") as f:
        linhas = list(csv.DictReader(f))
    base = Path(a.manifesto).parent
    leitor = pn.LeitorB()
    ser = abrir(a.porta or porta_padrao())

    res = []
    for l in linhas:
        _, nome_roi, roi = roi_do_quadro(rois, l["arquivo"])
        caixa, n = tuple(roi["caixa"]), int(roi["n_digitos"])
        face, realce = tuple(roi.get("face_pct", (0, 100))), int(roi.get("realce", 0))
        quadro = cv2.imread(str(base / l["arquivo"]), cv2.IMREAD_GRAYSCALE)
        # PC: mesma conta do firmware (pipeline_nuvem.entrada_fatia), saídas int8 do classificador
        larg = caixa[2] - caixa[0]
        saidas_pc = [leitor.pontuacoes_fatia(quadro, caixa[0] + larg * i // n, caixa[1],
                                             caixa[0] + larg * (i + 1) // n, caixa[3], face, realce).astype(int).tolist()
                     for i in range(n)]
        lido_pc = "".join(str(int(np.argmax(s))) for s in saidas_pc)
        lido_placa, saidas_placa, t_ms = ler_na_placa(ser, quadro, caixa, n, face, realce)
        dif = int(np.abs(np.array(saidas_pc) - np.array(saidas_placa)).max())
        res.append({"arquivo": l["arquivo"], "rotulo": l["rotulo"], "roi": nome_roi, "lido_pc": lido_pc,
                    "lido_placa": lido_placa, "leitura_igual": int(lido_pc == lido_placa),
                    "saidas_iguais": int(dif == 0), "maior_dif_saida_int8": dif, "t_digitos_placa_ms": t_ms})
        print(f"{Path(l['arquivo']).name}  rótulo {l['rotulo']}  PC {lido_pc}  placa {lido_placa}  "
              f"{'iguais' if dif == 0 else f'saídas diferem até {dif}'}  ({t_ms} ms na placa)")
    ser.close()

    pasta_res = PASTA / "resultados"
    with open(pasta_res / "placa_x_pc_por_foto.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(res[0]))
        w.writeheader()
        w.writerows(res)
    rot = [r for r in res if "?" not in r["rotulo"]]
    ac_pc = sum(r["lido_pc"] == r["rotulo"] for r in rot)
    ac_placa = sum(r["lido_placa"] == r["rotulo"] for r in rot)
    tempos = [r["t_digitos_placa_ms"] for r in res]
    md = ["# Placa x PC nas mesmas imagens", "",
          f"Gerado por `comparar_placa_pc.py` em {datetime.date.today().isoformat()}. Os {len(res)} quadros de "
          f"`{Path(a.manifesto).name}` foram mandados pela serial ao `transmissor_ocr_esp32cam` (comando `LERQ`), cada "
          "um com a ROI da sua posição de câmera, e lidos pelo mesmo `lerDigitos()` do OCR na placa (TFLite Micro, "
          "esp-nn). O PC leu os mesmos quadros com o `pipeline_nuvem.py` (ai-edge-litert, kernels de referência).", "",
          "| | Resultado |", "|---|---|",
          f"| Leituras iguais na placa e no PC | {sum(r['leitura_igual'] for r in res)}/{len(res)} |",
          f"| Saídas int8 do classificador idênticas (todas as fatias) | {sum(r['saidas_iguais'] for r in res)}/{len(res)} "
          f"(maior diferença: {max(r['maior_dif_saida_int8'] for r in res)}) |",
          f"| Leituras exatas contra o rótulo ({len(rot)} quadros sem `?`) | placa {ac_placa}/{len(rot)}, "
          f"PC {ac_pc}/{len(rot)} |",
          f"| Tempo do classificador na placa ({n} fatias) | mediana {int(np.median(tempos))} ms "
          f"({min(tempos)} a {max(tempos)} ms) |", "",
          "Mede só o cálculo: não inclui a câmera, a exposição nem a variação entre quadros ao vivo. Detalhe por quadro "
          "em `placa_x_pc_por_foto.csv`."]
    (pasta_res / "PLACA_X_PC.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n" + "\n".join(md))


if __name__ == "__main__":
    main()
