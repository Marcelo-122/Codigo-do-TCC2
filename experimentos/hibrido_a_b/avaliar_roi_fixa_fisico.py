"""Acurácia da leitura com a ROI fixa nos quadros capturados do hidrômetro físico.

Lê os quadros 160x120 crus de `quadros_160x120.csv` (capturados com `capturar_quadros.py`, câmera parada) com a
ROI gravada pelo calibrador (caixa, número de dígitos, face da roda e realce), sem o modelo de segmentação. É o modo
`roi` do `transmissor_ocr_esp32cam`: o `pipeline_nuvem.entrada_fatia` faz as mesmas contas do firmware (as funções em
C, compiladas no PC, deram as mesmas entradas 28x28, pixel a pixel).

Se a câmera mudou de lugar durante a captura, cada posição tem a sua ROI: `posicoes_camera.csv` diz a partir de que
quadro vale cada JSON (`primeiro_quadro,roi`). Sem esse arquivo, vale `--roi` para todos.

Compara quatro pré-processamentos (fatia inteira sem realce, só a face, só o realce, e o calibrado: face + realce)
nos dois fluxos: borda (o quadro direto) e nuvem (o mesmo quadro depois do JPEG q90, o que o servidor receberia).
Quadros com `?` no rótulo (roda entre dois números) ficam fora das contas.

Ressalvas que o relatório mostra:
- a face e o realce foram escolhidos olhando a leitura ao vivo na calibração; as fotos com a mesma leitura da
  calibração da sua posição (`leitura_no_pc` do JSON) não são teste independente e aparecem separadas;
- os quatro primeiros dígitos deste medidor são sempre 0, então a acurácia por dígito também é dada só para os dois
  últimos e só para a roda das unidades.

Uso (na raiz do repositório, com o .venv desta pasta):
    experimentos/hibrido_a_b/.venv/Scripts/python experimentos/hibrido_a_b/avaliar_roi_fixa_fisico.py
Saídas: resultados/ROI_FIXA_FISICO.md e resultados/roi_fixa_fisico_por_foto.csv (nesta pasta).
"""
import argparse
import csv
import datetime
import hashlib
import json
import math
import sys
from pathlib import Path

import cv2

PASTA = Path(__file__).resolve().parent
RAIZ = PASTA.parents[1]
sys.path.insert(0, str(RAIZ / "ocr"))
import pipeline_nuvem as pn  # noqa: E402

# As quatro variantes usam a face do JSON da posição e realce fixo (0 ou 1); o `realce` do JSON só diz qual delas
# está gravada na placa (marcada "na placa" no relatório).
VARIANTES = ["sem pré-processamento", "só a face", "só o realce", "face + realce"]


def wilson(acertos, n, z=1.96):
    """Intervalo de confiança de 95 % (Wilson) para uma proporção."""
    if n == 0:
        return 0.0, 0.0
    p = acertos / n
    centro = (p + z * z / (2 * n)) / (1 + z * z / n)
    meia = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return max(0.0, centro - meia), min(1.0, centro + meia)


def placar(itens):
    """itens: lista de (lido, real)."""
    return {"n": len(itens),
            "exatas": sum(lido == real for lido, real in itens),
            "dig": sum(sum(a == b for a, b in zip(lido, real)) for lido, real in itens),
            "tot": sum(len(real) for _, real in itens),
            "ult2": sum(sum(a == b for a, b in zip(lido[-2:], real[-2:])) for lido, real in itens),
            "unid": sum(lido[-1] == real[-1] for lido, real in itens)}


def fmt(p):
    if p["n"] == 0:
        return "| — | — | — | — |"
    lo, hi = wilson(p["exatas"], p["n"])
    return (f"| {p['exatas']}/{p['n']} ({100 * p['exatas'] / p['n']:.0f} %; IC 95 % {100 * lo:.0f}–{100 * hi:.0f} %) "
            f"| {p['dig']}/{p['tot']} ({100 * p['dig'] / p['tot']:.0f} %) "
            f"| {p['ult2']}/{2 * p['n']} ({100 * p['ult2'] / (2 * p['n']):.0f} %) "
            f"| {p['unid']}/{p['n']} ({100 * p['unid'] / p['n']:.0f} %) |")


def carregar_rois(manifesto, roi_padrao, arq_posicoes):
    """Lista de (primeiro_quadro, nome do json, dict da ROI), em ordem."""
    if arq_posicoes and Path(arq_posicoes).exists():
        with open(arq_posicoes, encoding="utf-8") as f:
            linhas = sorted(csv.DictReader(f), key=lambda l: l["primeiro_quadro"])
        pares = [(l["primeiro_quadro"], Path(arq_posicoes).parent / l["roi"]) for l in linhas]
    else:
        pares = [("", Path(roi_padrao))]
    return [(primeiro, caminho.name, json.loads(caminho.read_text(encoding="utf-8"))) for primeiro, caminho in pares]


def roi_do_quadro(rois, arquivo):
    nome = Path(arquivo).name
    validos = [r for r in rois if r[0] <= nome]
    return validos[-1] if validos else rois[0]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifesto", default=str(PASTA / "quadros_160x120.csv"))
    ap.add_argument("--roi", default=str(PASTA / "roi_fisico_1.json"), help="ROI de todos, sem posicoes_camera.csv")
    ap.add_argument("--posicoes", default=str(PASTA / "posicoes_camera.csv"))
    a = ap.parse_args()
    sys.stdout.reconfigure(errors="replace")

    rois = carregar_rois(a.manifesto, a.roi, a.posicoes)
    with open(a.manifesto, encoding="utf-8") as f:
        linhas = list(csv.DictReader(f))
    base = Path(a.manifesto).parent
    leitor = pn.LeitorB()

    por_foto = []
    for l in linhas:
        _, nome_roi, roi = roi_do_quadro(rois, l["arquivo"])
        caixa, n = tuple(roi["caixa"]), int(roi["n_digitos"])
        face, realce = tuple(roi.get("face_pct", (0, 100))), int(roi.get("realce", 0))
        variantes = dict(zip(VARIANTES, [(pn.FACE_PADRAO, 0), (face, 0), (pn.FACE_PADRAO, 1), (face, 1)]))
        na_placa = VARIANTES[3] if realce else VARIANTES[1]
        quadro = cv2.imread(str(base / l["arquivo"]), cv2.IMREAD_GRAYSCALE)
        independente = l["rotulo"] != roi.get("leitura_no_pc", "")
        for fluxo in ("borda", "nuvem"):
            q = quadro if fluxo == "borda" else pn.transmitir_como_jpeg(quadro)[0]
            for nome, (fc, rc) in variantes.items():
                lido = leitor.ler(q, n, caixa=caixa, face=fc, realce=rc)["leitura"]
                por_foto.append({"arquivo": l["arquivo"], "rotulo": l["rotulo"], "luz": l.get("luz", ""), "roi": nome_roi,
                                 "independente": int(independente), "fluxo": fluxo, "variante": nome,
                                 "na_placa": int(nome == na_placa), "lido": lido,
                                 "exato": int(lido == l["rotulo"]) if "?" not in l["rotulo"] else ""})

    pasta_res = PASTA / "resultados"
    pasta_res.mkdir(exist_ok=True)
    with open(pasta_res / "roi_fixa_fisico_por_foto.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(por_foto[0]))
        w.writeheader()
        w.writerows(por_foto)

    def sel(fluxo, variante, filtro=lambda r: True):
        return [(r["lido"], r["rotulo"]) for r in por_foto
                if r["fluxo"] == fluxo and r["variante"] == variante and "?" not in r["rotulo"] and filtro(r)]

    rotulados = [l for l in linhas if "?" not in l["rotulo"]]
    distintas = sorted({l["rotulo"] for l in rotulados})
    hash_modelo = hashlib.sha256(Path(pn.MODELO_DIGITO).read_bytes()).hexdigest()[:12]
    cab = "| Pré-processamento | Leituras exatas | Dígitos | Dois últimos dígitos | Roda das unidades |"
    md = [f"# ROI fixa no hidrômetro físico ({len(rotulados)} quadros rotulados)", "",
          f"Gerado por `avaliar_roi_fixa_fisico.py` em {datetime.date.today().isoformat()}. Medidor `fisico_1`, câmera "
          f"parada, quadros 160x120 crus de `{Path(a.manifesto).name}`: {len(linhas)} quadros, {len(linhas) - len(rotulados)} "
          f"com `?` fora das contas, {len(distintas)} leituras distintas de `{distintas[0]}` a `{distintas[-1]}`, luz "
          f"{', '.join(sorted({l.get('luz', '') for l in linhas}))}. Classificador `modelo_digito.tflite` (sha256 "
          f"{hash_modelo}), INT8, sem segmentação, mesmas contas do `transmissor_ocr_esp32cam` em modo `roi`.", "",
          "| Posição da câmera | A partir de | ROI | Caixa | Face | Realce na placa | Calibrada em | Quadros rotulados |",
          "|---|---|---|---|---|---|---|---|"]
    for primeiro, nome_roi, roi in rois:
        nq = len({r["arquivo"] for r in por_foto if r["roi"] == nome_roi and "?" not in r["rotulo"]})
        md.append(f"| {chr(65 + rois.index((primeiro, nome_roi, roi)))} | {primeiro or '—'} | `{nome_roi}` | "
                  f"`{','.join(map(str, roi['caixa']))}` | {roi.get('face_pct', [0, 100])[0]}-"
                  f"{roi.get('face_pct', [0, 100])[1]} % | {roi.get('realce', 0)} | `{roi.get('leitura_no_pc', '')}` | {nq} |")
    md.append("")
    for fluxo in ("borda", "nuvem"):
        md += [f"## Fluxo {fluxo}" + (" (quadro direto, como na placa)" if fluxo == "borda" else " (quadro depois do JPEG q90)"),
               "", cab, "|---|---|---|---|---|"]
        md += [f"| {v} " + fmt(placar(sel(fluxo, v))) for v in VARIANTES]
        md.append("")
    md += ["## Teste independente (fluxo borda)", "",
           "Sem as fotos cuja leitura é a mesma usada na calibração da sua posição (a face e o realce foram escolhidos "
           "olhando essa leitura).", "", cab, "|---|---|---|---|---|"]
    md += [f"| {v} " + fmt(placar(sel("borda", v, lambda r: r["independente"] == 1))) for v in VARIANTES]
    md += ["", "## Por posição da câmera (fluxo borda, configuração gravada na placa)", "",
           "| Posição " + cab[19:], "|---|---|---|---|---|"]
    for primeiro, nome_roi, roi in rois:
        md.append(f"| {chr(65 + [r[1] for r in rois].index(nome_roi))} (`{nome_roi}`) "
                  + fmt(placar([(r["lido"], r["rotulo"]) for r in por_foto if r["fluxo"] == "borda" and r["na_placa"]
                                and r["roi"] == nome_roi and "?" not in r["rotulo"]])))
    erros = [r for r in por_foto if r["fluxo"] == "borda" and r["na_placa"] and r["exato"] == 0]
    md += ["", "## Erros (fluxo borda, configuração gravada na placa)", "", "| Quadro | Rótulo | Lido |", "|---|---|---|"]
    md += [f"| {Path(r['arquivo']).name} | {r['rotulo']} | {r['lido']} |" for r in erros] or ["| — | — | — |"]
    md += ["", "Detalhe de cada quadro, fluxo e variante em `roi_fixa_fisico_por_foto.csv`.", "",
           "**Limites:** um medidor e uma iluminação; os quatro primeiros dígitos são sempre 0 (por isso as colunas dos "
           "dois últimos e da roda das unidades); a face e o realce foram escolhidos neste mesmo medidor. O resultado mede "
           "a leitura com a câmera fixa e calibrada, não a generalização para outro hidrômetro (nas 21 fotos de outros "
           "medidores de `dados/teste/`, a mesma face e o realce pioraram a leitura)."]
    (pasta_res / "ROI_FIXA_FISICO.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    main()
