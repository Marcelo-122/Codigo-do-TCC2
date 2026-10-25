"""
scripts/download_datasets.py
Baixa (ou orienta o download de) os datasets públicos usados no TCC e os coloca
nas pastas que os scripts de treino esperam. Os datasets NÃO ficam no Git.

Uso:
    python scripts/download_datasets.py --listar            # fontes e licenças
    python scripts/download_datasets.py                     # baixa tudo que for automático
    python scripts/download_datasets.py --somente digitos   # só um dataset
    python scripts/download_datasets.py --forcar            # sobrescreve destinos já preenchidos

Requisitos para os datasets do Kaggle:
    pip install kaggle
    e credenciais do Kaggle (https://www.kaggle.com/settings/api, "Generate New Token"):
    variável KAGGLE_API_TOKEN (no ambiente ou no .env, veja .env.example) ou o login
    `kaggle auth login`.

O destino depende da branch: só são preenchidas as pastas de módulo que existem
no checkout atual (legado/ocr_cloud/, TreinoEModelosOCRNaBorda/, ModeloEDataset/).
"""

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
import config  # noqa: E402,F401  (carrega o .env, inclusive KAGGLE_* se definidos)

DATASETS = {
    "toloka": {
        "nome": "Yandex.Toloka Water Meters Dataset (autor: Kucev Roman)",
        "fonte": "https://www.kaggle.com/datasets/tapakah68/yandextoloka-water-meters-dataset",
        "kaggle": "tapakah68/yandextoloka-water-meters-dataset",
        "licenca": "CC BY-NC-ND 4.0 (segundo os metadados do Kaggle; confirme na página). ~1 GB",
        "usado_por": "detector de visor e dataset de dígitos (BDM.py, treinamento-detector.py, "
                     "gerar_blackout.py, preparar_dataset_digitos.py)",
        # (pasta a procurar dentro do download, destino relativo à raiz do repo)
        "pastas": [
            ("images", "TreinoEModelosOCRNaBorda/dataset/images"),
            ("masks", "TreinoEModelosOCRNaBorda/dataset/masks"),
            ("images", "ModeloEDataset/dataset/images"),
            ("masks", "ModeloEDataset/dataset/masks"),
        ],
    },
    "digitos": {
        "nome": "Digits 0-9 (autor: Aquib Iqbal)",
        "fonte": "https://www.kaggle.com/datasets/aquibiqbal/digits-09",
        "kaggle": "aquibiqbal/digits-09",
        "licenca": "ver a página do dataset no Kaggle antes de redistribuir",
        "usado_por": "legado/ocr_cloud/src/train_model_ocr_cloud.py e gerador_sintetico.py",
        # pasta com as subpastas 0..9
        "pastas": [
            ("<digitos>", "legado/ocr_cloud/num_dataset"),
            ("<digitos>", "TreinoEModelosOCRNaBorda/dataset/num"),
        ],
    },
    "dryad": {
        "nome": "Word-Wheel Water Meter Dataset (Zhao et al., Scientific Data 13, 479, 2026)",
        "fonte": "https://doi.org/10.5061/dryad.7d7wm3860",
        "kaggle": None,
        "licenca": "CC BY-NC-ND 4.0 (uso não comercial, sem obras derivadas)",
        "usado_por": "ModeloEDataset/preparar_dataset_dryad.py (2,8 GB)",
        "manual": (
            "Download manual (o Dryad exige o navegador):\n"
            "  1. Abra https://doi.org/10.5061/dryad.7d7wm3860 e baixe o dataset.\n"
            "  2. Extraia em ModeloEDataset/dataset/Word-Wheel_Water_Meter_Dataset/ de modo que exista\n"
            "     ModeloEDataset/dataset/Word-Wheel_Water_Meter_Dataset/Word-Wheel_Water_Meter_Dataset/recognition/\n"
            "  3. Cite o artigo e respeite a licença: não redistribua versões adaptadas dos dados."
        ),
        "verificar": "ModeloEDataset/dataset/Word-Wheel_Water_Meter_Dataset/Word-Wheel_Water_Meter_Dataset/recognition",
    },
}

GERADOS = (
    "Conjuntos gerados a partir dos de cima (não baixe, gere):\n"
    "  python TreinoEModelosOCRNaBorda/gerador_sintetico.py   -> dataset/visores_sinteticos\n"
    "  python TreinoEModelosOCRNaBorda/gerar_blackout.py      -> dataset/visores_blackout"
)


def listar():
    for chave, d in DATASETS.items():
        print(f"[{chave}] {d['nome']}")
        print(f"    fonte:    {d['fonte']}")
        print(f"    licença:  {d['licenca']}")
        print(f"    usado em: {d['usado_por']}")
    print("\n" + GERADOS)


def achar_pasta(raiz, nome):
    """Primeira pasta chamada `nome` dentro de `raiz` (a mais rasa), ou None."""
    candidatas = [p for p in raiz.rglob(nome) if p.is_dir() and any(p.iterdir())]
    return min(candidatas, key=lambda p: len(p.parts)) if candidatas else None


def achar_pasta_digitos(raiz):
    """Primeira pasta que contém subpastas 0..9 (uma por classe), ou None."""
    classes = {str(i) for i in range(10)}
    candidatas = [p for p in [raiz, *raiz.rglob("*")]
                  if p.is_dir() and classes <= {c.name for c in p.iterdir() if c.is_dir()}]
    return min(candidatas, key=lambda p: len(p.parts)) if candidatas else None


def baixar_kaggle(slug, destino):
    try:
        from kaggle.api.kaggle_api_extended import KaggleApi
    except ImportError:
        sys.exit("Instale o pacote do Kaggle: pip install kaggle")
    except Exception as e:  # versões antigas autenticam já no import
        sys.exit(f"Credenciais do Kaggle ausentes ou inválidas: {e}")
    api = KaggleApi()
    try:
        api.authenticate()
    except Exception as e:
        sys.exit(f"Credenciais do Kaggle ausentes ou inválidas ({e}). "
                 "Use ~/.kaggle/kaggle.json ou KAGGLE_USERNAME/KAGGLE_KEY no .env.")
    print(f"  baixando {slug} ...")
    api.dataset_download_files(slug, path=str(destino), unzip=True, quiet=False)


def pendentes(pastas, forcar):
    """Destinos deste checkout que ainda precisam ser preenchidos."""
    saida = []
    for procurar, destino_rel in pastas:
        if not (RAIZ / destino_rel.split("/")[0]).is_dir():
            continue  # esta branch não tem esse módulo
        destino = RAIZ / destino_rel
        if forcar or not (destino.is_dir() and any(destino.iterdir())):
            saida.append((procurar, destino_rel))
    return saida


def preencher(origem_raiz, pastas, forcar):
    for procurar, destino_rel in pastas:
        modulo = destino_rel.split("/")[0]
        if not (RAIZ / modulo).is_dir():
            continue  # esta branch não tem esse módulo
        destino = RAIZ / destino_rel
        if destino.is_dir() and any(destino.iterdir()) and not forcar:
            print(f"  já existe, pulando: {destino_rel} (use --forcar para sobrescrever)")
            continue
        origem = achar_pasta_digitos(origem_raiz) if procurar == "<digitos>" \
            else achar_pasta(origem_raiz, procurar)
        if origem is None:
            print(f"  AVISO: não achei '{procurar}' no download; copie para {destino_rel} manualmente.")
            continue
        destino.mkdir(parents=True, exist_ok=True)
        shutil.copytree(origem, destino, dirs_exist_ok=True)
        print(f"  ok: {destino_rel}")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--listar", action="store_true", help="mostra fontes e licenças e sai")
    p.add_argument("--somente", choices=DATASETS, help="processa apenas este dataset")
    p.add_argument("--forcar", action="store_true", help="sobrescreve destinos já preenchidos")
    args = p.parse_args()

    if args.listar:
        listar()
        return

    for chave, d in DATASETS.items():
        if args.somente and args.somente != chave:
            continue
        print(f"\n== {d['nome']}\n   {d['fonte']}\n   licença: {d['licenca']}")
        if d["kaggle"] is None:
            ok = (RAIZ / d["verificar"]).is_dir()
            print("  presente." if ok else "  NÃO encontrado.\n" + d["manual"])
            continue
        if not pendentes(d["pastas"], args.forcar):
            print("  já presente (ou sem módulo correspondente nesta branch): nada a baixar. "
                  "Use --forcar para baixar de novo.")
            continue
        with tempfile.TemporaryDirectory() as tmp:
            baixar_kaggle(d["kaggle"], Path(tmp))
            preencher(Path(tmp), d["pastas"], args.forcar)

    print("\n" + GERADOS)


if __name__ == "__main__":
    main()
