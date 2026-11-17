"""Lê o conjunto de hidrômetros físicos (`dados/teste/`) com a ROI marcada à mão, sem o modelo de segmentação.

É o cenário da instalação com a câmera fixa: a inclinação da fileira e a janela dos dígitos são calibradas uma vez
(`dados/teste/roi_manual.csv`) e a leitura usa só as fatias iguais e o classificador INT8, com a mesma lógica do
firmware (`LeitorB.ler` com a caixa dada). Complementa o `avaliar_pipeline.py --conjunto fisico`, em que a caixa vem
do modelo de segmentação.

`roi_manual.csv`, uma linha por foto:
  angulo_graus  rotação aplicada ao quadro 160×120 em torno do centro antes de ler (convenção do
                `cv2.getRotationMatrix2D`: positivo = anti-horário), a mesma de `pipeline_nuvem.alinhar`;
  caixa         x0,y0,x1,y1 da janela dos dígitos no quadro JÁ girado, do primeiro ao último rolete;
  fundo         `claro` (dígitos escuros) ou `escuro` (dígitos claros), marcado olhando a foto, como a caixa;
  origem_angulo `hough` (o ângulo de `estimar_inclinacao` deixou a fileira reta) ou `manual` (corrigido a olho).
As caixas foram marcadas pela geometria (bordas da janela e centros dos roletes, com as fatias caindo entre eles),
olhando o quadro ampliado com grade, antes de rodar este script; não foram ajustadas pela leitura.

Fluxos, como no `avaliar_pipeline.py`: borda = quadro direto; nuvem = o mesmo quadro depois do JPEG q90 (o servidor
gira o quadro remontado). A rotação existe no servidor (`pipeline_nuvem.alinhar`); no firmware não está
implementada, então a linha `borda` supõe essa rotação com ângulo fixo. Cada fluxo é lido com fatias iguais e com a
votação entre 5 caixas deslocadas (`avaliar_roi_fixa.py`) e, na variante `_polaridade`, com fatias iguais e a
janela invertida (255 - pixel) nas fotos de fundo escuro. O classificador foi treinado quase só com dígitos escuros
em fundo claro; a polaridade, como o número de roletes, é uma propriedade do medidor conhecida na instalação.

Saídas (na raiz do repositório):
  medicoes/ocr_teste.csv                                       linhas dos conjuntos `fisico_roi_manual`,
                                                               `fisico_roi_manual_votacao` e
                                                               `fisico_roi_manual_polaridade`;
  medicoes/ocr_teste_por_imagem_fisico_roi_manual.csv          uma linha por (foto, fluxo, variante);
  dados/teste/conferencia_roi_manual.png                       cada quadro girado com a caixa, as fatias e o
                                                               dígito lido (verde certo, vermelho errado), fluxo
                                                               nuvem, variante `_polaridade`.

Uso:  python ocr/avaliar_roi_manual.py
"""
import csv
import datetime
import os
import sys

import cv2
import numpy as np

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
from avaliar_pipeline import CAMPOS_RESUMO, SAIDA_RESUMO, _hash_arquivo, distancia_edicao  # noqa: E402
from avaliar_roi_fixa import DESLOCAMENTOS  # noqa: E402
from pipeline_nuvem import (MODELO_DIGITO, MODELO_SEGMENTACAO, LeitorB, alinhar, para_quadro_camera,  # noqa: E402
                            transmitir_como_jpeg)

RAIZ = os.path.dirname(AQUI)
DIR_TESTE = os.path.join(RAIZ, "dados", "teste")
SAIDA_POR_IMAGEM = os.path.join(RAIZ, "medicoes", "ocr_teste_por_imagem_fisico_roi_manual.csv")
SAIDA_FOLHA = os.path.join(DIR_TESTE, "conferencia_roi_manual.png")
# (conjunto, deslocamentos da votação, inverte a janela de fundo escuro)
VARIANTES = (("fisico_roi_manual", ((0, 0),), False), ("fisico_roi_manual_votacao", DESLOCAMENTOS, False),
             ("fisico_roi_manual_polaridade", ((0, 0),), True))


def carregar():
    with open(os.path.join(DIR_TESTE, "rotulos.csv"), encoding="utf-8") as f:
        rotulos = {l["arquivo"]: l for l in csv.DictReader(f) if l["arquivo"].strip()}
    with open(os.path.join(DIR_TESTE, "roi_manual.csv"), encoding="utf-8") as f:
        rois = list(csv.DictReader(f))
    faltam = set(rotulos) - {r["arquivo"] for r in rois}
    if faltam:
        sys.exit(f"sem ROI em roi_manual.csv: {sorted(faltam)}")
    return [{"arquivo": r["arquivo"], "leitura": rotulos[r["arquivo"]]["leitura"].strip(),
             "n": int(rotulos[r["arquivo"]]["n_digitos"]), "angulo": float(r["angulo_graus"]),
             "caixa": tuple(int(v) for v in r["caixa"].split(",")), "escuro": r["fundo"].strip() == "escuro"}
            for r in rois]


def desenhar(quadro, caixa, n, lido, real, escala=3):
    img = cv2.cvtColor(cv2.resize(quadro, None, fx=escala, fy=escala, interpolation=cv2.INTER_NEAREST),
                       cv2.COLOR_GRAY2BGR)
    x0, y0, x1, y1 = caixa
    cv2.rectangle(img, (x0 * escala, y0 * escala), (x1 * escala, y1 * escala), (0, 220, 0), 1)
    for i in range(n):
        sx0, sx1 = x0 + ((x1 - x0) * i) // n, x0 + ((x1 - x0) * (i + 1)) // n
        if i:
            cv2.line(img, (sx0 * escala, y0 * escala), (sx0 * escala, y1 * escala), (0, 220, 0), 1)
        cor = (0, 170, 0) if lido[i] == real[i] else (0, 0, 230)
        cv2.putText(img, lido[i], ((sx0 + sx1) // 2 * escala - 6, min(y1 * escala + 22, img.shape[0] - 4)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, cor, 2)
    return img


def main():
    itens = carregar()
    leitor = LeitorB()
    por_imagem, folhas = [], []
    for it in itens:
        bruto = cv2.imdecode(np.fromfile(os.path.join(DIR_TESTE, "imagens", it["arquivo"]), np.uint8), cv2.IMREAD_COLOR)
        quadro = para_quadro_camera(bruto)
        for fluxo in ("borda", "nuvem"):
            entrada = quadro if fluxo == "borda" else transmitir_como_jpeg(quadro)[0]
            girado, _ = alinhar(entrada, it["angulo"])
            for variante, desl, inverte in VARIANTES:
                q = 255 - girado if inverte and it["escuro"] else girado
                lido = leitor.ler(q, it["n"], caixa=it["caixa"], deslocamentos=desl)["leitura"]
                real = it["leitura"]
                por_imagem.append({"conjunto": variante, "arquivo": it["arquivo"], "fluxo": fluxo,
                                   "leitura_real": real, "leitura_lida": lido, "exato": int(lido == real),
                                   "digitos_certos": sum(a == b for a, b in zip(real, lido)), "n_digitos": it["n"],
                                   "erros_edicao": distancia_edicao(real, lido), "angulo_graus": it["angulo"],
                                   "fundo": "escuro" if it["escuro"] else "claro",
                                   "caixa": "{},{},{},{}".format(*it["caixa"])})
                if fluxo == "nuvem" and variante == "fisico_roi_manual_polaridade":
                    img = desenhar(girado, it["caixa"], it["n"], lido, real)
                    cv2.putText(img, f"{it['arquivo']} real {real}", (4, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
                    folhas.append(cv2.copyMakeBorder(img, 2, 2, 2, 2, cv2.BORDER_CONSTANT, value=(0, 0, 0)))

    modelos = (_hash_arquivo(MODELO_SEGMENTACAO), _hash_arquivo(MODELO_DIGITO))
    resumo = []
    for variante, _, _ in VARIANTES:
        for fluxo in ("borda", "nuvem"):
            ls = [l for l in por_imagem if l["conjunto"] == variante and l["fluxo"] == fluxo]
            exatas = sum(l["exato"] for l in ls)
            dig_ok, dig_tot = sum(l["digitos_certos"] for l in ls), sum(l["n_digitos"] for l in ls)
            resumo.append({
                "conjunto": variante, "origem": "fisico", "fluxo": fluxo, "n_imagens": len(ls),
                "leituras_exatas": exatas, "taxa_leitura_exata": round(exatas / len(ls), 4),
                "digitos_certos": dig_ok, "digitos_total": dig_tot, "acuracia_digito": round(dig_ok / dig_tot, 4),
                "cer": round(sum(l["erros_edicao"] for l in ls) / dig_tot, 4), "n_com_caixa_real": len(ls),
                "dice_mascara": "", "iou_mascara": "", "iou_caixa": "", "sem_caixa_prevista": "",
                "modelo_segmentacao": modelos[0], "modelo_digito": modelos[1],
                "data": datetime.date.today().isoformat(),
            })
            print(f"{variante} {fluxo}: leitura exata {exatas}/{len(ls)} ({exatas / len(ls):.0%}), "
                  f"dígitos {dig_ok}/{dig_tot} ({dig_ok / dig_tot:.1%}), CER {resumo[-1]['cer']}")

    with open(SAIDA_POR_IMAGEM, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(por_imagem[0].keys()))
        w.writeheader()
        w.writerows(por_imagem)
    existentes = []
    if os.path.exists(SAIDA_RESUMO):
        with open(SAIDA_RESUMO, encoding="utf-8") as f:
            existentes = [l for l in csv.DictReader(f) if l["conjunto"] not in {v[0] for v in VARIANTES}]
    with open(SAIDA_RESUMO, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CAMPOS_RESUMO)
        w.writeheader()
        w.writerows(existentes + resumo)
    while len(folhas) % 4:
        folhas.append(np.zeros_like(folhas[0]))
    cv2.imencode(".png", np.vstack([np.hstack(folhas[i:i + 4]) for i in range(0, len(folhas), 4)]))[1].tofile(SAIDA_FOLHA)
    print(f"gravado em {os.path.relpath(SAIDA_POR_IMAGEM, RAIZ)}, {os.path.relpath(SAIDA_RESUMO, RAIZ)} "
          f"e {os.path.relpath(SAIDA_FOLHA, RAIZ)}")


if __name__ == "__main__":
    main()
