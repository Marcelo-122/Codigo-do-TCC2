"""Refaz as imagens de uma execucao do reconstrutor.py a partir de logs/<execucao>/serial_rx.txt.

O serial_rx.txt guarda todos os frames do receptor com o DevAddr mascarado (XXXXXXXX). Este script
poe o DevAddr de volta (LORA_DEV_ADDR do .env), descriptografa com LORA_APP_SKEY, junta os chunks
por id de leitura e grava as imagens completas em medicoes/imagens/. Quando o transmissao.csv tem
a leitura, confere o SHA-256 da imagem refeita com o registrado (prova que e a mesma imagem).

Uso (na raiz do projeto, com o venv ativo):
  python medicoes/recuperar_imagens.py 20261027_135830_bancada-imagem
Nao sobrescreve uma imagem que ja existe (use --sobrescrever).
"""
import argparse
import csv
import hashlib
import os
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(AQUI, ".."))  # enlace.py e config.py ficam na raiz

import enlace  # noqa: E402


def ler_frames(caminho, dev_addr_frame_hex):
    """Frames (bytes) do serial_rx.txt, com o DevAddr desmascarado."""
    with open(caminho, encoding="utf-8") as f:
        for linha in f:
            m = enlace.LINE_RE.search(linha.replace("XXXXXXXX", dev_addr_frame_hex))
            if m:
                yield bytes.fromhex(m.group(1))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("execucao", help="nome da pasta em medicoes/logs/, ex.: 20261027_135830_bancada-imagem")
    p.add_argument("--sobrescrever", action="store_true")
    args = p.parse_args()

    import config

    app_skey = config.require_hex("LORA_APP_SKEY", 16)
    dev_addr = bytes.fromhex(config.require("LORA_DEV_ADDR"))
    dev_addr_frame = dev_addr[::-1].hex().upper()  # no frame o DevAddr vai em little-endian

    pasta_log = os.path.join(AQUI, "logs", args.execucao)
    por_id = {}
    for raw in ler_frames(os.path.join(pasta_log, "serial_rx.txt"), dev_addr_frame):
        try:
            info = enlace.parse_uplink(raw, app_skey, dev_addr)
            if info["fport"] == enlace.FPORT_LEITURA:
                continue
            leitura_id, idx, total, dados = enlace.parse_chunk(info["payload"])
        except ValueError:
            continue
        reg = por_id.setdefault(leitura_id, {"totais": {}, "chunks": {}})
        reg["totais"][total] = reg["totais"].get(total, 0) + 1
        reg["chunks"].setdefault(idx, dados)

    hashes = {}
    csv_medicoes = os.path.join(AQUI, "transmissao.csv")
    if os.path.exists(csv_medicoes):
        with open(csv_medicoes, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if r["run_id"] == args.execucao and r["status"] == "completa":
                    hashes[int(r["leitura_id"])] = r["imagem_sha256"]

    pasta_img = os.path.join(AQUI, "imagens")
    os.makedirs(pasta_img, exist_ok=True)
    feitas = 0
    for leitura_id, reg in sorted(por_id.items()):
        total = max(reg["totais"], key=reg["totais"].get)  # o total mais repetido (frames com bits errados divergem)
        faltam = [i for i in range(total) if i not in reg["chunks"]]
        if faltam:
            print(f"leitura {leitura_id}: incompleta ({total - len(faltam)}/{total}), faltam {faltam}")
            continue
        imagem = b"".join(reg["chunks"][i] for i in range(total))
        sha = hashlib.sha256(imagem).hexdigest()
        nome = os.path.join(pasta_img, f"{args.execucao}_L{leitura_id:05d}.jpg")
        esperado = hashes.get(leitura_id)
        confere = "sem hash no CSV" if esperado is None else ("SHA-256 confere" if sha == esperado else "SHA-256 DIFERENTE")
        if os.path.exists(nome) and not args.sobrescrever:
            print(f"leitura {leitura_id}: {nome} ja existe, mantido ({confere})")
            continue
        with open(nome, "wb") as f:
            f.write(imagem)
        feitas += 1
        print(f"leitura {leitura_id}: {len(imagem)} bytes -> {os.path.relpath(nome, AQUI)} ({confere})")
    print(f"{feitas} imagem(ns) gravada(s).")


if __name__ == "__main__":
    main()
