"""
registro.py
Registro das medições do enlace LoRa: logs completos de cada execução e uma linha por
leitura (imagem) em medicoes/transmissao.csv, com PDR, tempo de rádio e latência.

Quem usa: reconstrutor.py (receptor, com ou sem controle do nó) e orchestrator.py.
Execucao, Leitura e Sessao não abrem serial nem têm relógio próprio: recebem cada linha já
com o instante em que foi lida (`t`, de time.perf_counter()), o que permite testar sem
hardware. Só `abrir_serial` e `LinhasSerial` (no fim do arquivo) tocam em porta serial.

O que é gravado, por execução, em medicoes/logs/<run_id>/:
  meta.json       quem/onde/como: argumentos, versões, commit do git, parâmetros do enlace,
                  contadores finais
  eventos.jsonl   uma linha JSON por evento (disparo, foto, chunk completo, timeout,
                  erro de serial, leitura encerrada com o resumo completo...)
  chunks.csv      uma linha por frame recebido, aceito ou não (RSSI, FCnt, perdidos
                  entre frames, status: novo/duplicado/ignorado...)
  serial_rx.txt   todas as linhas do receptor, com timestamp (DevAddr mascarado)
  serial_tx.txt   todas as linhas do nó, com timestamp (só quando o nó está ligado ao PC)
e, fora da pasta da execução:
  medicoes/transmissao.csv     uma linha por leitura, acumulada entre execuções
  medicoes/imagens/            a imagem de cada leitura (completa ou parcial)
  medicoes/transmissao_ocr.csv uma linha por leitura do fluxo OCR na borda (FPort 2): os dígitos
                               que chegaram, FCnt, tempo de rádio e, com o nó ligado, latência

Fluxo OCR (Rede/transmissor_ocr_esp32cam): um único uplink na FPort 2 carrega a leitura inteira,
então não há blocos nem JPEG. O receptor trata os dois fluxos juntos: FPort 1 vira imagem (como
sempre), FPort 2 vira uma linha em transmissao_ocr.csv. `fluxo="ocr"` só muda o que o nó
imprime/aceita com o nó ligado ao PC (LER no lugar de CAPTURE, linhas "[ocr] ...") e os timeouts.

Definições (as colunas do CSV seguem estas):
  pdr_leitura   blocos únicos recebidos / total de blocos da imagem.
  pdr_enlace    frames distintos recebidos / frames enviados pelo nó. "Enviados" vem do log
                do nó (tentativas menos "ocupado"), base "tx", ou, sem o nó ligado ao PC,
                da contagem de FCnt (recebidos + lacunas), base "fcnt", que NÃO enxerga
                perdas antes do primeiro nem depois do último frame recebido.
  tempo_radio_s soma do tempo no ar CALCULADO (Semtech AN1200.13, analise_tempo_no_ar.py)
                dos frames enviados (base "tx") ou recebidos (base "rx"). Não é medido.
  latencia_s    da escrita de CAPTURE no nó (base "disparo") até a imagem completa no PC;
                sem o nó ligado, do primeiro chunk (base "primeiro_chunk", subestima).

Privacidade: DevAddr e chaves LoRaWAN nunca são gravados (README, "Configuração de
segredos"). As linhas do receptor vão para serial_rx.txt com o DevAddr mascarado, e as
mensagens de erro do parser são trocadas por uma categoria.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import platform
import re
import statistics
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

import analise_tempo_no_ar as ar
import enlace

RAIZ = Path(__file__).resolve().parent
PASTA_MEDICOES = RAIZ / "medicoes"

# --- Linhas que o firmware do nó imprime (Rede/transmissor_esp32cam) -------------------
RE_FOTO = re.compile(r"\[camera\] JPEG .*?: (\d+) bytes \(leitura id (\d+)\)")
RE_CAMERA_FALHA = re.compile(r"\[camera\] (falha ao capturar|fmt2jpg falhou)|\[ERRO\] quadro")
RE_TENTATIVA = re.compile(r"\[chunk (\d+)/(\d+) tent (\d+)\] (\d+) bytes payload")
RE_OCUPADO = re.compile(r"\[aviso\] chunk (\d+) ocupado")
RE_FALHOU = re.compile(r"\[ERRO\] chunk (\d+) falhou")
RE_CONCLUIDO = re.compile(r"\[envio\] concluido: (\d+) ok, (\d+) falhas")

# --- Linhas que o firmware do fluxo OCR imprime (Rede/transmissor_ocr_esp32cam) --------
RE_OCR_LEITURA = re.compile(r"\[ocr\] leitura=(\S+) achou_caixa=(\d)")
RE_OCR_ID = re.compile(r"\[ocr\] enviando leitura id (\d+)")
RE_OCR_FALHA = re.compile(r"\[ocr\] (camera|modelos) indisponive|\[ciclo\] OCR nao rodou"
                          r"|\[camera\] falha ao capturar|\[ERRO\] (quadro|sem memoria)")
RE_UPLINK_TENT = re.compile(r"\[uplink tent (\d+)\] (\d+) bytes payload")
RE_UPLINK_OCUPADO = re.compile(r"\[aviso\] modulo ocupado")
RE_UPLINK_FALHOU = re.compile(r"\[ERRO\] uplink falhou")

# DevAddr (bytes 1 a 4 do frame LoRaWAN) mascarado nos logs
_RE_HEX_FRAME = re.compile(r"(HEX:[0-9A-Fa-f]{2})[0-9A-Fa-f]{8}")

# Salto de FCnt acima disso é tratado como reinício do contador, não como perdas
_LIMITE_LACUNA_FCNT = 1000

CAMPOS_TRANSMISSAO = [
    "run_id", "leitura_id", "distancia_m", "rotulo", "modo", "status", "motivo_fim",
    "inicio", "fim",
    "sf", "bw_khz", "chunk_bytes", "intervalo_envio_s",
    "jpeg_bytes", "jpeg_valido", "total_blocos", "blocos_unicos", "blocos_faltando",
    "frames_validos", "duplicados", "duplicados_divergentes", "total_divergente",
    "tamanho_anomalo",
    "blocos_enviados", "blocos_enviados_base", "pdr_leitura", "pdr_enlace",
    "fcnt_perdidos", "fcnt_repetidos", "fcnt_reinicios",
    "rssi_min_dbm", "rssi_medio_dbm", "rssi_max_dbm",
    "tempo_radio_s", "tempo_radio_base",
    "t_foto_s", "t_primeiro_chunk_s", "t_envio_s", "latencia_s", "latencia_base",
    "tx_tentativas", "tx_ocupado", "tx_falhas", "tx_ok_reportado",
    "imagem_arquivo", "imagem_sha256",
]

CAMPOS_OCR = [
    "run_id", "leitura_id", "distancia_m", "rotulo", "modo", "status", "motivo_fim",
    "inicio", "fim",
    "sf", "bw_khz", "payload_bytes",
    "leitura", "achou_caixa", "digitos_incertos", "leitura_no", "leitura_confere",
    "duplicados", "rssi_dbm", "fcnt", "fcnt_perdidos_antes",
    "tempo_radio_s", "tempo_radio_base",
    "t_ocr_s", "latencia_s", "latencia_base",
    "tx_tentativas", "tx_ocupado", "tx_falhas",
]

CAMPOS_CHUNKS = [
    "ts", "t_s", "n", "status", "leitura_id", "indice", "total", "dados_bytes",
    "rssi_dbm", "fcnt", "fcnt_delta", "fcnt_perdidos_antes", "fport", "frame_bytes", "detalhe",
]


# --- Utilitários -----------------------------------------------------------------------
def mascarar_linha(texto: str) -> str:
    """Troca o DevAddr de uma linha 'HEX:<frame>|RSSI:<n>' por XXXXXXXX."""
    return _RE_HEX_FRAME.sub(r"\1XXXXXXXX", texto)


def jpeg_valido(dados: bytes) -> bool:
    """Confere só os marcadores: começa com SOI (FFD8) e termina com EOI (FFD9)."""
    return len(dados) >= 4 and dados[:2] == b"\xff\xd8" and dados[-2:] == b"\xff\xd9"


def _categoria_erro(erro: ValueError) -> str:
    """Resume o erro do parser sem repetir endereço de rede nem bytes do frame."""
    msg = str(erro)
    if "DevAddr" in msg:
        return "dev_addr_diferente"
    if msg.startswith("frame curto"):
        return "frame_curto"
    if msg.startswith("frame sem FPort"):
        return "frame_sem_payload"
    if msg.startswith("payload curto"):
        return "payload_curto"
    if msg.startswith("cabeçalho inválido"):
        return "cabecalho_invalido"
    if msg.startswith("chunk com"):
        return "chunk_grande_demais"
    if msg.startswith("leitura inválida"):
        return "leitura_invalida"
    if msg.startswith("fport de imagem"):
        return "fport_imagem_em_fluxo_ocr"
    return "erro_parser"


def _arred(valor, casas=3):
    return "" if valor is None else round(valor, casas)


def _slug(texto: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", texto).strip("-")[:40]


def _git_info() -> dict:
    """Commit atual e se há alterações em arquivos rastreados (para reproduzir a medição)."""
    def git(*args):
        r = subprocess.run(["git", *args], cwd=RAIZ, capture_output=True, text=True, timeout=5)
        return r.stdout.strip() if r.returncode == 0 else None
    try:
        return {"commit": git("rev-parse", "--short", "HEAD"),
                "alterado": bool(git("status", "--porcelain", "--untracked-files=no"))}
    except (OSError, subprocess.SubprocessError):
        return {"commit": None, "alterado": None}


def anexar_csv(caminho: Path, campos: list[str], linha: dict) -> None:
    """Acrescenta uma linha ao CSV, gravando-a em disco na hora (fsync).

    Se o arquivo já existe com colunas diferentes, o antigo é preservado com um sufixo de data
    e um novo começa: nunca se misturam linhas de formatos diferentes sob um só cabeçalho."""
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    if caminho.exists() and caminho.stat().st_size > 0:
        with open(caminho, newline="", encoding="utf-8") as f:
            antigo = next(csv.reader(f), None)
        if antigo != campos:
            destino = caminho.with_name(f"{caminho.stem}_{time.strftime('%Y%m%d_%H%M%S')}{caminho.suffix}")
            os.replace(caminho, destino)
            print(f"[registro] colunas de {caminho.name} mudaram: o arquivo antigo foi guardado como {destino.name}")
    novo = not caminho.exists() or caminho.stat().st_size == 0
    with open(caminho, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=campos, extrasaction="ignore")
        if novo:
            w.writeheader()
        w.writerow(linha)
        f.flush()
        os.fsync(f.fileno())


# --- Execução: pasta de logs de uma rodada ---------------------------------------------
class Execucao:
    """Uma rodada de medição (do início ao Ctrl+C): dona dos arquivos de log."""

    def __init__(self, modo: str, rotulo: str = "", distancia_m: float | None = None,
                 pasta_medicoes: Path | str = PASTA_MEDICOES, extras: dict | None = None,
                 relogio=time.perf_counter, agora=datetime.now, imprimir=print):
        self.modo = modo
        self.rotulo = rotulo
        self.distancia_m = distancia_m
        self.pasta_medicoes = Path(pasta_medicoes)
        self.relogio = relogio
        self.imprimir = imprimir
        self._t0_mono = relogio()
        self._t0_wall = agora().astimezone()
        self.contadores: Counter = Counter()
        self.n_chunks = 0
        self._avisou_disco = False
        self._arquivos: dict = {}

        base = self._t0_wall.strftime("%Y%m%d_%H%M%S") + (f"_{_slug(rotulo)}" if rotulo else "")
        self.run_id, sufixo = base, 1
        while True:
            self.pasta = self.pasta_medicoes / "logs" / self.run_id
            try:
                self.pasta.mkdir(parents=True, exist_ok=False)
                break
            except FileExistsError:
                sufixo += 1
                self.run_id = f"{base}_{sufixo}"
        self.pasta_imagens = self.pasta_medicoes / "imagens"
        self.arquivo_transmissao = self.pasta_medicoes / "transmissao.csv"
        self.arquivo_ocr = self.pasta_medicoes / "transmissao_ocr.csv"

        self._chunks_csv = open(self.pasta / "chunks.csv", "w", newline="", encoding="utf-8")
        self._chunks_w = csv.DictWriter(self._chunks_csv, fieldnames=CAMPOS_CHUNKS)
        self._chunks_w.writeheader()
        self._eventos = open(self.pasta / "eventos.jsonl", "w", encoding="utf-8")

        self.meta = {
            "run_id": self.run_id, "inicio": self.iso(self._t0_mono), "fim": None,
            "modo": modo, "rotulo": rotulo, "distancia_m": distancia_m,
            "comando": sys.argv,
            "host": platform.node(), "so": platform.platform(),
            "python": sys.version.split()[0], "pyserial": _versao_pyserial(),
            "git": _git_info(),
            "enlace": {
                "sf": enlace.SF, "bw_khz": enlace.BW_KHZ, "freq_mhz": enlace.FREQ_MHZ,
                "chunk_bytes": enlace.CHUNK_DATA_SIZE, "cabecalho_bytes": enlace.HEADER_SIZE,
                "fport": enlace.FPORT, "fport_leitura": enlace.FPORT_LEITURA,
                "intervalo_envio_s": enlace.INTERVALO_ENVIO_S,
            },
            "tempo_no_ar": "calculado (Semtech AN1200.13, analise_tempo_no_ar.py), nao medido",
            "privacidade": "DevAddr e chaves nao sao gravados; DevAddr mascarado em serial_rx.txt",
            **(extras or {}),
        }
        self._gravar_meta()
        self.evento("run_inicio", mono=self._t0_mono, pasta=str(self.pasta))

    # -- tempo ----------------------------------------------------------------------------
    def wall(self, mono: float) -> datetime:
        return self._t0_wall + timedelta(seconds=mono - self._t0_mono)

    def iso(self, mono: float | None) -> str:
        return "" if mono is None else self.wall(mono).isoformat(timespec="milliseconds")

    def rel(self, mono: float) -> float:
        return round(mono - self._t0_mono, 3)

    # -- escrita (uma falha de disco avisa uma vez e não derruba a medição) ----------------
    def _escrever(self, escrever) -> None:
        try:
            escrever()
        except (OSError, ValueError) as e:
            if not self._avisou_disco:
                self._avisou_disco = True
                self.imprimir(f"[registro] ERRO ao gravar log: {e} (a medição continua)")

    def _gravar_meta(self) -> None:
        def _f():
            tmp = self.pasta / "meta.json.tmp"
            tmp.write_text(json.dumps(self.meta, ensure_ascii=False, indent=2, default=str),
                           encoding="utf-8")
            os.replace(tmp, self.pasta / "meta.json")
        self._escrever(_f)

    def evento(self, tipo: str, mono: float | None = None, **campos) -> None:
        mono = self.relogio() if mono is None else mono
        linha = {"ts": self.iso(mono), "t_s": self.rel(mono), "evento": tipo, **campos}

        def _f():
            self._eventos.write(json.dumps(linha, ensure_ascii=False, default=str) + "\n")
            self._eventos.flush()
        self._escrever(_f)

    def serial(self, canal: str, texto: str, mono: float) -> None:
        """Grava a linha crua da serial ('rx' = receptor, 'tx' = nó) com o instante da leitura."""
        if canal == "rx":
            texto = mascarar_linha(texto)

        def _f():
            arq = self._arquivos.get(canal)
            if arq is None:
                arq = self._arquivos[canal] = open(self.pasta / f"serial_{canal}.txt", "w",
                                                   encoding="utf-8")
            arq.write(f"{self.iso(mono)}\t{self.rel(mono)}\t{texto}\n")
            arq.flush()
        self._escrever(_f)

    def chunk(self, mono: float, status: str, **campos) -> None:
        """Uma linha em chunks.csv (todo frame recebido, aceito ou não)."""
        self.n_chunks += 1
        linha = {"ts": self.iso(mono), "t_s": self.rel(mono), "n": self.n_chunks,
                 "status": status, **campos}

        def _f():
            self._chunks_w.writerow(linha)
            self._chunks_csv.flush()
        self._escrever(_f)

    def registrar_envio(self, linha: dict) -> None:
        self._escrever(lambda: anexar_csv(self.arquivo_transmissao, CAMPOS_TRANSMISSAO, linha))

    def registrar_leitura_ocr(self, linha: dict) -> None:
        self._escrever(lambda: anexar_csv(self.arquivo_ocr, CAMPOS_OCR, linha))

    def fechar(self, **resumo) -> None:
        if self._chunks_csv.closed:
            return
        self.evento("run_fim", contadores=dict(self.contadores), **resumo)
        self.meta["fim"] = self.iso(self.relogio())
        self.meta["contadores"] = dict(self.contadores)
        self.meta.update(resumo)
        self._gravar_meta()
        for arq in [self._chunks_csv, self._eventos, *self._arquivos.values()]:
            try:
                arq.close()
            except OSError:
                pass

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.fechar()


def _versao_pyserial() -> str | None:
    try:
        import serial
        return getattr(serial, "__version__", None)
    except ImportError:
        return None


# --- Leitura: o estado de uma imagem em andamento --------------------------------------
class Leitura:
    """Tudo o que se sabe de uma imagem (um id de leitura): chunks, tempos, contadores."""

    def __init__(self, leitura_id: int | None = None, t_disparo: float | None = None,
                 t_abertura: float | None = None):
        self.id = leitura_id
        self.t_disparo = t_disparo       # instante em que o PC mandou CAPTURE (None se não controla o nó)
        self.t_abertura = t_abertura     # instante do primeiro sinal (disparo ou 1º chunk)
        self.t_foto = None               # linha "[camera] JPEG ..." do nó
        self.jpeg_bytes_tx = None        # tamanho do JPEG segundo o nó
        self.total = None
        self.chunks: dict[int, bytes] = {}
        self.t_primeiro = None           # 1º frame válido
        self.t_ultimo_novo = None        # último chunk inédito
        self.t_ultimo_frame = None       # último frame válido, mesmo duplicado
        self.t_completa = None
        self.frames_validos = 0
        self.duplicados = 0
        self.duplicados_divergentes = 0
        self.total_divergente = 0
        self.tamanho_anomalo = 0
        self.rssi: list[int] = []
        self.airtime_rx_ms = 0.0
        self.fcnt_primeiro = None
        self.fcnt_ultimo = None
        self.fcnt_perdidos = 0
        self.fcnt_repetidos = 0
        self.fcnt_reinicios = 0
        self.tx_observado = False        # alguma linha de envio do nó foi atribuída a esta leitura
        self.tx_tentativas = 0
        self.tx_ocupado = 0
        self.tx_falhas = 0
        self.tx_airtime_ms = 0.0
        self._ultima_tentativa_ms = 0.0
        self.tx_ok_reportado = None      # "[envio] concluido: N ok"
        self.t_envio_concluido = None
        self.t_ocr = None                # fluxo OCR: linha "[ocr] leitura=..." do nó (OCR concluído)
        self.leitura_tx = None           # fluxo OCR: a leitura que o nó diz ter feito

    @property
    def completa(self) -> bool:
        return self.total is not None and len(self.chunks) == self.total

    @property
    def faltando(self) -> list[int]:
        return [] if self.total is None else [i for i in range(self.total) if i not in self.chunks]

    def imagem(self) -> bytes:
        return b"".join(self.chunks[i] for i in range(self.total))

    def imagem_parcial(self) -> bytes:
        """Com zeros nos blocos que faltam (abre como JPEG parcial)."""
        return b"".join(self.chunks.get(i, b"\x00" * enlace.CHUNK_DATA_SIZE)
                        for i in range(self.total or 0))

    def registrar_frame(self, t: float, idx: int, total: int, dados: bytes, rssi: int,
                        fcnt: int) -> dict:
        """Contabiliza um frame válido. Devolve {status, fcnt_delta, fcnt_perdidos_antes}."""
        self.frames_validos += 1
        self.rssi.append(rssi)
        self.airtime_rx_ms += ar.tempo_no_ar_ms(
            ar.OVERHEAD_LORAWAN + enlace.HEADER_SIZE + len(dados), enlace.SF, enlace.BW_KHZ * 1000)
        if self.t_primeiro is None:
            self.t_primeiro = t
        self.t_ultimo_frame = t

        # FCnt: cada AT+SENDB incrementa; lacunas = frames enviados que o receptor não viu
        delta, perdidos = None, 0
        if self.fcnt_ultimo is None:
            self.fcnt_primeiro = fcnt
        else:
            delta = (fcnt - self.fcnt_ultimo) & 0xFFFF
            if delta == 0:
                self.fcnt_repetidos += 1
            elif delta <= _LIMITE_LACUNA_FCNT:
                perdidos = delta - 1
                self.fcnt_perdidos += perdidos
            else:
                self.fcnt_reinicios += 1
        self.fcnt_ultimo = fcnt
        info = {"fcnt_delta": delta, "fcnt_perdidos_antes": perdidos}

        if self.total is not None and total != self.total:
            self.total_divergente += 1
            return {"status": "total_divergente", **info}
        self.total = total

        # Só o último bloco pode ser menor que o tamanho cheio
        if (idx < total - 1 and len(dados) != enlace.CHUNK_DATA_SIZE) or len(dados) == 0:
            self.tamanho_anomalo += 1

        if idx in self.chunks:
            self.duplicados += 1
            if self.chunks[idx] != dados:
                self.duplicados_divergentes += 1
                return {"status": "duplicado_divergente", **info}
            return {"status": "duplicado", **info}

        self.chunks[idx] = dados
        self.t_ultimo_novo = t
        return {"status": "novo", **info}

    def registrar_linha_tx(self, texto: str, t: float) -> str | None:
        """Interpreta uma linha do nó que pertence a esta leitura. Devolve o tipo, ou None."""
        m = RE_TENTATIVA.search(texto)
        if m:
            self.tx_observado = True
            self.tx_tentativas += 1
            self._ultima_tentativa_ms = ar.tempo_no_ar_ms(
                ar.OVERHEAD_LORAWAN + int(m.group(4)), enlace.SF, enlace.BW_KHZ * 1000)
            self.tx_airtime_ms += self._ultima_tentativa_ms
            return "tentativa"
        if RE_OCUPADO.search(texto):       # a tentativa anterior não foi ao ar
            self.tx_observado = True
            self.tx_ocupado += 1
            self.tx_airtime_ms -= self._ultima_tentativa_ms
            self._ultima_tentativa_ms = 0.0
            return "ocupado"
        if RE_FALHOU.search(texto):
            self.tx_observado = True
            self.tx_falhas += 1
            return "falhou"
        m = RE_CONCLUIDO.search(texto)
        if m:
            self.tx_observado = True
            self.tx_ok_reportado = int(m.group(1))
            self.t_envio_concluido = t
            return "concluido"
        # Fluxo OCR: o uplink da leitura (mesma contabilidade, com as mensagens do outro firmware)
        m = RE_UPLINK_TENT.search(texto)
        if m:
            self.tx_observado = True
            self.tx_tentativas += 1
            self._ultima_tentativa_ms = ar.tempo_no_ar_ms(
                ar.OVERHEAD_LORAWAN + int(m.group(2)), enlace.SF, enlace.BW_KHZ * 1000)
            self.tx_airtime_ms += self._ultima_tentativa_ms
            return "tentativa"
        if RE_UPLINK_OCUPADO.search(texto):
            self.tx_observado = True
            self.tx_ocupado += 1
            self.tx_airtime_ms -= self._ultima_tentativa_ms
            self._ultima_tentativa_ms = 0.0
            return "ocupado"
        if RE_UPLINK_FALHOU.search(texto):
            self.tx_observado = True
            self.tx_falhas += 1
            return "falhou"
        return None


# --- Sessão: liga as linhas das seriais às leituras e ao registro ----------------------
class Sessao:
    """Recebe as linhas do receptor (e do nó, se ligado ao PC) e mantém o registro.

    Controla uma leitura por vez (`atual`). Uma leitura termina quando:
      completa        todos os blocos chegaram (com `grace_s` de espera pelo "[envio] concluido"
                      do nó, que traz as contagens finais de transmissão)
      tx_concluido    o nó terminou de enviar e ainda faltam blocos
      nova_leitura    chegou um chunk de outro id (só sem controle do nó)
      timeout_*       inatividade (sem controle do nó), leitura longa demais, ou o nó não
                      respondeu ao CAPTURE (sem_foto)
      interrompido / fim_da_execucao   encerramento pelo chamador
    """

    def __init__(self, execucao: Execucao, app_skey: bytes, dev_addr: bytes | None = None, *,
                 grace_s: float = 0.0, timeout_inatividade_s: float = 300.0,
                 timeout_leitura_s: float = 900.0, timeout_foto_s: float = 30.0,
                 salvar_imagens: bool = True, imprimir=print, fluxo: str = "imagem"):
        self.fluxo = fluxo                # "imagem" ou "ocr" (ver o docstring do módulo)
        self.ex = execucao
        self.app_skey = app_skey
        self.dev_addr = dev_addr
        self.grace_s = grace_s
        self.timeout_inatividade_s = timeout_inatividade_s
        self.timeout_leitura_s = timeout_leitura_s
        self.timeout_foto_s = timeout_foto_s
        self.salvar_imagens = salvar_imagens
        self.imprimir = imprimir
        self.atual: Leitura | None = None
        self.historico: dict[int, Leitura] = {}
        self.resumos: list[dict] = []
        self.resumos_ocr: list[dict] = []   # linhas de transmissao_ocr.csv desta execução
        self._fcnt_ocr: int | None = None   # FCnt do último uplink de leitura (FPort 2)
        self._ocr_vistos: set[tuple[int, int]] = set()   # (id, FCnt) já registrados

    @property
    def n_leituras(self) -> int:
        """Leituras encerradas desta execução, de imagem e de OCR."""
        return len(self.resumos) + len(self.resumos_ocr)

    # -- entrada ---------------------------------------------------------------------------
    def disparar(self, t: float, leitura_id: int | None = None) -> Leitura:
        """O PC acabou de mandar o comando que inicia o envio de uma imagem."""
        if self.atual:
            self.encerrar("novo_disparo", t)
        self.atual = Leitura(leitura_id, t_disparo=t, t_abertura=t)
        if leitura_id is not None:
            self.historico[leitura_id] = self.atual
        self.ex.evento("disparo", t, leitura_id=leitura_id)
        return self.atual

    def linha_tx(self, texto: str, t: float) -> None:
        """Uma linha da serial do nó (ESP32-CAM)."""
        self.ex.serial("tx", texto, t)
        if self.fluxo == "ocr":
            self._linha_tx_ocr(texto, t)
            return
        a = self.atual
        m = RE_FOTO.search(texto)
        if m:
            jpeg, lid = int(m.group(1)), int(m.group(2))
            if a is None or a.id not in (None, lid):   # foto sem disparo nosso (ex.: modo AUTO do nó)
                if a is not None:
                    self.encerrar("nova_leitura", t)
                a = self.atual = Leitura(t_abertura=t)
            a.id, a.t_foto, a.jpeg_bytes_tx = lid, t, jpeg
            self.historico[lid] = a
            self.ex.evento("foto", t, leitura_id=lid, jpeg_bytes=jpeg)
            self.imprimir(f"[leitura {lid}] foto de {jpeg} bytes, {-(-jpeg // enlace.CHUNK_DATA_SIZE)} blocos")
        elif RE_CAMERA_FALHA.search(texto):
            self.ex.contadores["falhas_camera"] += 1
            self.ex.evento("falha_camera", t, linha=texto)
            if a is not None and a.id is None:
                self.encerrar("falha_captura", t)
        elif a is not None:
            tipo = a.registrar_linha_tx(texto, t)
            if tipo in ("ocupado", "falhou", "concluido"):
                self.ex.evento(f"tx_{tipo}", t, leitura_id=a.id, linha=texto)
        self.verificar(t)

    def _linha_tx_ocr(self, texto: str, t: float) -> None:
        """Uma linha do nó no fluxo OCR (transmissor_ocr_esp32cam)."""
        a = self.atual
        m = RE_OCR_LEITURA.search(texto)
        if m:
            if a is not None and a.t_ocr is None:
                a.t_ocr, a.leitura_tx = t, m.group(1)
                self.ex.evento("ocr_concluido", t, leitura=m.group(1), achou_caixa=int(m.group(2)))
            self.verificar(t)
            return
        m = RE_OCR_ID.search(texto)
        if m:
            if a is not None and a.id is None:
                a.id = int(m.group(1))
                self.ex.evento("ocr_id", t, leitura_id=a.id)
            self.verificar(t)
            return
        if RE_OCR_FALHA.search(texto):
            self.ex.contadores["falhas_ocr"] += 1
            self.ex.evento("falha_ocr", t, linha=texto)
            if a is not None and a.id is None and a.t_ocr is None:
                self.encerrar("falha_ocr", t)
            return
        if a is not None:
            tipo = a.registrar_linha_tx(texto, t)
            if tipo in ("ocupado", "falhou"):
                self.ex.evento(f"tx_{tipo}", t, leitura_id=a.id, linha=texto)
        self.verificar(t)

    def linha_rx(self, texto: str, t: float) -> dict | None:
        """Uma linha da serial do receptor. Devolve o resultado se for um frame, senão None."""
        self.ex.serial("rx", texto, t)
        m = enlace.LINE_RE.search(texto)
        if not m:
            return None
        hex_frame, rssi = m.group(1), int(m.group(2))
        self.ex.contadores["frames_rx"] += 1
        try:
            raw = bytes.fromhex(hex_frame)
            info = enlace.parse_uplink(raw, self.app_skey, self.dev_addr)
            if info["fport"] == enlace.FPORT_LEITURA:     # fluxo OCR: a leitura inteira em um frame
                lid, achou, digitos = enlace.parse_leitura(info["payload"])
                return self._frame_leitura(t, info, rssi, len(raw), lid, achou, digitos)
            if self.fluxo == "ocr":
                raise ValueError("fport de imagem em fluxo ocr")
            lid, idx, total, dados = enlace.parse_chunk(info["payload"])
        except ValueError as e:
            categoria = _categoria_erro(e)
            self.ex.contadores["frames_ignorados"] += 1
            self.ex.contadores[f"ignorado_{categoria}"] += 1
            self.ex.chunk(t, "ignorado", rssi_dbm=rssi, frame_bytes=len(hex_frame) // 2,
                          detalhe=categoria)
            return {"status": "ignorado", "detalhe": categoria}

        fcnt = info["fcnt"]
        base = {"leitura_id": lid, "indice": idx, "total": total, "dados_bytes": len(dados),
                "rssi_dbm": rssi, "fcnt": fcnt, "fport": info["fport"], "frame_bytes": len(raw)}

        # A que leitura pertence este chunk?
        a = self.atual
        if a is not None and a.id is None:           # nó ligado, mas o id ainda não chegou pela serial
            a.id = lid
            self.historico[lid] = a
            self.ex.evento("id_pelo_chunk", t, leitura_id=lid)
        ja = self.historico.get(lid)
        if ja is not None and ja is not a:           # chunk atrasado de uma leitura já encerrada
            self.ex.contadores["frames_pos_encerramento"] += 1
            self.ex.chunk(t, "pos_encerramento", **base)
            return {"status": "pos_encerramento", "leitura_id": lid}
        if a is not None and a.id != lid:
            if a.t_disparo is None:                  # sem controle do nó: chunk de outra foto = nova leitura
                self.encerrar("nova_leitura", t)
                a = None
            else:                                    # com controle: não é a foto que o nó acabou de tirar
                self.ex.contadores["frames_outra_leitura"] += 1
                self.ex.chunk(t, "outra_leitura", **base)
                return {"status": "outra_leitura", "leitura_id": lid}
        if a is None:
            a = self.atual = Leitura(lid, t_abertura=t)
            self.historico[lid] = a
            self.ex.evento("leitura_aberta", t, leitura_id=lid, total=total)
            self.imprimir(f"[leitura {lid}] detectada: {total} blocos de até {enlace.CHUNK_DATA_SIZE} bytes")

        r = a.registrar_frame(t, idx, total, dados, rssi, fcnt)
        self.ex.contadores[f"frames_{r['status']}"] += 1
        self.ex.chunk(t, r["status"], fcnt_delta=r["fcnt_delta"] if r["fcnt_delta"] is not None else "",
                      fcnt_perdidos_antes=r["fcnt_perdidos_antes"], **base)
        if r["status"] == "novo":
            self.imprimir(f"  [bloco {idx:>3}/{total - 1}] {len(dados):>3} B  RSSI={rssi} dBm  "
                          f"FCnt={fcnt}  faltam {total - len(a.chunks)}")
        else:
            self.imprimir(f"  [bloco {idx:>3}/{total - 1}] {r['status']}")
        if r["fcnt_perdidos_antes"]:
            self.imprimir(f"  [aviso] {r['fcnt_perdidos_antes']} frame(s) perdido(s) antes deste (lacuna de FCnt)")
        if a.completa and a.t_completa is None:
            a.t_completa = t
            self.ex.evento("imagem_completa", t, leitura_id=a.id)
        self._avaliar_fim(t)
        return {"status": r["status"], "leitura_id": lid, "indice": idx, "total": total,
                "rssi": rssi, "fcnt": fcnt}

    # -- fluxo OCR: a leitura chega inteira em um frame (FPort 2) -------------------------
    def _frame_leitura(self, t: float, info: dict, rssi: int, frame_bytes: int,
                       lid: int, achou: bool, digitos: str) -> dict:
        """Registra um uplink de leitura. Com o nó ligado ao PC (fluxo ocr), fecha a leitura em
        andamento e mede a latência a partir do disparo; sem o nó, grava a linha direto."""
        fcnt = info["fcnt"]
        n_bytes = len(info["payload"])
        a = self.atual if self.fluxo == "ocr" else None
        base = {"leitura_id": lid, "indice": 0, "total": 1, "dados_bytes": n_bytes,
                "rssi_dbm": rssi, "fcnt": fcnt, "fport": info["fport"], "frame_bytes": frame_bytes}
        self.ex.contadores["frames_leitura"] += 1

        if (lid, fcnt) in self._ocr_vistos:           # o mesmo uplink de novo
            self.ex.contadores["frames_duplicado"] += 1
            self.ex.chunk(t, "duplicado", **base)
            return {"status": "duplicado", "leitura_id": lid}
        if a is not None and a.id is not None and a.id != lid:   # atraso de outra leitura
            self.ex.contadores["frames_outra_leitura"] += 1
            self.ex.chunk(t, "outra_leitura", **base)
            return {"status": "outra_leitura", "leitura_id": lid}
        self._ocr_vistos.add((lid, fcnt))

        # FCnt: cada uplink incrementa; a lacuna é o que o receptor não viu (não enxerga
        # perdas antes do primeiro nem depois do último uplink recebido)
        delta, perdidos = None, 0
        if self._fcnt_ocr is not None:
            delta = (fcnt - self._fcnt_ocr) & 0xFFFF
            if 0 < delta <= _LIMITE_LACUNA_FCNT:
                perdidos = delta - 1
            elif delta > _LIMITE_LACUNA_FCNT:
                self.ex.contadores["fcnt_reinicios_leitura"] += 1
        self._fcnt_ocr = fcnt
        self.ex.chunk(t, "novo", fcnt_delta="" if delta is None else delta,
                      fcnt_perdidos_antes=perdidos, **base)

        if a is not None:
            if a.id is None:
                a.id = lid
            a.t_primeiro = a.t_completa = t
        linha = self._linha_ocr(a, lid, t, achou=achou, digitos=digitos, rssi=rssi, fcnt=fcnt,
                                perdidos=perdidos, payload_bytes=n_bytes)
        if a is not None:
            self.atual = None
        self._registrar_ocr(linha, t)
        return {"status": "novo", "leitura_id": lid, "leitura": digitos, "rssi": rssi, "fcnt": fcnt}

    def _linha_ocr(self, a: "Leitura | None", lid, t: float, *, achou=None, digitos="", rssi=None,
                   fcnt=None, perdidos="", payload_bytes="", status=None, motivo="recebida") -> dict:
        """Uma linha de transmissao_ocr.csv (uso interno). `a` é a leitura disparada pelo PC, se houver."""
        disparo = a.t_disparo if a is not None else None
        if status is None:
            if "?" in digitos:
                status = "recebida_digito_incerto"
            elif not achou:
                status = "recebida_sem_caixa"
            else:
                status = "recebida"
        linha = {c: "" for c in CAMPOS_OCR}
        linha.update({
            "run_id": self.ex.run_id, "leitura_id": "" if lid is None else lid,
            "distancia_m": "" if self.ex.distancia_m is None else self.ex.distancia_m,
            "rotulo": self.ex.rotulo, "modo": self.ex.modo, "status": status, "motivo_fim": motivo,
            "inicio": self.ex.iso(disparo if disparo is not None else t), "fim": self.ex.iso(t),
            "sf": enlace.SF, "bw_khz": enlace.BW_KHZ, "payload_bytes": payload_bytes,
            "leitura": digitos, "achou_caixa": "" if achou is None else int(achou),
            "digitos_incertos": digitos.count("?") if digitos else "",
            "duplicados": 0, "rssi_dbm": "" if rssi is None else rssi,
            "fcnt": "" if fcnt is None else fcnt, "fcnt_perdidos_antes": perdidos,
        })
        if a is not None:
            linha["leitura_no"] = "" if a.leitura_tx is None else a.leitura_tx
            if a.leitura_tx is not None and digitos:
                linha["leitura_confere"] = int(a.leitura_tx == digitos)
            if a.tx_observado:
                linha.update(tx_tentativas=a.tx_tentativas, tx_ocupado=a.tx_ocupado,
                             tx_falhas=a.tx_falhas)
            if a.t_ocr is not None and disparo is not None:
                linha["t_ocr_s"] = _arred(a.t_ocr - disparo)
        if digitos:   # chegou um frame: o tempo de rádio vem do log do nó (tx) ou do frame (rx)
            if a is not None and a.tx_observado and a.tx_tentativas:
                linha["tempo_radio_s"], linha["tempo_radio_base"] = _arred(a.tx_airtime_ms / 1000), "tx"
            else:
                linha["tempo_radio_s"] = _arred(ar.tempo_no_ar_ms(
                    ar.OVERHEAD_LORAWAN + int(payload_bytes), enlace.SF, enlace.BW_KHZ * 1000) / 1000)
                linha["tempo_radio_base"] = "rx"
            if disparo is not None:
                linha["latencia_s"], linha["latencia_base"] = _arred(t - disparo), "disparo"
        return linha

    def _registrar_ocr(self, linha: dict, t: float) -> None:
        self.resumos_ocr.append(linha)
        self.ex.registrar_leitura_ocr(linha)
        self.ex.evento("leitura_ocr", t, **linha)
        self.ex.contadores["leituras_ocr"] += 1
        self.ex.contadores[f"leituras_ocr_{linha['status']}"] += 1
        lat = linha["latencia_s"]
        self.imprimir(f"[leitura {linha['leitura_id']}] {linha['status']}: {linha['leitura']!r}"
                      + (f"  RSSI={linha['rssi_dbm']} dBm  FCnt={linha['fcnt']}" if linha["fcnt"] != "" else "")
                      + (f", latência {lat:.1f} s" if lat != "" else "")
                      + (f"  [aviso] {linha['fcnt_perdidos_antes']} uplink(s) perdido(s) antes deste (lacuna de FCnt)"
                         if linha["fcnt_perdidos_antes"] else ""))

    def _encerrar_ocr(self, a: "Leitura", motivo: str, t: float) -> dict:
        """Fecha uma leitura OCR disparada pelo PC que não recebeu nenhum uplink."""
        linha = self._linha_ocr(a, a.id, t, status="sem_dados", motivo=motivo)
        self._registrar_ocr(linha, t)
        return linha

    # -- fim de leitura --------------------------------------------------------------------
    def verificar(self, t: float) -> None:
        """Chamar periodicamente: aplica timeouts e fecha leituras que já podem fechar."""
        a = self.atual
        if a is None:
            return
        if a.t_disparo is not None:
            if a.id is None and t - a.t_disparo > self.timeout_foto_s:
                self.encerrar("sem_foto", t)
                return
            if t - a.t_disparo > self.timeout_leitura_s:
                self.encerrar("timeout_leitura", t)
                return
        else:
            ultimo = a.t_ultimo_frame if a.t_ultimo_frame is not None else a.t_abertura
            if ultimo is not None and t - ultimo > self.timeout_inatividade_s:
                self.encerrar("timeout_inatividade", t)
                return
        self._avaliar_fim(t)

    def _avaliar_fim(self, t: float) -> None:
        a = self.atual
        if a is None:
            return
        if a.t_completa is not None:
            if (self.grace_s <= 0 or a.t_envio_concluido is not None
                    or t - a.t_completa >= self.grace_s):
                self.encerrar("completa", t)
        elif a.t_envio_concluido is not None and t - a.t_envio_concluido >= max(self.grace_s, 3.0):
            self.encerrar("tx_concluido", t)

    def encerrar(self, motivo: str, t: float) -> dict | None:
        """Fecha a leitura atual: grava a imagem, a linha do CSV e o evento. Devolve o resumo."""
        a = self.atual
        if a is None:
            return None
        self.atual = None
        if self.fluxo == "ocr" and a.t_disparo is not None:   # leitura OCR sem uplink
            return self._encerrar_ocr(a, motivo, t)
        resumo = self._resumir(a, motivo, t)
        self.resumos.append(resumo)
        self.ex.registrar_envio(resumo)
        self.ex.evento("leitura_encerrada", t, **resumo)
        self.ex.contadores["leituras"] += 1
        self.ex.contadores[f"leituras_{resumo['status']}"] += 1
        pdr = resumo["pdr_leitura"]
        lat = resumo["latencia_s"]
        self.imprimir(
            f"[leitura {a.id}] {resumo['status']} ({motivo}): {resumo['blocos_unicos']}/{resumo['total_blocos']} blocos"
            + (f", PDR da leitura {pdr:.0%}" if pdr != "" else "")
            + (f", latência {lat:.1f} s" if lat != "" else "")
            + (f", faltando {a.faltando}" if a.faltando and len(a.faltando) <= 20 else ""))
        return resumo

    def _salvar_imagem(self, a: Leitura) -> tuple[str, str]:
        """Grava a imagem (completa ou parcial). Devolve (caminho relativo a medicoes/, sha256)."""
        if not self.salvar_imagens or not a.chunks or a.total is None:
            return "", ""
        completa = a.completa
        dados = a.imagem() if completa else a.imagem_parcial()
        nome = f"{self.ex.run_id}_L{a.id:05d}{'' if completa else '_parcial'}.jpg"
        try:
            self.ex.pasta_imagens.mkdir(parents=True, exist_ok=True)
            (self.ex.pasta_imagens / nome).write_bytes(dados)
        except OSError as e:
            self.ex.evento("erro_imagem", leitura_id=a.id, erro=str(e))
            return "", ""
        return f"imagens/{nome}", hashlib.sha256(dados).hexdigest() if completa else ""

    def _resumir(self, a: Leitura, motivo: str, t_fim: float) -> dict:
        completa = a.completa
        valido = jpeg_valido(a.imagem()) if completa else None
        if completa:
            status = "completa" if valido else "completa_jpeg_invalido"
        else:
            status = "incompleta" if a.chunks else "sem_dados"
        arquivo, sha = self._salvar_imagem(a)

        # Blocos enviados: preferir o log do nó; senão estimar pelo FCnt (ver docstring do módulo)
        distintos = a.frames_validos - a.fcnt_repetidos
        if a.tx_observado and a.tx_tentativas:
            enviados, base_env = a.tx_tentativas - a.tx_ocupado, "tx"
        elif a.frames_validos:
            enviados, base_env = distintos + a.fcnt_perdidos, "fcnt"
        else:
            enviados, base_env = None, ""
        pdr_enlace = (distintos / enviados) if enviados else None
        pdr_leitura = (len(a.chunks) / a.total) if a.total else None

        if a.tx_observado and a.tx_tentativas:
            radio_s, base_radio = a.tx_airtime_ms / 1000, "tx"
        elif a.frames_validos:
            radio_s, base_radio = a.airtime_rx_ms / 1000, "rx"
        else:
            radio_s, base_radio = None, ""

        latencia = base_lat = ""
        if a.t_completa is not None:
            if a.t_disparo is not None:
                latencia, base_lat = a.t_completa - a.t_disparo, "disparo"
            elif a.t_primeiro is not None:
                latencia, base_lat = a.t_completa - a.t_primeiro, "primeiro_chunk"
        ref = a.t_disparo
        t_envio = (a.t_ultimo_novo - a.t_primeiro) if a.t_primeiro is not None else None
        rssi = a.rssi
        inicio = a.t_disparo if a.t_disparo is not None else (a.t_primeiro if a.t_primeiro is not None else a.t_abertura)
        fim = a.t_completa if a.t_completa is not None else (a.t_ultimo_frame if a.t_ultimo_frame is not None else t_fim)
        jpeg_bytes = len(a.imagem()) if completa else a.jpeg_bytes_tx
        return {
            "run_id": self.ex.run_id, "leitura_id": "" if a.id is None else a.id,
            "distancia_m": "" if self.ex.distancia_m is None else self.ex.distancia_m,
            "rotulo": self.ex.rotulo, "modo": self.ex.modo, "status": status, "motivo_fim": motivo,
            "inicio": self.ex.iso(inicio), "fim": self.ex.iso(fim),
            "sf": enlace.SF, "bw_khz": enlace.BW_KHZ, "chunk_bytes": enlace.CHUNK_DATA_SIZE,
            "intervalo_envio_s": enlace.INTERVALO_ENVIO_S,
            "jpeg_bytes": "" if jpeg_bytes is None else jpeg_bytes,
            "jpeg_valido": "" if valido is None else int(valido),
            "total_blocos": "" if a.total is None else a.total,
            "blocos_unicos": len(a.chunks),
            "blocos_faltando": ";".join(map(str, a.faltando)),
            "frames_validos": a.frames_validos, "duplicados": a.duplicados,
            "duplicados_divergentes": a.duplicados_divergentes,
            "total_divergente": a.total_divergente, "tamanho_anomalo": a.tamanho_anomalo,
            "blocos_enviados": "" if enviados is None else enviados, "blocos_enviados_base": base_env,
            "pdr_leitura": _arred(pdr_leitura, 4) if pdr_leitura is not None else "",
            "pdr_enlace": _arred(pdr_enlace, 4) if pdr_enlace is not None else "",
            "fcnt_perdidos": a.fcnt_perdidos, "fcnt_repetidos": a.fcnt_repetidos,
            "fcnt_reinicios": a.fcnt_reinicios,
            "rssi_min_dbm": min(rssi) if rssi else "",
            "rssi_medio_dbm": _arred(statistics.fmean(rssi), 1) if rssi else "",
            "rssi_max_dbm": max(rssi) if rssi else "",
            "tempo_radio_s": _arred(radio_s, 3), "tempo_radio_base": base_radio,
            "t_foto_s": _arred(None if ref is None or a.t_foto is None else a.t_foto - ref),
            "t_primeiro_chunk_s": _arred(None if ref is None or a.t_primeiro is None else a.t_primeiro - ref),
            "t_envio_s": _arred(t_envio),
            "latencia_s": _arred(latencia) if latencia != "" else "", "latencia_base": base_lat,
            "tx_tentativas": a.tx_tentativas if a.tx_observado else "",
            "tx_ocupado": a.tx_ocupado if a.tx_observado else "",
            "tx_falhas": a.tx_falhas if a.tx_observado else "",
            "tx_ok_reportado": "" if a.tx_ok_reportado is None else a.tx_ok_reportado,
            "imagem_arquivo": arquivo, "imagem_sha256": sha,
        }


# --- Serial sem bloqueio ---------------------------------------------------------------
def abrir_serial(porta: str, baud: int = 115200):
    """Abre a porta sem resetar a placa (DTR/RTS desligados antes de abrir) e sem bloquear."""
    import serial

    ser = serial.Serial()
    ser.port, ser.baudrate, ser.timeout = porta, baud, 0
    ser.dtr = False
    ser.rts = False
    ser.open()
    ser.reset_input_buffer()
    return ser


class LinhasSerial:
    """Lê uma serial sem bloquear e devolve (instante, linha) assim que cada linha completa chega.

    O instante é tomado logo depois da leitura dos bytes, então o erro é o intervalo entre
    consultas (alguns ms), bem menor que os segundos entre os chunks."""

    def __init__(self, ser, relogio=time.perf_counter):
        self.ser = ser
        self.relogio = relogio
        self._buf = bytearray()

    def ler(self) -> list[tuple[float, str]]:
        n = self.ser.in_waiting
        if not n:
            return []
        dados = self.ser.read(n)
        t = self.relogio()
        self._buf.extend(dados)
        saida = []
        while (i := self._buf.find(b"\n")) >= 0:
            linha = bytes(self._buf[:i])
            del self._buf[:i + 1]
            texto = linha.decode("utf-8", errors="replace").strip()
            if texto:
                saida.append((t, texto))
        if len(self._buf) > 65536:   # lixo sem quebra de linha: não deixa crescer sem limite
            saida.append((t, "[descartado: 64 KB sem fim de linha]"))
            self._buf.clear()
        return saida


# --- Estatísticas ----------------------------------------------------------------------
def estatisticas(resumos: list[dict]) -> list[str]:
    """Linhas de texto com o resumo de uma execução (para imprimir no fim)."""
    n = len(resumos)
    completas = [r for r in resumos if r["status"].startswith("completa")]
    linhas = [f"{n} leitura(s): {len(completas)} completa(s), {n - len(completas)} incompleta(s)/falha(s)"]

    def serie(campo, formato, nome):
        v = sorted(r[campo] for r in resumos if r[campo] != "")
        if v:
            p95 = v[min(len(v) - 1, int(round(0.95 * (len(v) - 1))))]
            linhas.append(f"{nome}: min {v[0]:{formato}}  mediana {statistics.median(v):{formato}}  "
                          f"p95 {p95:{formato}}  max {v[-1]:{formato}}  média {statistics.fmean(v):{formato}}")
    serie("pdr_leitura", ".2f", "PDR da leitura")
    serie("pdr_enlace", ".2f", "PDR do enlace ")
    serie("latencia_s", ".1f", "Latência (s)   ")
    serie("tempo_radio_s", ".2f", "Tempo de rádio (s)")
    if 0 < n < 30:
        linhas.append("Atenção: o critério de pronto da issue pede >= 30 envios.")
    return linhas


def estatisticas_ocr(resumos: list[dict]) -> list[str]:
    """Resumo das leituras do fluxo OCR (linhas de transmissao_ocr.csv)."""
    n = len(resumos)
    recebidas = [r for r in resumos if r["status"] != "sem_dados"]
    linhas = [f"{n} leitura(s) OCR: {len(recebidas)} recebida(s), {n - len(recebidas)} sem uplink"]
    perdidos = sum(r["fcnt_perdidos_antes"] or 0 for r in recebidas)
    if recebidas:
        linhas.append(f"Uplinks perdidos (lacunas de FCnt): {perdidos}; "
                      f"PDR do enlace {len(recebidas) / (len(recebidas) + perdidos):.2f} "
                      "(não vê perdas antes do primeiro nem depois do último uplink)")
        sem_caixa = sum(r["status"] == "recebida_sem_caixa" for r in recebidas)
        incertas = sum(r["status"] == "recebida_digito_incerto" for r in recebidas)
        linhas.append(f"Sem caixa: {sem_caixa}; com dígito incerto ('?'): {incertas}")
        conferem = [r["leitura_confere"] for r in recebidas if r["leitura_confere"] != ""]
        if conferem:
            linhas.append(f"Leitura do PC igual à impressa pelo nó: {sum(conferem)}/{len(conferem)}")
    for campo, formato, nome in (("latencia_s", ".1f", "Latência (s)   "),
                                 ("tempo_radio_s", ".3f", "Tempo de rádio (s)")):
        v = sorted(r[campo] for r in resumos if r[campo] != "")
        if v:
            p95 = v[min(len(v) - 1, int(round(0.95 * (len(v) - 1))))]
            linhas.append(f"{nome}: min {v[0]:{formato}}  mediana {statistics.median(v):{formato}}  "
                          f"p95 {p95:{formato}}  max {v[-1]:{formato}}  média {statistics.fmean(v):{formato}}")
    if 0 < n < 30:
        linhas.append("Atenção: o critério de pronto da issue pede >= 30 envios.")
    return linhas
