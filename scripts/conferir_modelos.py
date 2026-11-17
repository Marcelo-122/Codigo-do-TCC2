"""Confere se as cópias dos headers dos modelos são iguais à de ModeloEDataset/modelos/.

Os firmwares da ESP32-CAM precisam de uma cópia de `modelo.h` (segmentação) e de `modelo_digito.h`
(classificador) na pasta do sketch, porque a Arduino IDE não inclui arquivos de fora dela. Este script compara
cada cópia com a original (SHA-256) e sai com código 1 se alguma estiver diferente ou faltando.

Uso (na raiz do repositório):  python scripts/conferir_modelos.py
"""
import hashlib
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
ORIGEM = RAIZ / "ModeloEDataset" / "modelos"
COPIAS = [
    RAIZ / "Rede" / "transmissor_ocr_esp32cam",
    RAIZ / "test_images" / "debug_ocr_esp32cam",
]
ARQUIVOS = ["modelo.h", "modelo_digito.h"]


def sha256(caminho: Path) -> str:
    return hashlib.sha256(caminho.read_bytes()).hexdigest()


def main() -> int:
    ok = True
    for nome in ARQUIVOS:
        original = ORIGEM / nome
        ref = sha256(original)
        print(f"{nome}: {ref[:12]} ({original.relative_to(RAIZ).as_posix()})")
        for pasta in COPIAS:
            copia = pasta / nome
            rel = copia.relative_to(RAIZ).as_posix()
            if not copia.exists():
                print(f"  FALTA      {rel}")
                ok = False
            elif sha256(copia) != ref:
                print(f"  DIFERENTE  {rel}")
                ok = False
            else:
                print(f"  igual      {rel}")
    if not ok:
        print("\nCopie de novo a partir de ModeloEDataset/modelos/ (ou regenere com gerar_header.py).")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
