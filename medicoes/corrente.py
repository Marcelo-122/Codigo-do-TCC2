"""
Captura e analisa as medicoes de corrente feitas com ina219_logger.ino.

  python corrente.py capturar COM5 corrente/sleep_60s.csv
      grava o CSV (t_us,shunt_mV,bus_V) enviado pelo logger; Ctrl+C encerra.

  python corrente.py analisar corrente/auto_30s.csv --offset-ma 0.4 \\
      --init-s 0.4 --captura-s 0.03 --envio-s 101.8 \\
      --bateria-mah 2000
      acha os ciclos (acorda -> ativo -> deep sleep), calcula mAh por ciclo,
      corrente media por estado e, se der --bateria-mah, a autonomia.

Como os ciclos sao achados: o sleep e o nivel de corrente mais baixo e constante
do arquivo. Qualquer trecho abaixo do limiar por >= --min-sleep-s e sleep; o
fim de cada sleep e um despertar. Um ciclo vai de um despertar ao proximo.
Os tempos --init-s/--captura-s/--envio-s vem da linha [CICLO_FIM] do no
(t_ate_ciclo_ms, t_captura_ms, t_envio_ms, em segundos aqui).
"""
import argparse
import csv
import os
import statistics as st
import sys

R_SHUNT_OHM = 0.1  # resistor R100 do modulo INA219; confira com um multimetro


def capturar(porta, saida, baud):
    import serial  # pyserial, ja usado no resto do repositorio

    n = 0
    os.makedirs(os.path.dirname(os.path.abspath(saida)), exist_ok=True)
    with serial.Serial(porta, baud, timeout=1) as ser, open(saida, "w", newline="") as f:
        f.write("t_us,shunt_mV,bus_V\n")
        print(f"Gravando em {saida}. Ctrl+C para parar.")
        try:
            while True:
                linha = ser.readline().decode("ascii", errors="ignore").strip()
                partes = linha.split(",")
                if len(partes) != 3 or not partes[0].isdigit():
                    if linha.startswith("#"):
                        print(linha)
                    continue
                try:
                    float(partes[1]), float(partes[2])
                except ValueError:
                    continue
                f.write(linha + "\n")
                n += 1
                if n % 5000 == 0:
                    f.flush()
                    print(f"{n} amostras")
        except KeyboardInterrupt:
            pass
    print(f"{n} amostras gravadas.")


def carregar(caminho, offset_ma):
    t, i, v = [], [], []
    anterior, volta = None, 0
    with open(caminho, newline="") as f:
        for linha in csv.DictReader(f):
            try:
                tu = int(linha["t_us"])
                sh = float(linha["shunt_mV"])
                bus = float(linha["bus_V"])
            except (ValueError, KeyError):
                continue
            if anterior is not None and tu < anterior:
                volta += 1 << 32  # micros() de 32 bits deu a volta
            anterior = tu
            t.append((tu + volta) / 1e6)
            i.append(sh / R_SHUNT_OHM - offset_ma)  # mV / ohm = mA
            v.append(bus)
    if len(t) < 100:
        sys.exit("Poucas amostras no arquivo.")
    t0 = t[0]
    return [x - t0 for x in t], i, v


def integra(t, i, a, b):
    """mAh entre os indices [a, b) pela regra do trapezio."""
    q = 0.0
    for k in range(a, min(b, len(t) - 1)):
        q += 0.5 * (i[k] + i[k + 1]) * (t[k + 1] - t[k])
    return q / 3600.0


def media(i, a, b):
    return st.fmean(i[a:b]) if b > a else float("nan")


def achar_sleeps(t, i, limiar, min_sleep_s):
    """Lista de (ini, fim) em indices dos trechos de sleep."""
    runs, ini = [], None
    for k, x in enumerate(i):
        if x < limiar and ini is None:
            ini = k
        elif x >= limiar and ini is not None:
            if t[k - 1] - t[ini] >= min_sleep_s:
                runs.append((ini, k))
            ini = None
    if ini is not None and t[-1] - t[ini] >= min_sleep_s:
        runs.append((ini, len(i)))
    return runs


def indice_em(t, alvo, a, b):
    for k in range(a, b):
        if t[k] >= alvo:
            return k
    return b


def analisar(args):
    t, i, v = carregar(args.csv, args.offset_ma)
    if args.max_amostras:  # so as primeiras N amostras (o no pode ter seguido ciclando depois)
        t, i, v = t[: args.max_amostras], i[: args.max_amostras], v[: args.max_amostras]
    baixos = sorted(i)[: max(10, len(i) // 10)]
    nivel_sleep = st.median(baixos)
    limiar = args.limiar_ma if args.limiar_ma else nivel_sleep + max(5.0, 0.5 * nivel_sleep)
    dur = t[-1]
    print(f"{len(t)} amostras em {dur:.1f} s ({len(t) / dur:.0f} Hz), tensao media {st.fmean(v):.3f} V")
    print(f"Nivel de sleep ~ {nivel_sleep:.2f} mA, limiar sleep/ativo = {limiar:.1f} mA")

    sleeps = achar_sleeps(t, i, limiar, args.min_sleep_s)
    if len(sleeps) < 2:
        sys.exit("Menos de 2 trechos de sleep: nao ha ciclo completo. Capture mais tempo ou ajuste --limiar-ma.")
    # Despertar k = fim do sleep k. Ciclo = [despertar k, despertar k+1).
    acordes = [fim for _, fim in sleeps]
    estados = []
    if args.init_s is not None:
        a = args.boot_rom_s
        b = a + args.init_s
        estados.append(("init+camera", 0.0, b))
        c = b + (args.captura_s or 0.0)
        estados.append(("captura", b, c))
        d = c + (args.envio_s or 0.0)
        estados.append(("envio (TX)", c, d))

    linhas = []
    for k in range(len(acordes) - 1):
        a, b = acordes[k], acordes[k + 1]
        ini_sleep = next((s for s, _ in sleeps if a < s <= b), b)
        q = integra(t, i, a, b)
        resumo = {
            "ciclo": k + 1,
            "periodo_s": t[b] - t[a] if b < len(t) else t[-1] - t[a],
            "ativo_s": t[ini_sleep] - t[a],
            "mAh": q,
            "ativo_mA": media(i, a, ini_sleep),
            "sleep_mA": media(i, ini_sleep, b),
            "pico_mA": max(i[a:b]),
        }
        for nome, e0, e1 in estados:
            ka = indice_em(t, t[a] + e0, a, b)
            kb = indice_em(t, t[a] + e1, a, b)
            resumo[nome] = media(i, ka, kb)
        linhas.append(resumo)

    cab = ["ciclo", "periodo_s", "ativo_s", "mAh", "ativo_mA", "sleep_mA", "pico_mA"] + [e[0] for e in estados]
    print("\n" + "  ".join(f"{c:>12}" for c in cab))
    for r in linhas:
        print("  ".join(f"{r[c]:>12.3f}" if c != "ciclo" else f"{r[c]:>12d}" for c in cab))

    mah = [r["mAh"] for r in linhas]
    periodo = st.fmean(r["periodo_s"] for r in linhas)
    sd = st.stdev(mah) if len(mah) > 1 else float("nan")
    print(f"\nmAh por leitura: {st.fmean(mah):.4f} (desvio {sd:.4f}, n={len(mah)} ciclos)")
    print(f"Periodo medio do ciclo: {periodo:.1f} s; corrente media do ciclo: {st.fmean(mah) * 3600 / periodo:.2f} mA")
    print("Para o criterio de pronto (>= 30 leituras por fluxo) sao necessarios >= 30 ciclos.")
    if args.bateria_mah:
        por_dia = 86400.0 / periodo
        dias = args.bateria_mah / (st.fmean(mah) * por_dia)
        print(f"Com bateria de {args.bateria_mah:.0f} mAh e 1 leitura a cada {periodo:.0f} s "
              f"({por_dia:.0f}/dia): {dias:.1f} dias (sem perdas de regulador, auto-descarga ou temperatura)")

    if args.png:
        try:
            import matplotlib

            matplotlib.use("Agg")
            import matplotlib.pyplot as plt

            plt.figure(figsize=(12, 4))
            plt.plot(t, i, lw=0.5)
            plt.axhline(limiar, color="r", ls="--", lw=0.8, label="limiar sleep/ativo")
            plt.xlabel("s")
            plt.ylabel("mA")
            plt.legend()
            plt.tight_layout()
            plt.savefig(args.png, dpi=120)
            print(f"Grafico em {args.png}")
        except ImportError:
            print("matplotlib nao instalado: grafico ignorado.")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("capturar")
    c.add_argument("porta")
    c.add_argument("saida")
    c.add_argument("--baud", type=int, default=921600)
    a = sub.add_parser("analisar")
    a.add_argument("csv")
    a.add_argument("--offset-ma", type=float, default=0.0, help="offset do INA219 medido com a carga desconectada")
    a.add_argument("--limiar-ma", type=float, default=None, help="limiar sleep/ativo (padrao: automatico)")
    a.add_argument("--min-sleep-s", type=float, default=2.0)
    a.add_argument("--max-amostras", type=int, default=None, help="analisa so as primeiras N amostras do arquivo")
    a.add_argument("--init-s", type=float, help="t_ate_ciclo_ms do no, em s")
    a.add_argument("--captura-s", type=float, help="t_captura_ms do no, em s")
    a.add_argument("--envio-s", type=float, help="t_envio_ms do no, em s")
    a.add_argument("--boot-rom-s", type=float, default=0.4,
                   help="tempo entre o despertar e o millis()=0 do setup (aproximado)")
    a.add_argument("--bateria-mah", type=float)
    a.add_argument("--png")
    args = p.parse_args()
    if args.cmd == "capturar":
        capturar(args.porta, args.saida, args.baud)
    else:
        analisar(args)


if __name__ == "__main__":
    main()
