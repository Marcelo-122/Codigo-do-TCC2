"""Leitura do hidrômetro no servidor: o lado "nuvem" da comparação borda × nuvem.

Roda no PC os MESMOS modelos do Pipeline B (segmentação `modelo_esp32.tflite` e classificador
`modelo_digito.tflite`, de `ModeloEDataset/modelos/`) com a MESMA lógica do firmware
`test_images/debug_ocr_esp32cam/debug_ocr_esp32cam.ino`, para que a única diferença entre borda e
nuvem seja onde a conta é feita e o que trafega pelo enlace:

  borda: a ESP32-CAM lê o quadro 160×120 em tons de cinza e envia só a leitura (poucos bytes);
  nuvem: a ESP32-CAM envia o quadro como JPEG (qualidade 90), o servidor o remonta e lê.

Passos (iguais aos do firmware):
  1. quadro 160×120 cinza -> 192×192 por vizinho mais próximo; entrada int8 = pixel - 128;
  2. segmentação; caixa = menor retângulo (sem rotação) que contém todos os pixels com saída > 0;
  3. a caixa é cortada em N fatias de largura igual (N = número de rodinhas do medidor);
  4. cada fatia -> 28×28 por vizinho mais próximo, entrada int8 = pixel - 128, argmax das 10 classes.

Uso:
    python ocr/pipeline_nuvem.py foto.jpg --digitos 6             # modo nuvem (passa pelo JPEG q90)
    python ocr/pipeline_nuvem.py foto.jpg --digitos 6 --modo borda
    python ocr/pipeline_nuvem.py foto.jpg --digitos 6 --centro-y 250  # foto em retrato: faixa 4:3 em y=250
    python ocr/pipeline_nuvem.py foto.jpg --digitos 6 --debug saida.png   # desenha caixa e fatias
    python ocr/pipeline_nuvem.py foto.jpg --digitos 6 --alinhar       # endireita a inclinação (Hough) antes de ler
    python ocr/pipeline_nuvem.py foto.jpg --digitos 6 --roi 19,51,117,69   # janela fixa (câmera parada): sem segmentação
    python ocr/pipeline_nuvem.py foto.jpg --digitos 6 --roi 19,51,117,69 --votar   # soma 5 caixas deslocadas

Entrada: qualquer imagem. Se não for 160×120, vira um quadro 160×120 em cinza (INTER_AREA), o que emula
o que a câmera entrega ao firmware. O OpenCV respeita a orientação EXIF do JPEG (as fotos de
`ocr/teste_comum/` têm EXIF 8 e chegam em retrato, 480×640). Fotos que não são 4:3 paisagem não são
esticadas: recorta-se uma faixa 4:3 de largura total, centrada em `--centro-y` (a altura da janela dos
dígitos), o equivalente a apontar a câmera para o medidor. Requer: pip install -r ocr/requirements.txt
"""
import argparse
import os
import sys
import time

import cv2
import numpy as np

try:  # evita o delegate XNNPACK: a TFLM do firmware usa kernels de referência
    from ai_edge_litert.interpreter import Interpreter, OpResolverType
    _SEM_DELEGATE = dict(experimental_op_resolver_type=OpResolverType.BUILTIN_WITHOUT_DEFAULT_DELEGATES)
except ImportError:  # pragma: no cover - fallback para outras distribuições do TFLite
    from tensorflow.lite.python.interpreter import Interpreter
    _SEM_DELEGATE = {}

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELO_SEGMENTACAO = os.path.join(RAIZ, "ModeloEDataset", "modelos", "modelo_esp32.tflite")
MODELO_DIGITO = os.path.join(RAIZ, "ModeloEDataset", "modelos", "modelo_digito.tflite")

CAM_W, CAM_H = 160, 120      # QQVGA, como o firmware captura
MODEL_W, MODEL_H = 192, 192  # entrada da segmentação
DIGIT_W, DIGIT_H = 28, 28    # entrada do classificador de dígito
JPEG_QUALIDADE = 90          # JPEG_QUALITY do transmissor (Rede/transmissor_esp32cam)
POSICAO_JANELA = 0.43        # onde a janela dos dígitos fica na altura do quadro (nos frames reais, ~0,4 a 0,5)


def topo_da_faixa(h, w, centro_y=None):
    """Linha onde começa a faixa 4:3 de largura total que `para_quadro_camera` recorta de uma foto em retrato."""
    alt = w * CAM_H // CAM_W
    centro = h / 2 if centro_y is None else centro_y
    return int(min(max(centro - POSICAO_JANELA * alt, 0), h - alt)), alt


def para_quadro_camera(imagem, centro_y=None):
    """Devolve um quadro uint8 CAM_H×CAM_W em tons de cinza (o que a câmera entrega ao firmware).

    Imagem que não é 4:3 paisagem (por exemplo, foto em retrato) não é esticada: corta-se uma faixa 4:3
    de largura total, com a janela dos dígitos em `centro_y` (linha da imagem; padrão: meio da imagem)
    a `POSICAO_JANELA` da altura da faixa."""
    if imagem.ndim == 3:
        imagem = cv2.cvtColor(imagem, cv2.COLOR_BGR2GRAY)
    h, w = imagem.shape
    if abs(w / h - CAM_W / CAM_H) > 0.01:
        if w * CAM_H > h * CAM_W:  # mais larga que 4:3: corta as laterais, centrado
            novo_w = h * CAM_W // CAM_H
            x0 = (w - novo_w) // 2
            imagem = imagem[:, x0:x0 + novo_w]
        else:                      # mais alta que 4:3 (retrato): faixa horizontal em torno de centro_y
            topo, alt = topo_da_faixa(h, w, centro_y)
            imagem = imagem[topo:topo + alt]
    if imagem.shape != (CAM_H, CAM_W):
        imagem = cv2.resize(imagem, (CAM_W, CAM_H), interpolation=cv2.INTER_AREA)
    return imagem


def transmitir_como_jpeg(quadro, qualidade=JPEG_QUALIDADE):
    """Emula o que o servidor recebe: o quadro comprimido em JPEG e decodificado de volta.

    Devolve (quadro_remontado, bytes_do_jpeg). Não simula perda de pacotes; a imagem chega inteira."""
    ok, jpeg = cv2.imencode(".jpg", quadro, [cv2.IMWRITE_JPEG_QUALITY, qualidade])
    if not ok:
        raise RuntimeError("falha ao codificar o JPEG")
    remontado = cv2.imdecode(jpeg, cv2.IMREAD_GRAYSCALE)
    return remontado, int(jpeg.size)


def estimar_inclinacao(quadro):
    """Ângulo (graus, convenção de `cv2.getRotationMatrix2D`: positivo = anti-horário) que endireita as linhas
    quase horizontais do quadro (moldura da janela, texto), pela mediana ponderada das linhas de Hough."""
    bordas = cv2.Canny(cv2.GaussianBlur(quadro, (3, 3), 0), 40, 110)
    linhas = cv2.HoughLinesP(bordas, 1, np.pi / 360, threshold=25, minLineLength=35, maxLineGap=4)
    if linhas is None:
        return 0.0
    angulos, pesos = [], []
    for x1, y1, x2, y2 in linhas.reshape(-1, 4):
        a = np.degrees(np.arctan2(-(y2 - y1), x2 - x1))  # positivo = a linha sobe para a direita
        if abs(a) <= 20:
            angulos.append(a)
            pesos.append(np.hypot(x2 - x1, y2 - y1))
    if not angulos:
        return 0.0
    ordem = np.argsort(angulos)
    angulos, acumulado = np.array(angulos)[ordem], np.cumsum(np.array(pesos)[ordem])
    return -float(angulos[np.searchsorted(acumulado, acumulado[-1] / 2)])


def alinhar(quadro, angulo=None):
    """Gira o quadro em torno do centro para deixar a fileira de dígitos horizontal. Devolve (quadro, ângulo)."""
    if angulo is None:
        angulo = estimar_inclinacao(quadro)
    m = cv2.getRotationMatrix2D((CAM_W / 2, CAM_H / 2), angulo, 1.0)
    return cv2.warpAffine(quadro, m, (CAM_W, CAM_H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE), angulo


def girar_caixa(caixa, angulo):
    """Leva uma caixa (x0, y0, x1, y1) marcada no quadro original para o quadro depois de `alinhar` (mesmo tamanho)."""
    x0, y0, x1, y1 = caixa
    m = cv2.getRotationMatrix2D((CAM_W / 2, CAM_H / 2), angulo, 1.0)
    cantos = cv2.transform(np.array([[[x0, y0], [x1, y0], [x0, y1], [x1, y1]]], np.float32), m)[0]
    cx, cy = (cantos[:, 0].min() + cantos[:, 0].max()) / 2, (cantos[:, 1].min() + cantos[:, 1].max()) / 2
    return (int(cx - (x1 - x0) / 2), int(cy - (y1 - y0) / 2), int(cx + (x1 - x0) / 2), int(cy + (y1 - y0) / 2))


def _vizinho_mais_proximo(quadro, x0, y0, largura, altura, saida_w, saida_h):
    """Mesmo cálculo de índices do firmware: src = origem + (i * tamanho) // saida."""
    largura = max(largura, 1)
    altura = max(altura, 1)
    ys = y0 + (np.arange(saida_h) * altura) // saida_h
    xs = x0 + (np.arange(saida_w) * largura) // saida_w
    return quadro[ys][:, xs]


def _para_int8(pixels):
    return (pixels.astype(np.int16) - 128).astype(np.int8)[np.newaxis, :, :, np.newaxis]


class LeitorB:
    """Pipeline B (segmentação + classificador de dígito), no PC."""

    def __init__(self, modelo_segmentacao=MODELO_SEGMENTACAO, modelo_digito=MODELO_DIGITO):
        self.seg = Interpreter(model_path=modelo_segmentacao, **_SEM_DELEGATE)
        self.dig = Interpreter(model_path=modelo_digito, **_SEM_DELEGATE)
        self.seg.allocate_tensors()
        self.dig.allocate_tensors()
        self._seg_in = self.seg.get_input_details()[0]
        self._seg_out = self.seg.get_output_details()[0]
        self._dig_in = self.dig.get_input_details()[0]
        self._dig_out = self.dig.get_output_details()[0]
        # A conta "pixel - 128" e o limiar "saída > 0" só valem com estas quantizações (as dos modelos de B).
        esperado_in = (1 / 255, -128)
        for nome, det in (("segmentação", self._seg_in), ("dígito", self._dig_in)):
            esc, zp = det["quantization"]
            if abs(esc - esperado_in[0]) > 1e-4 or zp != esperado_in[1]:
                raise ValueError(f"entrada do modelo de {nome} com quantização inesperada: {det['quantization']}")
        if self._seg_out["quantization"][1] != -128:
            raise ValueError("saída da segmentação com zero_point diferente de -128")

    def achar_mascara(self, quadro):
        """Máscara booleana MODEL_H×MODEL_W (192×192) da segmentação: saída int8 > 0, o mesmo limiar do firmware."""
        entrada = _para_int8(_vizinho_mais_proximo(quadro, 0, 0, CAM_W, CAM_H, MODEL_W, MODEL_H))
        self.seg.set_tensor(self._seg_in["index"], entrada)
        self.seg.invoke()
        return self.seg.get_tensor(self._seg_out["index"])[0, :, :, 0] > 0

    def achar_caixa(self, quadro, mascara=None):
        """Caixa (x0, y0, x1, y1) em coordenadas do quadro 160×120, ou None se a máscara vier vazia."""
        if mascara is None:
            mascara = self.achar_mascara(quadro)
        if not mascara.any():
            return None
        ys, xs = np.nonzero(mascara)
        return ((int(xs.min()) * CAM_W) // MODEL_W, (int(ys.min()) * CAM_H) // MODEL_H,
                (int(xs.max()) * CAM_W) // MODEL_W, (int(ys.max()) * CAM_H) // MODEL_H)

    def pontuacoes_fatia(self, quadro, sx0, sy0, sx1, sy1):
        """Saída do classificador (10 classes, int8 da softmax) para a região dada."""
        fatia = _vizinho_mais_proximo(quadro, sx0, sy0, sx1 - sx0, sy1 - sy0, DIGIT_W, DIGIT_H)
        self.dig.set_tensor(self._dig_in["index"], _para_int8(fatia))
        self.dig.invoke()
        return self.dig.get_tensor(self._dig_out["index"])[0].astype(np.float32)

    def classificar_fatia(self, quadro, sx0, sy0, sx1, sy1):
        return int(np.argmax(self.pontuacoes_fatia(quadro, sx0, sy0, sx1, sy1)))

    def ler(self, quadro, n_digitos, caixa=None, deslocamentos=((0, 0),)):
        """Lê o quadro. Devolve dict com 'leitura' (string; '-' * n se não achou a caixa), 'caixa', 'mascara'
        (192×192; None se a caixa foi dada) e tempos.

        `caixa` (x0, y0, x1, y1) pula a segmentação e usa a janela dada (diagnóstico: isola o erro do
        classificador do erro da segmentação). Sem ela, a caixa vem do modelo, como no firmware.

        `deslocamentos` [(dx, dy), ...] soma as saídas do classificador sobre a caixa deslocada de cada par
        (votação): tolera uma caixa imprecisa ao custo de rodar o classificador uma vez por deslocamento."""
        t0 = time.perf_counter()
        mascara = None
        if caixa is None:
            mascara = self.achar_mascara(quadro)
            caixa = self.achar_caixa(quadro, mascara)
        t1 = time.perf_counter()
        if caixa is None:
            return {"leitura": "-" * n_digitos, "caixa": None, "mascara": mascara,
                    "t_seg_ms": (t1 - t0) * 1e3, "t_dig_ms": 0.0}
        digitos = []
        for i in range(n_digitos):
            soma = np.zeros(10, np.float32)
            for dx, dy in deslocamentos:
                x0 = min(max(caixa[0] + dx, 0), CAM_W - 2)
                x1 = min(max(caixa[2] + dx, x0 + 1), CAM_W - 1)
                y0 = min(max(caixa[1] + dy, 0), CAM_H - 2)
                y1 = min(max(caixa[3] + dy, y0 + 1), CAM_H - 1)
                largura = x1 - x0
                sx0 = x0 + (largura * i) // n_digitos
                sx1 = x0 + (largura * (i + 1)) // n_digitos
                soma += self.pontuacoes_fatia(quadro, sx0, y0, sx1, y1)
            digitos.append(str(int(np.argmax(soma))))
        t2 = time.perf_counter()
        return {"leitura": "".join(digitos), "caixa": caixa, "mascara": mascara,
                "t_seg_ms": (t1 - t0) * 1e3, "t_dig_ms": (t2 - t1) * 1e3}


def desenhar(quadro, caixa, n_digitos, escala=4):
    """Quadro ampliado com a caixa e as linhas de fatia (para conferir onde o modelo olhou)."""
    img = cv2.cvtColor(cv2.resize(quadro, None, fx=escala, fy=escala, interpolation=cv2.INTER_NEAREST),
                       cv2.COLOR_GRAY2BGR)
    if caixa is None:
        cv2.putText(img, "sem caixa", (6, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
        return img
    x0, y0, x1, y1 = [v * escala for v in caixa]
    cv2.rectangle(img, (x0, y0), (x1, y1), (0, 255, 0), 1)
    for i in range(1, n_digitos):
        x = x0 + ((x1 - x0) * i) // n_digitos
        cv2.line(img, (x, y0), (x, y1), (0, 200, 255), 1)
    return img


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("imagem")
    ap.add_argument("--digitos", type=int, required=True, help="número de rodinhas do medidor (N_FATIAS do firmware)")
    ap.add_argument("--centro-y", type=int, help="altura da janela dos dígitos, para fotos em retrato (ver o docstring)")
    ap.add_argument("--modo", choices=["nuvem", "borda"], default="nuvem",
                    help="nuvem: o quadro passa pelo JPEG q90 antes da leitura; borda: lê o quadro direto")
    ap.add_argument("--alinhar", action="store_true", help="endireita a inclinação do quadro antes de ler (no servidor)")
    ap.add_argument("--roi", metavar="x0,y0,x1,y1", help="janela dos dígitos fixa no quadro 160x120 (câmera parada): pula a segmentação")
    ap.add_argument("--votar", action="store_true", help="com --roi, soma as saídas de 5 caixas deslocadas (±2 px em x, ±1 px em y)")
    ap.add_argument("--debug", metavar="ARQUIVO", help="grava a imagem com a caixa e as fatias desenhadas")
    a = ap.parse_args()

    bruto = cv2.imdecode(np.fromfile(a.imagem, np.uint8), cv2.IMREAD_COLOR)
    if bruto is None:
        sys.exit(f"não consegui abrir {a.imagem}")
    quadro = para_quadro_camera(bruto, a.centro_y)
    tamanho_jpeg = None
    if a.modo == "nuvem":
        quadro, tamanho_jpeg = transmitir_como_jpeg(quadro)
    if a.alinhar:
        quadro, angulo = alinhar(quadro)
        print(f"inclinação corrigida: {angulo:+.1f} graus")
    roi = tuple(int(v) for v in a.roi.split(",")) if a.roi else None
    desl = ((0, 0), (-2, 0), (2, 0), (0, -1), (0, 1)) if a.votar else ((0, 0),)
    r = LeitorB().ler(quadro, a.digitos, caixa=roi, deslocamentos=desl)
    print(f"leitura: {r['leitura']}  caixa: {r['caixa']}  segmentação: {r['t_seg_ms']:.0f} ms  dígitos: {r['t_dig_ms']:.0f} ms")
    if tamanho_jpeg:
        print(f"JPEG transmitido: {tamanho_jpeg} bytes")
    if a.debug:
        cv2.imencode(".png", desenhar(quadro, r["caixa"], a.digitos))[1].tofile(a.debug)


if __name__ == "__main__":
    main()
