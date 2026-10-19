"""
config.py
Configuração compartilhada pelos scripts: lê o arquivo .env (CHAVE=VALOR) da
raiz do repositório e expõe helpers para ler variáveis.

Chaves, endereços e portas seriais NÃO ficam no código. Copie .env.example
para .env e preencha com os valores da sua máquina. O .env está no .gitignore.
Variáveis já definidas no ambiente têm prioridade sobre o .env.
"""

import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent


def _carregar_env():
    """Lê um .env simples (CHAVE=VALOR, sem comentário na mesma linha do valor)."""
    arquivo = RAIZ / ".env"
    if not arquivo.is_file():
        return
    # utf-8-sig: tolera o BOM que alguns editores do Windows gravam
    for linha in arquivo.read_text(encoding="utf-8-sig").splitlines():
        linha = linha.strip()
        if linha and not linha.startswith("#") and "=" in linha:
            chave, valor = linha.split("=", 1)
            os.environ.setdefault(chave.strip(), valor.strip().strip("\"'"))


_carregar_env()


def get(nome, padrao=None):
    """Valor da variável, ou `padrao` se estiver ausente ou vazia."""
    valor = os.environ.get(nome, "").strip()
    return valor if valor else padrao


def require(nome):
    """Valor da variável; encerra o programa com uma mensagem clara se faltar."""
    valor = get(nome)
    if valor is None:
        sys.exit(f"Variável {nome} não configurada: defina no .env (veja .env.example).")
    return valor


def require_hex(nome, n_bytes):
    """Como require(), mas converte de hex e confere o tamanho em bytes."""
    texto = require(nome)
    try:
        dados = bytes.fromhex(texto)
    except ValueError:
        sys.exit(f"{nome} no .env não é hexadecimal válido.")
    if len(dados) != n_bytes:
        sys.exit(f"{nome} no .env deve ter {n_bytes} bytes ({2 * n_bytes} caracteres hex).")
    return dados
