# calibrar_roi_esp32cam

Ferramenta de bancada para posicionar a ROI (caixa dos dígitos) do hidrômetro com a ESP32-CAM já montada.
A placa sobe um servidor web; no navegador do PC aparece o quadro **ao vivo**, no mesmo formato que o
firmware de OCR captura (`PIXFORMAT_GRAYSCALE`, `FRAMESIZE_QQVGA`, 160×120). Os pixels vão crus, sem JPEG,
então a caixa desenhada vale direto para o `lerDigitos()`.

## Uso

1. Arduino IDE: placa **AI Thinker ESP32-CAM**, **PSRAM habilitada**. Não precisa de biblioteca extra.
2. Rede (escolha uma):
   - **Sem configurar nada**: a placa cria a rede `Hidrometro-ROI` (senha `hidrometro`). Conecte o PC nela
     e abra <http://192.168.4.1>.
   - **Na sua rede**: crie `wifi_local.h` nesta pasta (já está no `.gitignore`):
     ```c
     #define WIFI_SSID  "minha-rede"
     #define WIFI_SENHA "minha-senha"
     ```
     Abra <http://hidrometro.local> ou o IP que aparece no monitor serial (115200). Se a placa não
     conectar em 15 s, ela cria a rede própria acima.
3. Na página:
   - arraste no vídeo para desenhar a caixa; arraste dentro para mover; arraste os cantos para redimensionar;
   - setas movem 1 px, Shift+setas mudam o tamanho; os campos x0/y0/x1/y1 também podem ser digitados;
   - ajuste **dígitos** (N): as linhas amarelas são as fatias que o firmware recorta, e o painel
     "Entrada do classificador" mostra cada fatia em 28×28, como o modelo recebe;
   - **Congelar** para ajustar com calma num quadro parado;
   - **Salvar no ESP32** grava na NVS. **Baixar JSON** e **Baixar foto (PNG)** guardam uma cópia no PC.

Gire o hidrômetro ou a câmera até os dígitos ficarem paralelos às bordas da caixa: o firmware de OCR
não corrige rotação.

## Onde a ROI fica

- **NVS**, namespace `roi`, chaves `x0`, `y0`, `x1`, `y1`, `n` (int) e `valida` (bool). Coordenadas no quadro
  160×120; `x1`/`y1` são exclusivos, como no `lerDigitos()`. A NVS sobrevive a reset, a deep sleep e a gravar
  outro sketch por cima (desde que *Erase All Flash Before Sketch Upload* esteja desligado; a NVS fica em
  `0x9000` em todos os esquemas de partição padrão, inclusive *Huge APP*).
- **JSON** baixado: `{"caixa": [x0, y0, x1, y1], "n_digitos": N, "quadro": [160, 120], "fatias": [...], ...}`,
  o mesmo campo `caixa` de `ModeloEDataset/calibracao_manual/*.json`.
- **Serial**: `ROI` imprime a salva, `APAGAR` apaga, `IP` mostra o endereço.

## Ler a ROI no firmware de OCR

Depois de calibrar, grave o `transmissor_ocr_esp32cam` normalmente. Para ele usar a ROI salva:

```cpp
#include <Preferences.h>

// Le a ROI gravada pelo calibrar_roi_esp32cam. false = nada salvo.
bool carregarRoi(int* x0, int* y0, int* x1, int* y1, int* n) {
  Preferences p;
  if (!p.begin("roi", true)) return false;
  bool ok = p.getBool("valida", false);
  if (ok) {
    *x0 = p.getInt("x0"); *y0 = p.getInt("y0");
    *x1 = p.getInt("x1"); *y1 = p.getInt("y1");
    *n  = p.getInt("n");
  }
  p.end();
  return ok;
}
```

Com ela, o `executarOcr()` pode pular a segmentação e chamar `lerDigitos(frame, x0, y0, x1, y1, ...)` direto.
Hoje o número de fatias lá é a constante `N_FATIAS`; para usar o `n` salvo, ele precisa virar parâmetro.

Se o firmware de OCR mudar de resolução ou formato de câmera, refaça a calibração: a ROI está em pixels do
quadro 160×120.
