"""
Mede a latencia ponta a ponta do fluxo de IMAGEM: do disparo no no ate a imagem
completa disponivel no PC que remonta os chunks.

Usa as duas seriais ao mesmo tempo, com um unico relogio (o do PC):
  - TX_SERIAL_PORT: ESP32-CAM (no). Dele vem o disparo e a linha "[camera] JPEG ...".
  - RX_SERIAL_PORT: Heltec (receptor). Dele vem cada chunk LoRaWAN.

Modos:
  capture  o PC manda CAPTURE ao no, N vezes. Disparo = instante em que o comando
           e escrito na serial.
  auto     o no esta em modo AUTO (deep sleep). Disparo = primeira linha do setup()
           apos o despertar ("[boot] causa=timer"), ~0,3-0,5 s depois do despertar
           real (boot da ROM nao aparece na serial). So escuta, nao manda nada.

Marcos medidos em cada leitura, em ms desde o disparo:
  t_ate_foto_ms            linha "[camera] JPEG" (captura + compressao concluidas)
  t_ate_primeiro_chunk_ms  primeiro chunk chegou ao receptor
  t_ate_ultimo_chunk_ms    ultimo chunk que completou a imagem
  t_ate_disponivel_ms      imagem remontada (e salva, se --salvar-imagens)  <- latencia ponta a ponta
  t_envio_ms               ultimo - primeiro chunk (tempo de enlace)

Leituras que nao completam (chunks perdidos, sem RESEND) entram no CSV com completo=0
e ficam fora das estatisticas de latencia.

Fluxo OCR na borda (--fluxo ocr, firmware Rede/transmissor_ocr_esp32cam): a leitura inteira
chega em UM uplink na FPort 2, entao nao ha chunks nem JPEG. No modo capture o PC manda LER
(no lugar de CAPTURE); no modo auto o no esta em AUTO e o disparo e o mesmo ("[boot]
causa=timer"). A leitura esta completa quando o uplink chega ao receptor:
  t_ate_ocr_ms       linha "[ocr] leitura=..." do no (segmentacao + digitos concluidos)
  t_ate_primeiro_chunk_ms = t_ate_ultimo_chunk_ms = chegada do uplink; t_envio_ms = 0
  t_ate_disponivel_ms  uplink recebido e decodificado <- latencia ponta a ponta do fluxo OCR
Colunas leitura e achou_caixa trazem o que chegou ao PC.

Requisitos:  pip install pyserial pycryptodome   (config no .env, como os outros scripts)
Uso:
  python latencia_ponta_a_ponta.py capture --n 30
  python latencia_ponta_a_ponta.py auto --n 30
  python latencia_ponta_a_ponta.py capture --n 30 --fluxo ocr
  python latencia_ponta_a_ponta.py auto --n 30 --fluxo ocr
"""
import argparse
import csv
import os
import queue
import re
import statistics as st
import sys
import threading
import time
from datetime import datetime

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(AQUI, ".."))  # enlace.py e config.py ficam na raiz

import enlace  # noqa: E402

CSV_PADRAO = os.path.join(AQUI, "latencia_ponta_a_ponta.csv")
CAMPOS = ["recebido_em", "modo", "fluxo", "leitura_id", "completo", "chunks_total",
          "chunks_recebidos", "duplicados", "jpeg_bytes", "rssi_medio",
          "t_ate_foto_ms", "t_ate_primeiro_chunk_ms", "t_ate_ultimo_chunk_ms",
          "t_envio_ms", "t_ate_disponivel_ms", "t_ate_ocr_ms", "leitura", "achou_caixa"]

RE_FOTO = re.compile(r"\[camera\] JPEG .*?: (\d+) bytes \(leitura id (\d+)\)")
RE_OCR_LEITURA = re.compile(r"\[ocr\] leitura=(\S+) achou_caixa=(\d)")
RE_OCR_ID = re.compile(r"\[ocr\] enviando leitura id (\d+)")
GATILHOS_AUTO = ("[boot] causa=timer", "[auto] ligado")


def _ms(t, t0):
    return None if t is None else round((t - t0) * 1000)


class Medidor:
    """Junta o que vem das duas seriais em uma linha de CSV por leitura.

    Nao toca em serial nem em relogio proprio: recebe cada linha ja com o instante
    em que foi lida (`t`, em segundos), o que permite testar sem hardware."""

    def __init__(self, app_skey, dev_addr, modo, fluxo="imagem", relogio=time.perf_counter,
                 pasta_imagens=None, log=None):
        self.app_skey, self.dev_addr = app_skey, dev_addr
        self.modo, self.fluxo = modo, fluxo
        self.relogio = relogio
        self.pasta_imagens = pasta_imagens
        self.log = log or (lambda *_: None)  # --debug: diz por que um uplink foi descartado
        self.atual = None
        self.linhas = []  # linhas finalizadas, na ordem

    # -- ciclo de vida de uma leitura ------------------------------------------------
    def disparar(self, t):
        """Inicia uma leitura. Se havia outra incompleta, ela e fechada como perdida."""
        if self.atual:
            self.fechar()
        self.atual = {"t0": t, "t_foto": None, "id": None, "total": None, "chunks": {},
                      "t_primeiro": None, "t_ultimo": None, "dup": 0, "rssi": [], "jpeg": None,
                      "t_ocr": None, "leitura": None, "achou": None}

    def fechar(self):
        """Encerra a leitura em andamento sem imagem completa (timeout ou novo disparo)."""
        a = self.atual
        if not a:
            return None
        self.atual = None
        return self._registrar(a, completo=False, t_disp=None)

    def _registrar(self, a, completo, t_disp):
        t0 = a["t0"]
        linha = {
            "recebido_em": datetime.now().isoformat(timespec="seconds"),
            "modo": self.modo, "fluxo": self.fluxo,
            "leitura_id": a["id"], "completo": int(completo),
            "chunks_total": a["total"], "chunks_recebidos": len(a["chunks"]),
            "duplicados": a["dup"], "jpeg_bytes": a["jpeg"],
            "rssi_medio": round(st.fmean(a["rssi"]), 1) if a["rssi"] else None,
            "t_ate_foto_ms": _ms(a["t_foto"], t0),
            "t_ate_primeiro_chunk_ms": _ms(a["t_primeiro"], t0),
            "t_ate_ultimo_chunk_ms": _ms(a["t_ultimo"], t0),
            "t_envio_ms": (None if a["t_primeiro"] is None
                           else round((a["t_ultimo"] - a["t_primeiro"]) * 1000)),
            "t_ate_disponivel_ms": _ms(t_disp, t0),
            "t_ate_ocr_ms": _ms(a["t_ocr"], t0),
            "leitura": a["leitura"],
            "achou_caixa": None if a["achou"] is None else int(a["achou"]),
        }
        self.linhas.append(linha)
        return linha

    # -- linhas vindas das seriais ---------------------------------------------------
    def linha_tx(self, texto, t):
        if self.modo == "auto" and any(g in texto for g in GATILHOS_AUTO):
            self.disparar(t)
            return None
        if self.fluxo == "ocr":
            m = RE_OCR_ID.search(texto)
            if m and self.atual and self.atual["id"] is None:
                self.atual["id"] = int(m.group(1))
            m = RE_OCR_LEITURA.search(texto)
            if m and self.atual and self.atual["t_ocr"] is None:
                self.atual["t_ocr"] = t
            return None
        m = RE_FOTO.search(texto)
        if m and self.atual and self.atual["id"] is None:
            self.atual["jpeg"] = int(m.group(1))
            self.atual["id"] = int(m.group(2))
            self.atual["t_foto"] = t
        return None

    def linha_rx(self, texto, t):
        """Devolve a linha de CSV quando este chunk completa a imagem, senao None."""
        a = self.atual
        m = enlace.LINE_RE.search(texto)
        if m and not a:
            self.log("[descartado] uplink recebido sem leitura em andamento (o gatilho do no nao apareceu)")
        if not m or not a:
            return None  # sem leitura em andamento: ignora
        if self.fluxo == "ocr":
            return self._linha_rx_ocr(a, m, t)
        if a["id"] is None:
            return None  # ainda sem a linha da foto: ignora
        try:
            info = enlace.parse_uplink(bytes.fromhex(m.group(1)), self.app_skey, self.dev_addr)
            if info["fport"] == enlace.FPORT_LEITURA:
                return None  # uplink do fluxo OCR em uma medicao do fluxo de imagem
            id_rx, idx, total, dados = enlace.parse_chunk(info["payload"])
        except ValueError as e:
            self.log(f"[descartado] {e}")
            return None
        if id_rx != a["id"]:
            return None  # chunk atrasado de outra foto
        a["total"] = total
        if idx in a["chunks"]:
            a["dup"] += 1
            return None
        a["chunks"][idx] = dados
        a["rssi"].append(int(m.group(2)))
        if a["t_primeiro"] is None:
            a["t_primeiro"] = t
        a["t_ultimo"] = t
        if len(a["chunks"]) < total:
            return None

        imagem = b"".join(a["chunks"][i] for i in range(total))
        if self.pasta_imagens:
            os.makedirs(self.pasta_imagens, exist_ok=True)
            with open(os.path.join(self.pasta_imagens, f"leitura_{a['id']}.jpg"), "wb") as f:
                f.write(imagem)
        t_disp = self.relogio()
        self.atual = None
        return self._registrar(a, completo=True, t_disp=t_disp)

    def _linha_rx_ocr(self, a, m, t):
        """Fluxo OCR: o uplink da leitura (FPort 2) completa a leitura de uma vez."""
        try:
            info = enlace.parse_uplink(bytes.fromhex(m.group(1)), self.app_skey, self.dev_addr)
            if info["fport"] != enlace.FPORT_LEITURA:
                return None  # chunk de imagem em uma medicao do fluxo OCR
            id_rx, achou, digitos = enlace.parse_leitura(info["payload"])
        except ValueError as e:
            self.log(f"[descartado] {e}")
            return None
        if a["id"] is not None and id_rx != a["id"]:
            self.log(f"[descartado] uplink com id {id_rx}, esperado {a['id']}")
            return None  # uplink atrasado de outra leitura
        a["id"], a["total"] = id_rx, 1
        a["chunks"][0] = digitos.encode("ascii")
        a["leitura"], a["achou"] = digitos, achou
        a["rssi"].append(int(m.group(2)))
        a["t_primeiro"] = a["t_ultimo"] = t
        t_disp = self.relogio()
        self.atual = None
        return self._registrar(a, completo=True, t_disp=t_disp)


def resumo(linhas):
    ok = [x["t_ate_disponivel_ms"] for x in linhas if x["completo"]]
    print(f"\n{len(linhas)} leituras, {len(ok)} completas, {len(linhas) - len(ok)} incompletas")
    if not ok:
        return
    ok.sort()
    p95 = ok[min(len(ok) - 1, int(round(0.95 * (len(ok) - 1))))]
    print(f"Latencia ponta a ponta (ms): min {ok[0]}  mediana {st.median(ok):.0f}  "
          f"p95 {p95}  max {ok[-1]}  media {st.fmean(ok):.0f}")
    if len(ok) < 30:
        print("Atencao: o criterio de pronto pede >= 30 leituras por fluxo.")


def abrir_csv(caminho):
    """Abre o CSV para anexar; se as colunas mudaram, preserva o antigo (como grab_image_debug.py)."""
    if os.path.exists(caminho):
        with open(caminho, newline="", encoding="utf-8") as f:
            antigo = next(csv.reader(f), None)
        if antigo != CAMPOS:
            os.replace(caminho, caminho.replace(".csv", f"_{time.strftime('%Y%m%d_%H%M%S')}.csv"))
    novo = not os.path.exists(caminho)
    f = open(caminho, "a", newline="", encoding="utf-8")
    w = csv.DictWriter(f, fieldnames=CAMPOS)
    if novo:
        w.writeheader()
    return f, w


def _leitor(ser, nome, fila, parar):
    while not parar.is_set():
        bruto = ser.readline()  # o instante e tomado logo que a linha chega
        t = time.perf_counter()
        if bruto:
            fila.put((nome, t, bruto.decode(errors="ignore").strip()))


def _abrir_serial(porta):
    import serial

    ser = serial.Serial()
    ser.port, ser.baudrate, ser.timeout = porta, 115200, 0.2
    ser.dtr = False  # evita resetar a placa ao abrir (igual a grab_image_debug.py)
    ser.rts = False
    ser.open()
    return ser


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("modo", choices=["capture", "auto"])
    p.add_argument("--n", type=int, default=30, help="numero de leituras (padrao 30)")
    p.add_argument("--timeout-s", type=float, default=600, help="tempo maximo por leitura no modo capture")
    p.add_argument("--pausa-s", type=float, default=5, help="espera entre leituras no modo capture")
    p.add_argument("--fluxo", choices=["imagem", "ocr"], default="imagem",
                   help="firmware do no: imagem (CAPTURE, chunks na FPort 1) ou ocr (LER, "
                        "leitura em um uplink na FPort 2); vai na coluna fluxo do CSV")
    p.add_argument("--csv", default=CSV_PADRAO)
    p.add_argument("--debug", action="store_true",
                   help="imprime cada linha das duas seriais e o motivo de cada uplink descartado")
    p.add_argument("--salvar-imagens", metavar="PASTA", help="salva cada imagem remontada (conta no tempo)")
    args = p.parse_args()

    import config

    app_skey = config.require_hex("LORA_APP_SKEY", 16)
    dev_addr = bytes.fromhex(config.get("LORA_DEV_ADDR", "")) or None
    med = Medidor(app_skey, dev_addr, args.modo, args.fluxo, pasta_imagens=args.salvar_imagens,
                  log=print if args.debug else None)

    tx = _abrir_serial(config.require("TX_SERIAL_PORT"))
    rx = _abrir_serial(config.require("RX_SERIAL_PORT"))
    fila, parar = queue.Queue(), threading.Event()
    leitores = []
    for ser, nome in ((tx, "tx"), (rx, "rx")):
        th = threading.Thread(target=_leitor, args=(ser, nome, fila, parar), daemon=True)
        th.start()
        leitores.append(th)
    print("Abrindo as seriais...")
    time.sleep(2)

    arquivo, escritor = abrir_csv(args.csv)

    def processar(nome, t, texto):
        if args.debug and texto:
            print(f"[{nome}] {texto[:160]}")
        linha = med.linha_tx(texto, t) if nome == "tx" else med.linha_rx(texto, t)
        return linha

    def publicar(linha):
        escritor.writerow(linha)
        arquivo.flush()
        extra = f" leitura {linha['leitura']}" if linha["leitura"] else ""
        print(f"[{len(med.linhas)}/{args.n}] id {linha['leitura_id']} completo={linha['completo']} "
              f"chunks {linha['chunks_recebidos']}/{linha['chunks_total']}{extra} "
              f"disponivel em {linha['t_ate_disponivel_ms']} ms")

    def consumir(timeout):
        try:
            nome, t, texto = fila.get(timeout=timeout)
        except queue.Empty:
            return
        antes = len(med.linhas)
        processar(nome, t, texto)
        for linha in med.linhas[antes:]:  # inclui a leitura fechada por um novo disparo
            publicar(linha)

    try:
        while len(med.linhas) < args.n:
            if args.modo == "capture":
                while not fila.empty():
                    fila.get_nowait()  # descarta o que sobrou da leitura anterior
                t0 = time.perf_counter()
                med.disparar(t0)
                tx.write(b"LER\n" if args.fluxo == "ocr" else b"CAPTURE\n")
                while med.atual and time.perf_counter() - t0 < args.timeout_s:
                    consumir(0.5)
                if med.atual:  # estourou o tempo
                    med.fechar()
                    publicar(med.linhas[-1])
                fim_pausa = time.time() + args.pausa_s
                while time.time() < fim_pausa:
                    consumir(0.5)
            else:
                consumir(1.0)
    except KeyboardInterrupt:
        print("\nInterrompido pelo usuario.")
    finally:
        parar.set()
        for th in leitores:
            th.join(timeout=1)  # fecha a porta so depois da leitura em curso (evita erro no encerramento)
        arquivo.close()
        tx.close()
        rx.close()
    resumo(med.linhas)


if __name__ == "__main__":
    main()
