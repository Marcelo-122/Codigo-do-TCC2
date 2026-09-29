import numpy as np


def distancia_edicao(a, b):
    """Distância de Levenshtein entre duas listas de dígitos."""
    m, n = len(a), len(b)
    dp = list(range(n + 1))
    for i in range(1, m + 1):
        prev, dp[0] = dp[0], i
        for j in range(1, n + 1):
            atual = dp[j]
            custo = 0 if a[i - 1] == b[j - 1] else 1
            dp[j] = min(dp[j] + 1, dp[j - 1] + 1, prev + custo)
            prev = atual
    return dp[n]

def localizar_erro(real, pred):
    """Classifica onde (aproximadamente) está a diferença entre real e pred,
    quando os tamanhos diferem por 1 dígito. Retorna 'inicio', 'fim',
    'meio' ou None (tamanhos iguais ou diferença > 1)."""
    if abs(len(real) - len(pred)) != 1:
        return None
    maior, menor = (real, pred) if len(real) > len(pred) else (pred, real)
    for i in range(len(maior)):
        candidato = maior[:i] + maior[i + 1:]
        if candidato == menor:
            terco = len(maior) / 3
            if i < terco:
                return 'inicio'
            if i > 2 * terco:
                return 'fim'
            return 'meio'
    return 'outro'   # diferença de tamanho mas não é uma simples inserção/remoção

def analisar_posicao_erros(resultados):
    contagem = {'inicio': 0, 'fim': 0, 'meio': 0, 'outro': 0, 'mesmo_tamanho': 0}
    for real, pred in resultados:
        if real == pred:
            continue
        if len(real) == len(pred):
            contagem['mesmo_tamanho'] += 1
            continue
        pos = localizar_erro(real, pred)
        contagem[pos or 'outro'] += 1

    total_erros = sum(contagem.values())
    if total_erros == 0:
        print("   (nenhum erro para analisar)")
        return
    print(f"   Localização dos {total_erros} erros:")
    for chave, rotulo in [('inicio', 'dígito a mais/a menos no INÍCIO'),
                          ('fim', 'dígito a mais/a menos no FIM'),
                          ('meio', 'dígito a mais/a menos no MEIO'),
                          ('mesmo_tamanho', 'mesmo tamanho (substituição/troca de posição)'),
                          ('outro', 'outro tipo de diferença')]:
        n = contagem[chave]
        if n:
            print(f"     {rotulo}: {n} ({100 * n / total_erros:.1f}%)")


def decodificar_beam_search(logits_batch, tamanhos, beam_width=10):
    """logits_batch: (batch, TIMESTEPS, N_CLASSES) logits (sem softmax).
    tamanhos: (batch,) com TIMESTEPS de cada amostra (geralmente todas iguais).
    Retorna lista de listas de dígitos. Mais robusto que o argmax greedy
    perto das bordas da sequência, onde a confiança costuma oscilar mais."""
    import tensorflow as tf
    logits_tm = tf.transpose(tf.cast(logits_batch, tf.float32), [1, 0, 2])  # time-major
    decodificado, _ = tf.nn.ctc_beam_search_decoder(
        logits_tm, sequence_length=tamanhos, beam_width=beam_width, top_paths=1)
    esparso = decodificado[0]
    denso = tf.sparse.to_dense(esparso, default_value=-1).numpy()
    saida = []
    for linha in denso:
        saida.append([int(v) for v in linha if v >= 0])
    return saida
    """Simula o que aconteceria se toda repetição consecutiva fosse fundida
    em uma só (o comportamento do CTC quando falta um blank entre elas)."""
    saida = []
    for d in lista:
        if not saida or saida[-1] != d:
            saida.append(d)
    return saida

def diagnosticar_colapso(resultados):
    """resultados: lista de (real, previsto), cada um lista de dígitos.
    Retorna estatísticas para saber se o erro dominante é colapso de
    repetições consecutivas (típico de zeros seguidos em leituras de
    hidrômetro) em vez de erro de classificação dígito a dígito."""
    n = len(resultados)
    exatos = 0
    bate_com_colapso_esperado = 0   # previsto == real, mas SEM repetições, colapsado
    dist_total = 0
    mais_curto_que_colapso = 0

    for real, pred in resultados:
        if real == pred:
            exatos += 1
        dist_total += distancia_edicao(real, pred)

        real_colapsado = colapsar_repeticoes(real)
        # Se o previsto bate com o real já sem as repetições, é um forte
        # indício de que o modelo está fundindo dígitos repetidos.
        if pred == real_colapsado and real != real_colapsado:
            bate_com_colapso_esperado += 1
        if len(pred) < len(real_colapsado):
            mais_curto_que_colapso += 1

    print(f"   Sequência exata: {exatos}/{n} ({100 * exatos / n:.1f}%)")
    print(f"   Distância de edição média: {dist_total / n:.2f} dígitos")
    print(f"   Previsto == real SEM as repetições consecutivas "
          f"(indício de colapso do CTC): {bate_com_colapso_esperado}/{n} "
          f"({100 * bate_com_colapso_esperado / n:.1f}%)")
    print(f"   Previsto mais curto que o real até colapsado (perdendo dígitos "
          f"além da repetição): {mais_curto_que_colapso}/{n}")