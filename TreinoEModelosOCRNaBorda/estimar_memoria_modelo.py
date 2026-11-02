import numpy as np

# Camadas que NÃO materializam um tensor próprio na inferência int8:
#  - BatchNormalization e ReLU são fundidas na convolução pelo conversor
#  - Dropout não existe na inferência
#  - Reshape é só uma nova "visão" do mesmo buffer
CAMADAS_IGNORADAS = {"InputLayer", "BatchNormalization", "ReLU", "Dropout", "Reshape"}


def _elementos(shape):
    return int(np.prod([d for d in shape if d is not None]))


def estimar_memoria(modelo, nome="modelo", folga=0.30):
    """Estimativa para um modelo de grafo SEQUENCIAL (cada camada consome a saída
    da anterior), que é o caso da CRNN conv-only deste projeto.

    Pico de ativações = maior (entrada + saída) entre duas operações consecutivas,
    que é o que o planejador de memória do TFLite Micro precisa manter vivo ao
    mesmo tempo. É uma ESTIMATIVA: o arena real costuma ser maior por alinhamento
    e buffers temporários do kernel (a 'folga' abaixo cobre isso de forma grosseira).
    Confirme no dispositivo com arena_used_bytes().
    """
    atual = _elementos(modelo.input_shape[1:])
    pico, onde = atual, "entrada"
    params = 0
    bias_int32 = 0
    macs = 0

    for camada in modelo.layers:
        tipo = type(camada).__name__
        if tipo in CAMADAS_IGNORADAS:
            continue

        saida = _elementos(camada.output_shape[1:])
        if atual + saida > pico:
            pico, onde = atual + saida, camada.name
        atual = saida

        if tipo in ("Conv2D", "DepthwiseConv2D", "Dense"):
            params += camada.count_params()
        if tipo == "Conv2D":
            bias_int32 += camada.filters          # BN fundida vira 1 bias por canal
            kh, kw = camada.kernel_size
            cin = camada.input_shape[-1]
            h, w = camada.output_shape[1], camada.output_shape[2]
            macs += h * w * kh * kw * cin * camada.filters
        elif tipo == "Dense":
            *passos, cin = camada.input_shape[1:]
            n_passos = _elementos(passos) if passos else 1
            macs += n_passos * cin * camada.units

    pesos_int8 = params + 4 * bias_int32
    print(f"--- Estimativa de memória: {nome} ---")
    print(f"   Parâmetros: {params:,}  |  MACs por inferência: {macs / 1e6:.1f} M")
    print(f"   Pesos int8:    {pesos_int8 / 1024:8.0f} KiB   (float32: {params * 4 / 1024:8.0f} KiB)")
    print(f"   Pico de ativações (camada: {onde}):")
    print(f"      int8:    {pico / 1024:8.0f} KiB   (float32: {pico * 4 / 1024:8.0f} KiB)")
    arena_int8 = pico * (1 + folga)
    print(f"   Arena int8 com {folga * 100:.0f}% de folga: ~{arena_int8 / 1024:.0f} KiB")
    print(f"   RAM total se pesos ficarem em RAM: ~{(arena_int8 + pesos_int8) / 1024:.0f} KiB "
          f"| se ficarem em flash: ~{arena_int8 / 1024:.0f} KiB")
    return {"params": params, "macs": macs, "pesos_int8": pesos_int8,
            "pico_ativacoes": pico, "onde": onde}


# ==========================================================================
# MODELOS COM SKIP CONNECTIONS (U-Net): estimativa por tempo de vida dos tensores
# ==========================================================================
def _nomes_entradas(camada):
    nodo = camada.inbound_nodes[0]
    ins = nodo.inbound_layers
    if not isinstance(ins, (list, tuple)):
        ins = [ins]
    return [l.name for l in ins]


def estimar_memoria_grafo(modelo, nome="modelo", folga=0.30, scratch_transposeconv=True):
    """Pico de RAM (arena) de um grafo com ramificações, como o U-Net.

    Cada tensor fica vivo do op que o cria até o último op que o consome, e o
    planejador de memória precisa de todos os vivos ao mesmo tempo. Por isso uma skip
    connection de alta resolução pesa durante TODA a rede: ela só pode ser liberada
    depois da concatenação no fim do decoder.

    scratch_transposeconv: no TFLite Micro, a TransposeConv int8 reserva (pelo que
    conheço do kernel; confirme no seu runtime) um buffer temporário int32 do tamanho
    da saída, ou seja, 4 bytes por elemento, vivo só durante aquele op.
    """
    tamanho, nascimento, ultimo, ordem = {}, {}, {}, []
    scratch = {}
    alias = {}                      # camada fundida/transparente -> tensor que ela repassa
    params = macs = 0

    def resolver(n):
        while n in alias:
            n = alias[n]
        return n

    for camada in modelo.layers:
        tipo = type(camada).__name__
        n = camada.name
        if tipo == "InputLayer":
            tamanho[n] = _elementos(camada.output_shape[1:] if not isinstance(camada.output_shape, list)
                                    else camada.output_shape[0][1:])
            nascimento[n] = ultimo[n] = 0
            ordem.append(n)
            continue

        entradas = [resolver(x) for x in _nomes_entradas(camada)]
        if tipo in CAMADAS_IGNORADAS:
            alias[n] = entradas[0]          # BN/ReLU fundidos, Dropout nulo, Reshape é só uma visão
            continue

        i = len(ordem)
        tamanho[n] = _elementos(camada.output_shape[1:])
        nascimento[n] = ultimo[n] = i
        for x in entradas:
            ultimo[x] = max(ultimo[x], i)
        ordem.append(n)

        if tipo == "Conv2DTranspose":
            if scratch_transposeconv:
                scratch[n] = 4 * tamanho[n]
            kh, kw = camada.kernel_size
            cin = camada.input_shape[-1]
            h, w = camada.input_shape[1], camada.input_shape[2]
            macs += h * w * kh * kw * cin * camada.filters
        elif tipo == "Conv2D":
            kh, kw = camada.kernel_size
            cin = camada.input_shape[-1]
            macs += camada.output_shape[1] * camada.output_shape[2] * kh * kw * cin * camada.filters
        if tipo in ("Conv2D", "Conv2DTranspose", "DepthwiseConv2D", "Dense"):
            params += camada.count_params()

    pico, onde = 0, ""
    for i, n in enumerate(ordem):
        vivos = sum(tamanho[t] for t in tamanho if nascimento[t] <= i <= ultimo[t])
        vivos += scratch.get(n, 0)
        if vivos > pico:
            pico, onde = vivos, n

    arena = pico * (1 + folga)
    print(f"--- Estimativa de memória (grafo): {nome} ---")
    print(f"   Parâmetros: {params:,}  |  MACs por inferência: {macs / 1e6:.1f} M")
    print(f"   Pesos int8: ~{params / 1024:.0f} KiB (float32: ~{params * 4 / 1024:.0f} KiB)")
    print(f"   Pico de RAM int8 no op '{onde}': {pico / 1024:.0f} KiB "
          f"({'com' if scratch_transposeconv else 'sem'} buffer da TransposeConv)")
    print(f"   Arena com {folga * 100:.0f}% de folga: ~{arena / 1024:.0f} KiB ({arena / 1024 / 1024:.2f} MiB)")
    return {"params": params, "macs": macs, "pico": pico, "onde": onde, "arena": arena}
