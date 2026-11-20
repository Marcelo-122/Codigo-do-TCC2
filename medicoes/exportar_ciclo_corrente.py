"""
Exporta UM ciclo de uma captura de corrente (despertar -> fim do repouso seguinte) num
arquivo .dat de duas colunas ("t mA"), para desenhar o grafico do ciclo (pgfplots no TCC).

Os ciclos sao achados como no "corrente.py analisar" (mesmo nivel de sleep, mesmo limiar e
mesma numeracao da tabela que ele imprime). As amostras de 100 Hz viram um envelope: para
cada janela de --janela-s segundos, o minimo e o maximo, o que mantem os picos de TX
(~136 ms) e reduz o arquivo para algumas centenas de pontos.

  python medicoes/exportar_ciclo_corrente.py medicoes/corrente/auto30_imagem.csv 8 ciclo_nuvem.dat --max-amostras 685000
  python medicoes/exportar_ciclo_corrente.py medicoes/corrente/auto30_ocr.csv 4 ciclo_borda.dat

Esses dois comandos geram os arquivos da figura do TCC (corrente_ciclo_nuvem.dat e
corrente_ciclo_borda.dat): ciclo 8 da imagem (219,3 s, 4,648 mAh) e ciclo 4 do OCR
(49,06 s, 0,822 mAh), escolhidos por terem carga proxima da mediana de cada corrida.

Para a apresentacao final, os ciclos da configuracao adotada (ROI e Radioenge em classe A, 2026-11-19), com carga
proxima da media de cada corrida (2,914 e 0,175 mAh):

  python medicoes/exportar_ciclo_corrente.py medicoes/corrente/auto30_imagem_classe_a.csv 24 corrente_ciclo_nuvem_classe_a.dat
  python medicoes/exportar_ciclo_corrente.py medicoes/corrente/auto30_ocr_roi_classe_a.csv 4 corrente_ciclo_borda_classe_a.dat

ciclo 24 da imagem (170,61 s, 2,882 mAh) e ciclo 4 do OCR (33,76 s, 0,176 mAh).
"""
import argparse
import os
import statistics as st
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from corrente import achar_sleeps, carregar, integra  # noqa: E402


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("csv", help="captura do ina219_logger (t_us,shunt_mV,bus_V)")
    p.add_argument("ciclo", type=int, help="numero do ciclo, como na tabela do 'corrente.py analisar'")
    p.add_argument("saida", help="arquivo .dat de saida")
    p.add_argument("--offset-ma", type=float, default=0.0)
    p.add_argument("--min-sleep-s", type=float, default=12.0, help="o mesmo usado no 'analisar'")
    p.add_argument("--max-amostras", type=int, default=None, help="o mesmo usado no 'analisar'")
    p.add_argument("--janela-s", type=float, default=0.25, help="janela do envelope min/max")
    a = p.parse_args()

    t, i, _ = carregar(a.csv, a.offset_ma)
    if a.max_amostras:
        t, i = t[: a.max_amostras], i[: a.max_amostras]
    nivel = st.median(sorted(i)[: max(10, len(i) // 10)])
    limiar = nivel + max(5.0, 0.5 * nivel)
    acordes = [fim for _, fim in achar_sleeps(t, i, limiar, a.min_sleep_s)]
    if not 1 <= a.ciclo < len(acordes):
        sys.exit(f"Ciclo {a.ciclo} fora do intervalo 1..{len(acordes) - 1}")
    ini, fim = acordes[a.ciclo - 1], acordes[a.ciclo]
    print(f"ciclo {a.ciclo}: {t[fim] - t[ini]:.2f} s, {integra(t, i, ini, fim):.3f} mAh, pico {max(i[ini:fim]):.1f} mA")

    with open(a.saida, "w") as f:
        f.write("t mA\n")
        k = ini
        while k < fim:
            t0, janela = t[k], []
            while k < fim and t[k] < t0 + a.janela_s:
                janela.append(i[k])
                k += 1
            f.write(f"{t0 - t[ini]:.3f} {min(janela):.1f}\n{t0 - t[ini] + a.janela_s / 2:.3f} {max(janela):.1f}\n")
    print(f"-> {a.saida}")


if __name__ == "__main__":
    main()
