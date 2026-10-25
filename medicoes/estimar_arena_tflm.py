"""Estima a arena de tensores que o TFLite Micro precisa para um .tflite.

Reproduz o planejador guloso do TFLM (GreedyMemoryPlanner): cada tensor de ativação
tem um intervalo de vida [primeiro_op, ultimo_op]; os maiores são colocados primeiro,
no menor deslocamento que não colide com tensores vivos ao mesmo tempo. Os pesos
(constantes) ficam na flash e não entram na conta.

Também entra o buffer temporário que o kernel de referência de TRANSPOSE_CONV pede
(acumuladores int32 do tamanho da saída), vivo só durante aquele nó. Sem ele a
segmentação de B dá 0,42 MB contra 1,62 MB medidos no ESP32-CAM; com ele o erro cai
para ~0,1%. Não modela a parte persistente (estruturas dos nós, dados dos operadores,
alguns kilobytes) nem os buffers de kernels otimizados (ESP-NN), por isso o resultado
pode ficar levemente abaixo do `arena_used_bytes()` real. Use --calibrar para ver o erro.

Uso:
    python estimar_arena_tflm.py modelo1.tflite [modelo2.tflite ...]
    python estimar_arena_tflm.py --calibrar   # compara com a arena medida da segmentação de B

Requer: pip install tflite numpy
"""
import argparse
import os
import sys

import numpy as np
import tflite

ALINHAMENTO = 16  # TFLM alinha os buffers da arena em 16 bytes

# bytes por elemento de cada tipo de tensor do schema do TFLite
TAMANHO_TIPO = {
    tflite.TensorType.FLOAT32: 4,
    tflite.TensorType.FLOAT16: 2,
    tflite.TensorType.INT32: 4,
    tflite.TensorType.UINT8: 1,
    tflite.TensorType.INT64: 8,
    tflite.TensorType.BOOL: 1,
    tflite.TensorType.INT16: 2,
    tflite.TensorType.INT8: 1,
    tflite.TensorType.FLOAT64: 8,
}
NOME_OP = {v: k for k, v in vars(tflite.BuiltinOperator).items() if not k.startswith("_")}


def alinhar(n):
    return (n + ALINHAMENTO - 1) // ALINHAMENTO * ALINHAMENTO


def carregar(caminho):
    with open(caminho, "rb") as f:
        return tflite.Model.GetRootAsModel(bytearray(f.read()), 0)


def tensores_da_arena(modelo):
    """Devolve (lista de [nome, bytes, inicio, fim, forma], operadores usados, número de nós)."""
    sub = modelo.Subgraphs(0)
    n_ops = sub.OperatorsLength()
    entradas = {sub.Inputs(i) for i in range(sub.InputsLength())}
    saidas = {sub.Outputs(i) for i in range(sub.OutputsLength())}

    inicio, fim = {}, {}
    for i in range(n_ops):
        op = sub.Operators(i)
        for j in range(op.OutputsLength()):
            t = op.Outputs(j)
            if t >= 0:
                inicio.setdefault(t, i)
                fim[t] = max(fim.get(t, i), i)
        for j in range(op.InputsLength()):
            t = op.Inputs(j)
            if t >= 0:
                fim[t] = max(fim.get(t, i), i)
    for t in entradas:
        inicio[t] = 0
    for t in saidas:
        fim[t] = n_ops - 1

    tensores = []
    for t, i0 in inicio.items():
        tensor = sub.Tensors(t)
        if modelo.Buffers(tensor.Buffer()).DataLength() > 0:
            continue  # constante: mora na flash
        forma = [tensor.Shape(k) for k in range(tensor.ShapeLength())]
        n = int(np.prod(forma)) if forma else 1
        nbytes = n * TAMANHO_TIPO.get(tensor.Type(), 4)
        nome = tensor.Name().decode() if tensor.Name() else f"t{t}"
        tensores.append([nome, alinhar(nbytes), i0, fim.get(t, i0), forma])

    nomes_ops = [NOME_OP.get(modelo.OperatorCodes(sub.Operators(i).OpcodeIndex()).BuiltinCode(), "?")
                 for i in range(n_ops)]
    for i, nome_op in enumerate(nomes_ops):
        if nome_op == "TRANSPOSE_CONV":
            saida = sub.Tensors(sub.Operators(i).Outputs(0))
            n = int(np.prod([saida.Shape(k) for k in range(saida.ShapeLength())]))
            tensores.append([f"scratch_transpose_conv_{i}", alinhar(n * 4), i, i, [n]])
    return tensores, sorted(set(nomes_ops)), n_ops


def planejar(tensores):
    """Planejador guloso por tamanho (mesmo critério do TFLM). Devolve o pico em bytes."""
    ordem = sorted(tensores, key=lambda t: (-t[1], t[2]))
    colocados = []  # (deslocamento, tamanho, inicio, fim)
    pico = 0
    for _, tam, i0, i1, _forma in ordem:
        conflitos = sorted(
            (off, off + sz) for off, sz, a, b in colocados if not (i1 < a or b < i0)
        )
        candidato = 0
        for lo, hi in conflitos:
            if candidato + tam <= lo:
                break
            candidato = max(candidato, hi)
        colocados.append((candidato, tam, i0, i1))
        pico = max(pico, candidato + tam)
    return pico


def relatar(caminho):
    modelo = carregar(caminho)
    tensores, ops, n_ops = tensores_da_arena(modelo)
    pico = planejar(tensores)
    soma = sum(t[1] for t in tensores)
    maior = max(tensores, key=lambda t: t[1])
    tam_arquivo = os.path.getsize(caminho)
    print(f"\n{os.path.basename(caminho)}  ({tam_arquivo / 1024:.1f} KB no arquivo)")
    print(f"  operadores: {n_ops} nós; tipos: {', '.join(ops)}")
    print(f"  tensores de ativação: {len(tensores)}; soma sem reuso: {soma / 1024:.1f} KB")
    print(f"  maior tensor: {maior[1] / 1024:.1f} KB  forma {maior[4]}")
    print(f"  ARENA PLANEJADA (pico): {pico:,} bytes = {pico / 1024 / 1024:.2f} MB")
    return pico


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("modelos", nargs="*")
    ap.add_argument("--calibrar", action="store_true",
                    help="roda o modelo de segmentação de B e compara com a arena medida no ESP32-CAM")
    a = ap.parse_args()

    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if a.calibrar:
        caminho = os.path.join(raiz, "ModeloEDataset", "modelos", "modelo_esp32.tflite")
        medido = 1623852  # arena_seg_bytes de medicoes/debug_metricas.csv
        pico = relatar(caminho)
        print(f"  arena medida no ESP32-CAM (arena_used_bytes): {medido:,}")
        print(f"  estimativa / medido = {pico / medido:.2f}")
        caminho = os.path.join(raiz, "ModeloEDataset", "modelos", "modelo_digito.tflite")
        pico = relatar(caminho)
        print("  arena medida no ESP32-CAM (arena_used_bytes): 28,556")
        print(f"  estimativa / medido = {pico / 28556:.2f}")
        return
    if not a.modelos:
        ap.print_help()
        sys.exit(1)
    for m in a.modelos:
        relatar(m)


if __name__ == "__main__":
    main()
