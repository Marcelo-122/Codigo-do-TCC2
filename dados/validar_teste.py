"""Confere o conjunto de teste de hidrômetro FÍSICO (`dados/teste/`) antes de avaliar o pipeline.

Falha (código de saída 1) se faltar algo do critério de pronto da issue ou se o conjunto não for confiável:

  - `rotulos.csv` com as colunas esperadas, uma linha por foto, todas com o arquivo em `imagens/`;
  - rótulo só com dígitos e do tamanho de `n_digitos`; `origem` igual a `fisico` (foto de monitor não vale);
  - pelo menos 30 fotos, com pelo menos 3 iluminações e 3 ângulos distintos (as colunas `iluminacao` e `angulo`);
  - nenhuma foto repetida (mesmo conteúdo) e nenhuma foto que também esteja nos dados de treino/ajuste
    (`ModeloEDataset/Imagens`, `ModeloEDataset/Imagens_2`, `test_images`, `ocr/teste_comum/imagens`).

Avisa (sem falhar) se faltar a caixa da janela em alguma foto: sem ela não há Dice/IoU para aquela foto.

Uso (na raiz do repositório):  python dados/validar_teste.py
"""
import csv
import hashlib
import os
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)
DIR_TESTE = os.path.join(AQUI, "teste")
MINIMO_FOTOS = 30
MINIMO_VARIACOES = 3
COLUNAS = ["arquivo", "leitura", "n_digitos", "medidor", "origem", "iluminacao", "angulo", "centro_y", "caixa",
           "observacao"]
# pastas de fotos que já foram usadas para treinar, ajustar ou testar outra coisa
PASTAS_USADAS = [("ModeloEDataset", "Imagens"), ("ModeloEDataset", "Imagens_2"), ("test_images",),
                 ("ocr", "teste_comum", "imagens")]
EXTENSOES = (".jpg", ".jpeg", ".png")


def sha(caminho):
    with open(caminho, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def hashes_usados():
    usados = {}
    for partes in PASTAS_USADAS:
        base = os.path.join(RAIZ, *partes)
        for pasta, _, arquivos in os.walk(base):
            for nome in arquivos:
                if nome.lower().endswith(EXTENSOES):
                    usados.setdefault(sha(os.path.join(pasta, nome)), os.path.relpath(os.path.join(pasta, nome), RAIZ))
    return usados


def main():
    erros, avisos = [], []
    with open(os.path.join(DIR_TESTE, "rotulos.csv"), encoding="utf-8") as f:
        leitor = csv.DictReader(f)
        if leitor.fieldnames != COLUNAS:
            sys.exit(f"colunas de rotulos.csv: {leitor.fieldnames}; esperado: {COLUNAS}")
        linhas = [l for l in leitor if (l["arquivo"] or "").strip()]

    vistos, usados = {}, hashes_usados()
    for l in linhas:
        nome = l["arquivo"].strip()
        caminho = os.path.join(DIR_TESTE, "imagens", nome)
        if not os.path.isfile(caminho):
            erros.append(f"{nome}: arquivo não encontrado em dados/teste/imagens/")
            continue
        if not l["leitura"].isdigit() or len(l["leitura"]) != int(l["n_digitos"] or -1):
            erros.append(f"{nome}: rótulo {l['leitura']!r} não tem {l['n_digitos']!r} dígitos")
        if l["origem"].strip() != "fisico":
            erros.append(f"{nome}: origem deve ser 'fisico' (veio {l['origem']!r}); foto de monitor não entra aqui")
        if not l["caixa"].strip():
            avisos.append(f"{nome}: sem `caixa` (x0,y0,x1,y1 no quadro 160x120); fica de fora do Dice/IoU")
        h = sha(caminho)
        if h in vistos:
            erros.append(f"{nome}: mesmo conteúdo de {vistos[h]}")
        vistos.setdefault(h, nome)
        if h in usados:
            erros.append(f"{nome}: é a mesma foto de {usados[h]} (já usada em treino ou em outro teste)")

    if len(linhas) < MINIMO_FOTOS:
        erros.append(f"só {len(linhas)} fotos; o mínimo é {MINIMO_FOTOS}")
    for coluna in ("iluminacao", "angulo"):
        valores = {l[coluna].strip() for l in linhas if l[coluna].strip()}
        if len(valores) < MINIMO_VARIACOES:
            erros.append(f"coluna {coluna}: {len(valores)} valores distintos; o mínimo é {MINIMO_VARIACOES}")

    for a in avisos:
        print("aviso:", a)
    for e in erros:
        print("ERRO:", e)
    print(f"{len(linhas)} fotos, {len({l['leitura'] for l in linhas})} leituras distintas, "
          f"{len(avisos)} avisos, {len(erros)} erros")
    sys.exit(1 if erros else 0)


if __name__ == "__main__":
    main()
