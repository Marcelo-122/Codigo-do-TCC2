"""Uso de CPU, frequência e pico de memória do nó por ciclo, nos dois fluxos.

Lê da serial da ESP32-CAM a linha [CPU_FIM] que os transmissores imprimem quando compilados com
MEDIR_CPU=1 (ver Rede/transmissor_ocr_esp32cam/medir_cpu.h), junto com a [CICLO_FIM] do mesmo ciclo,
e grava um CSV com uma linha por ciclo. Reinicia a placa (pulso no RTS), espera o banner e manda
AUTO:<s>, como o latencia_ponta_a_ponta.py --iniciar-auto.

O 1º ciclo vem do comando AUTO, não de um despertar (não tem o boot do deep sleep): fica no CSV com
despertou=0 e fora do resumo. Por isso o padrão é ler n + 1 ciclos.

Uso (na raiz do repositório, com o .venv da raiz):
    python medicoes/medir_cpu.py ocr --n 30          (firmware transmissor_ocr_esp32cam, MEDIR_CPU=1)
    python medicoes/medir_cpu.py imagem --n 30       (firmware transmissor_esp32cam, MEDIR_CPU=1)
    python medicoes/medir_cpu.py ocr --resumir medicoes/cpu/cpu_ocr.csv

Ao terminar, o nó continua no modo autônomo (só se para desligando a MB ou regravando).
Saídas: medicoes/cpu/cpu_<fluxo>.csv e o log bruto medicoes/cpu/cpu_<fluxo>.log.
"""
import argparse
import csv
import os
import re
import statistics as st
import sys
import time
from datetime import datetime

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(AQUI, ".."))  # config.py fica na raiz

RE_PAR = re.compile(r"(\w+)=(\S+)")
RE_FASE = re.compile(r"(\w+)=(-?[\d.]+)/(-?[\d.]+)/(\d+)")
NUMERICOS_CPU = ["f_cpu_mhz", "f_apb_mhz", "f_xtal_mhz", "pm", "taxa0", "taxa1", "t_ms", "uso0", "uso1",
                 "ocupado0_ms", "ocupado1_ms", "psram_total", "psram_pico", "interna_total", "interna_pico"]


def ler_cpu_fim(linha):
    cabeca, _, fases = linha.partition("fases:")
    d = {k: v for k, v in RE_PAR.findall(cabeca)}
    for nome, u0, u1, ms in RE_FASE.findall(fases):
        d[f"{nome}_uso0"], d[f"{nome}_uso1"], d[f"{nome}_ms"] = u0, u1, ms
    return d


def abrir(porta):
    import serial
    ser = serial.Serial()
    ser.port, ser.baudrate, ser.timeout = porta, 115200, 0.2
    ser.dtr = False  # sem isso a ESP32-CAM-MB pode ficar em modo de gravação
    ser.rts = False
    ser.open()
    ser.rts = True   # pulso só no RTS (EN): reinicia no firmware
    time.sleep(0.2)
    ser.rts = False
    return ser


def medir(args, csv_saida, log_saida):
    import config
    ser = abrir(args.porta or config.require("TX_SERIAL_PORT"))
    os.makedirs(os.path.dirname(csv_saida), exist_ok=True)
    linhas, cpu_pendente, buf = [], None, b""
    t_ini = time.time()
    with open(log_saida, "w", encoding="utf-8") as log:
        def ler_linhas():
            nonlocal buf
            buf += ser.read(4096)
            *prontas, buf = buf.split(b"\n")
            for b in prontas:
                texto = b.decode("utf-8", "replace").rstrip("\r")
                log.write(f"{time.time() - t_ini:9.3f} {texto}\n")
                yield texto

        limite = time.time() + 30
        pronto = False
        while time.time() < limite and not pronto:
            pronto = any(["Comandos:" in t for t in ler_linhas()])  # lista: consome (e grava) o lote todo
        if not pronto:
            sys.exit("o nó não mostrou o banner em 30 s (firmware errado ou modo de gravação?)")
        ser.write(f"AUTO:{args.intervalo}\n".encode())
        print(f"AUTO:{args.intervalo} enviado; esperando {args.n + 1} ciclos")
        log.flush()

        while len(linhas) < args.n + 1:
            for texto in ler_linhas():
                if texto.startswith("[roi]") or texto.startswith("[tflite]"):
                    print("  ", texto)
                if texto.startswith("[CPU_FIM]"):
                    cpu_pendente = ler_cpu_fim(texto)
                elif texto.startswith("[CICLO_FIM]") and cpu_pendente is not None:
                    ciclo = {k: v for k, v in RE_PAR.findall(texto)}
                    r = {"registrado_em": datetime.now().isoformat(timespec="seconds"), "fluxo": args.fluxo,
                         "despertou": 0 if not linhas else 1, **cpu_pendente,
                         **{f"ciclo_{k}": v for k, v in ciclo.items() if k != "ciclo"}}
                    linhas.append(r)
                    cpu_pendente = None
                    print(f"ciclo {r['ciclo']}: {r['t_ms']} ms acordado, uso0={r['uso0']}% uso1={r['uso1']}% "
                          f"f={r['f_cpu_mhz']} MHz psram_pico={int(r['psram_pico']) // 1024} KB")
                    gravar(csv_saida, linhas)
            log.flush()
    ser.close()
    return linhas


def gravar(caminho, linhas):
    campos = []
    for r in linhas:
        campos += [k for k in r if k not in campos]
    with open(caminho, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=campos)
        w.writeheader()
        w.writerows(linhas)


def resumir(linhas):
    usar = [r for r in linhas if str(r.get("despertou")) == "1"]
    print(f"\nResumo: {len(usar)} ciclos acordados do deep sleep (o 1º ciclo, do comando AUTO, fica fora)")
    if not usar:
        return
    for k in ("f_cpu_mhz", "f_apb_mhz", "f_xtal_mhz", "pm"):
        print(f"  {k}: {sorted({r[k] for r in usar})}")

    def desc(chave, fmt="{:.1f}", escala=1.0):
        v = [float(r[chave]) / escala for r in usar if r.get(chave) not in (None, "", "-1.0")]
        if not v:
            return "-"
        return (f"mediana {fmt.format(st.median(v))}, média {fmt.format(st.mean(v))}, "
                f"{fmt.format(min(v))} a {fmt.format(max(v))}")

    for k in ("t_ms", "uso0", "uso1", "ocupado0_ms", "ocupado1_ms"):
        print(f"  {k}: {desc(k)}")
    for k in ("psram_total", "psram_pico", "interna_total", "interna_pico"):
        print(f"  {k} (KB): {desc(k, '{:.1f}', 1024)}")
    fases = [k[:-3] for k in usar[0] if k.endswith("_ms") and k[:-3] + "_uso0" in usar[0]]
    for f in fases:
        print(f"  fase {f}: {desc(f + '_ms', '{:.0f}')} ms; uso0 {desc(f + '_uso0')}; uso1 {desc(f + '_uso1')}")


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # console do Windows em cp932/cp1252
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("fluxo", choices=["ocr", "imagem"])
    p.add_argument("--n", type=int, default=30, help="ciclos acordados do deep sleep (lê n + 1)")
    p.add_argument("--intervalo", type=int, default=30, help="segundos de deep sleep (AUTO:<s>)")
    p.add_argument("--porta", help="porta da ESP32-CAM (padrão: TX_SERIAL_PORT do .env)")
    p.add_argument("--csv", help="padrão: medicoes/cpu/cpu_<fluxo>.csv")
    p.add_argument("--resumir", metavar="CSV", help="só resume um CSV já gravado")
    args = p.parse_args()

    if args.resumir:
        with open(args.resumir, encoding="utf-8") as f:
            resumir(list(csv.DictReader(f)))
        return
    csv_saida = args.csv or os.path.join(AQUI, "cpu", f"cpu_{args.fluxo}.csv")
    linhas = medir(args, csv_saida, os.path.splitext(csv_saida)[0] + ".log")
    print(f"-> {csv_saida}")
    resumir(linhas)


if __name__ == "__main__":
    main()
