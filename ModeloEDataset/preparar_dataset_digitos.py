import os
import csv
import cv2

from digitos_comum import rectify_from_mask, segment_cells, save_digit_crops

DIRETORIO_ATUAL = os.path.dirname(os.path.abspath(__file__))
DIR_IMG = os.path.join(DIRETORIO_ATUAL, "dataset", "images")
DIR_MASK = os.path.join(DIRETORIO_ATUAL, "dataset", "masks")
DIR_OUT = os.path.join(DIRETORIO_ATUAL, "dataset", "digits")
FRAC_DIGITS = 3


def rotulo_esperado(nome_arquivo, n_celulas):
    # id_XXXX_value_<inteiro>_<fracao>.jpg
    sem_ext = os.path.splitext(nome_arquivo)[0]
    partes = sem_ext.split("_value_")
    if len(partes) != 2:
        return None
    inteiro_str, frac_str = partes[1].split("_")
    frac = frac_str.zfill(FRAC_DIGITS)
    largura_inteiro = n_celulas - FRAC_DIGITS
    if largura_inteiro < 1:
        return None
    if len(inteiro_str) > largura_inteiro:
        return None
    inteiro = inteiro_str.zfill(largura_inteiro)
    return inteiro + frac


def main():
    os.makedirs(DIR_OUT, exist_ok=True)
    arquivos = sorted(f for f in os.listdir(DIR_IMG) if f.lower().endswith((".png", ".jpg", ".jpeg")))

    aceitas = 0
    rejeitadas = 0
    motivos = {"mascara_invalida": 0, "segmentacao_falhou": 0, "rotulo_incompativel": 0}
    linhas_relatorio = []
    amostras_preview = {}

    for nome in arquivos:
        caminho_img = os.path.join(DIR_IMG, nome)
        caminho_mask = os.path.join(DIR_MASK, nome)
        if not os.path.exists(caminho_mask):
            continue

        img = cv2.imread(caminho_img)
        mask = cv2.imread(caminho_mask, cv2.IMREAD_GRAYSCALE)
        if img is None or mask is None:
            continue

        strip = rectify_from_mask(img, mask)
        if strip is None:
            rejeitadas += 1
            motivos["mascara_invalida"] += 1
            linhas_relatorio.append([nome, "rejeitada", "mascara_invalida", ""])
            continue

        # so tenta o total de 8 digitos (5 inteiros + 3 fracionarios): tentar
        # varios totais alternativos quando a segmentacao de 8 falha (ex.:
        # um "1" fino demais some da projecao) mostrou-se arriscado -- a
        # amostra as vezes "batia" a contagem com uma hipotese errada de
        # largura do inteiro, rotulando errado de forma sistematica.
        aceite_final = None
        cells = segment_cells(strip, 8)
        if cells is not None:
            rotulo = rotulo_esperado(nome, 8)
            if rotulo is not None and len(rotulo) == 8:
                aceite_final = (cells, rotulo)

        if aceite_final is None:
            rejeitadas += 1
            motivo = "segmentacao_falhou"
            linhas_relatorio.append([nome, "rejeitada", motivo, ""])
            motivos[motivo] += 1
            continue

        cells, rotulo = aceite_final
        prefix = os.path.splitext(nome)[0]
        save_digit_crops(cells, rotulo, DIR_OUT, prefix)
        aceitas += 1
        linhas_relatorio.append([nome, "aceita", "", rotulo])

        for ch, cell in zip(rotulo, cells):
            if ch not in amostras_preview:
                amostras_preview[ch] = cv2.resize(cell, (28, 28))

    relatorio_path = os.path.join(DIRETORIO_ATUAL, "dataset", "digits_report.csv")
    with open(relatorio_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["arquivo", "status", "motivo_rejeicao", "rotulo"])
        w.writerows(linhas_relatorio)

    if amostras_preview:
        digitos_ordenados = sorted(amostras_preview.keys())
        tiles = [amostras_preview[d] for d in digitos_ordenados]
        preview = cv2.hconcat(tiles)
        cv2.imwrite(os.path.join(DIRETORIO_ATUAL, "dataset", "digits_preview.png"), preview)

    total = aceitas + rejeitadas
    print(f"Total de pares imagem/mascara processados: {total}")
    print(f"Aceitas: {aceitas} ({100 * aceitas / max(total, 1):.1f}%)")
    print(f"Rejeitadas: {rejeitadas}")
    for motivo, qtd in motivos.items():
        print(f"  - {motivo}: {qtd}")
    print(f"Relatorio: {relatorio_path}")


if __name__ == "__main__":
    main()
