// ============================================================
// calibrar_roi_esp32cam.ino
// Ferramenta de bancada para posicionar a ROI (caixa dos digitos) do hidrometro.
//
// A ESP32-CAM sobe um servidor web; no navegador do PC aparece o quadro AO VIVO,
// exatamente como o firmware de OCR o enxerga (GRAYSCALE QQVGA 160x120, mesmos
// pixels, sem JPEG). Voce desenha/arrasta a caixa com o mouse, ve as N fatias que o
// lerDigitos() vai recortar (e a entrada 28x28 de cada uma) e salva.
//
// Onde a ROI fica salva:
//   1. NVS do ESP32 (Preferences, namespace "roi"): sobrevive a reset, a deep sleep e a
//      gravar OUTRO sketch por cima (o upload do Arduino nao apaga a NVS, a menos que
//      "Erase All Flash Before Sketch Upload" esteja ligado). O transmissor_ocr_esp32cam
//      pode le-la direto: ver README.md desta pasta.
//   2. No PC: botao "Baixar JSON" (mesmo campo "caixa" de calibracao_manual/*.json) e
//      o trecho C pronto para colar.
//
// Rede:
//   - Sem credenciais: a placa cria a rede "Hidrometro-ROI" (senha "hidrometro").
//     Conecte o PC nela e abra http://192.168.4.1
//   - Com credenciais (crie wifi_local.h nesta pasta, ja esta no .gitignore):
//       #define WIFI_SSID  "minha-rede"
//       #define WIFI_SENHA "minha-senha"
//     A placa entra na sua rede; abra http://hidrometro.local ou o IP impresso na Serial.
//     Se nao conectar em 15 s, cai para o modo de rede propria acima.
//
// Compilar como os outros sketches: placa "AI Thinker ESP32-CAM", PSRAM habilitada.
// Nao precisa de bibliotecas extras (esp_http_server, Preferences e ESPmDNS vem no core).
//
// Comandos pela Serial (115200):
//   ROI       imprime a ROI salva
//   APAGAR    apaga a ROI salva
//   IP        imprime o endereco para abrir no navegador
// ============================================================
#include "esp_camera.h"
#include "esp_http_server.h"
#include <WiFi.h>
#include <ESPmDNS.h>
#include <Preferences.h>

#include "pagina.h"   // PAGINA_HTML (interface web)

#if __has_include("wifi_local.h")
#include "wifi_local.h"
#endif
#ifndef WIFI_SSID
#define WIFI_SSID  ""   // vazio = modo de rede propria (AP)
#define WIFI_SENHA ""
#endif

#define AP_SSID    "Hidrometro-ROI"
#define AP_SENHA   "hidrometro"     // minimo 8 caracteres
#define MDNS_NOME  "hidrometro"     // http://hidrometro.local (so no modo com credenciais)

// --- Pinos camera (AI Thinker ESP32-CAM), iguais ao transmissor_ocr_esp32cam ---
#define PWDN_GPIO_NUM   32
#define RESET_GPIO_NUM  -1
#define XCLK_GPIO_NUM    0
#define SIOD_GPIO_NUM   26
#define SIOC_GPIO_NUM   27
#define Y9_GPIO_NUM     35
#define Y8_GPIO_NUM     34
#define Y7_GPIO_NUM     39
#define Y6_GPIO_NUM     36
#define Y5_GPIO_NUM     21
#define Y4_GPIO_NUM     19
#define Y3_GPIO_NUM     18
#define Y2_GPIO_NUM      5
#define VSYNC_GPIO_NUM  25
#define HREF_GPIO_NUM   23
#define PCLK_GPIO_NUM   22

#define FLASH_LED_PIN    4

// Mesmo quadro do firmware de OCR: se ele mudar de resolucao, a ROI precisa ser refeita.
static const int CAM_W = 160;
static const int CAM_H = 120;
static const int N_MAX = 10;   // limite de digitos aceito pela interface

static const char* NVS_NS = "roi";

struct Roi {
  bool valida;
  int x0, y0, x1, y1;   // coordenadas no quadro 160x120 (x1/y1 exclusivos, como no lerDigitos)
  int n;                // numero de digitos (fatias)
};

static Roi roi = {false, 20, 45, 140, 75, 6};   // padrao ate salvar a primeira
static Preferences prefs;
static httpd_handle_t servidor = nullptr;
static bool flashLigado = false;

// ----------------------------------------------------------------
bool initCamera() {
  camera_config_t cfg = {};
  cfg.ledc_channel = LEDC_CHANNEL_0;
  cfg.ledc_timer   = LEDC_TIMER_0;
  cfg.pin_d0 = Y2_GPIO_NUM; cfg.pin_d1 = Y3_GPIO_NUM;
  cfg.pin_d2 = Y4_GPIO_NUM; cfg.pin_d3 = Y5_GPIO_NUM;
  cfg.pin_d4 = Y6_GPIO_NUM; cfg.pin_d5 = Y7_GPIO_NUM;
  cfg.pin_d6 = Y8_GPIO_NUM; cfg.pin_d7 = Y9_GPIO_NUM;
  cfg.pin_xclk  = XCLK_GPIO_NUM;  cfg.pin_pclk  = PCLK_GPIO_NUM;
  cfg.pin_vsync = VSYNC_GPIO_NUM; cfg.pin_href  = HREF_GPIO_NUM;
  cfg.pin_sscb_sda = SIOD_GPIO_NUM; cfg.pin_sscb_scl = SIOC_GPIO_NUM;
  cfg.pin_pwdn  = PWDN_GPIO_NUM;  cfg.pin_reset = RESET_GPIO_NUM;
  cfg.xclk_freq_hz = 20000000;

  // Mesmo formato/resolucao do transmissor_ocr_esp32cam (o que importa para a ROI).
  // So o buffer muda: 2 quadros + GRAB_LATEST para o video ao vivo nao atrasar.
  cfg.pixel_format = PIXFORMAT_GRAYSCALE;
  cfg.frame_size   = FRAMESIZE_QQVGA;
  cfg.fb_count     = 2;
  cfg.fb_location  = CAMERA_FB_IN_PSRAM;
  cfg.grab_mode    = CAMERA_GRAB_LATEST;

  esp_err_t err = esp_camera_init(&cfg);
  if (err != ESP_OK) {
    Serial.printf("[camera] erro: 0x%x\n", err);
    return false;
  }
  Serial.println("[camera] GRAYSCALE QQVGA 160x120 (igual ao firmware de OCR)");
  return true;
}

// ----------------------------------------------------------------
// ROI na NVS
void carregarRoi() {
  if (!prefs.begin(NVS_NS, true)) {   // namespace ainda nao existe: nada salvo
    roi.valida = false;
    return;
  }
  if (prefs.getBool("valida", false)) {
    roi.valida = true;
    roi.x0 = prefs.getInt("x0", roi.x0);
    roi.y0 = prefs.getInt("y0", roi.y0);
    roi.x1 = prefs.getInt("x1", roi.x1);
    roi.y1 = prefs.getInt("y1", roi.y1);
    roi.n  = prefs.getInt("n",  roi.n);
  }
  prefs.end();
}

bool salvarRoi(const Roi& r) {
  if (!prefs.begin(NVS_NS, false)) return false;
  prefs.putInt("x0", r.x0);
  prefs.putInt("y0", r.y0);
  prefs.putInt("x1", r.x1);
  prefs.putInt("y1", r.y1);
  prefs.putInt("n",  r.n);
  prefs.putBool("valida", true);   // por ultimo: so marca valida com tudo gravado
  prefs.end();
  roi = r;
  roi.valida = true;
  return true;
}

void apagarRoi() {
  if (prefs.begin(NVS_NS, false)) {
    prefs.clear();
    prefs.end();
  }
  roi.valida = false;
}

bool roiOk(const Roi& r) {
  return r.x0 >= 0 && r.y0 >= 0 && r.x1 <= CAM_W && r.y1 <= CAM_H &&
         r.n >= 1 && r.n <= N_MAX &&
         (r.x1 - r.x0) >= r.n &&       // pelo menos 1 px por fatia
         (r.y1 - r.y0) >= 2;
}

void imprimirRoi() {
  if (!roi.valida) {
    Serial.println("[roi] nenhuma ROI salva");
    return;
  }
  Serial.printf("[roi] caixa=%d,%d,%d,%d n_digitos=%d (quadro %dx%d)\n",
                roi.x0, roi.y0, roi.x1, roi.y1, roi.n, CAM_W, CAM_H);
}

int roiJson(char* buf, size_t len) {
  return snprintf(buf, len,
                  "{\"valida\":%s,\"caixa\":[%d,%d,%d,%d],\"n_digitos\":%d,\"quadro\":[%d,%d]}",
                  roi.valida ? "true" : "false",
                  roi.x0, roi.y0, roi.x1, roi.y1, roi.n, CAM_W, CAM_H);
}

// ----------------------------------------------------------------
// Handlers HTTP
static esp_err_t enviarRoiJson(httpd_req_t* req) {
  char buf[160];
  roiJson(buf, sizeof(buf));
  httpd_resp_set_type(req, "application/json");
  httpd_resp_set_hdr(req, "Cache-Control", "no-store");
  return httpd_resp_send(req, buf, HTTPD_RESP_USE_STRLEN);
}

static esp_err_t hIndex(httpd_req_t* req) {
  httpd_resp_set_type(req, "text/html; charset=utf-8");
  return httpd_resp_send(req, PAGINA_HTML, HTTPD_RESP_USE_STRLEN);
}

// Quadro cru: CAM_W*CAM_H bytes de cinza (0-255), linha a linha. O navegador desenha
// esses pixels sem compressao, iguais aos que o OCR recebe.
static esp_err_t hFrame(httpd_req_t* req) {
  camera_fb_t* fb = esp_camera_fb_get();
  if (!fb) {
    httpd_resp_send_500(req);
    return ESP_FAIL;
  }
  if (fb->width != CAM_W || fb->height != CAM_H || fb->len != (size_t)(CAM_W * CAM_H)) {
    esp_camera_fb_return(fb);
    httpd_resp_send_500(req);
    return ESP_FAIL;
  }
  httpd_resp_set_type(req, "application/octet-stream");
  httpd_resp_set_hdr(req, "Cache-Control", "no-store");
  esp_err_t r = httpd_resp_send(req, (const char*)fb->buf, fb->len);
  esp_camera_fb_return(fb);
  return r;
}

static esp_err_t hRoiGet(httpd_req_t* req) {
  return enviarRoiJson(req);
}

static bool lerCampo(const char* corpo, const char* chave, int* v) {
  char val[12];
  if (httpd_query_key_value(corpo, chave, val, sizeof(val)) != ESP_OK) return false;
  char* fim = nullptr;
  long x = strtol(val, &fim, 10);
  if (fim == val || *fim != '\0') return false;
  *v = (int)x;
  return true;
}

// Corpo x-www-form-urlencoded: x0=..&y0=..&x1=..&y1=..&n=..
static esp_err_t hRoiPost(httpd_req_t* req) {
  char corpo[128];
  int total = req->content_len;
  if (total <= 0 || total >= (int)sizeof(corpo)) {
    httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "corpo invalido");
    return ESP_FAIL;
  }
  int lido = 0;
  while (lido < total) {
    int r = httpd_req_recv(req, corpo + lido, total - lido);
    if (r == HTTPD_SOCK_ERR_TIMEOUT) continue;
    if (r <= 0) return ESP_FAIL;
    lido += r;
  }
  corpo[lido] = '\0';

  Roi nova = {};
  bool ok = lerCampo(corpo, "x0", &nova.x0) && lerCampo(corpo, "y0", &nova.y0) &&
            lerCampo(corpo, "x1", &nova.x1) && lerCampo(corpo, "y1", &nova.y1) &&
            lerCampo(corpo, "n", &nova.n);
  if (!ok || !roiOk(nova)) {
    httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "ROI fora do quadro ou campos faltando");
    return ESP_FAIL;
  }
  if (!salvarRoi(nova)) {
    httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "falha ao gravar na NVS");
    return ESP_FAIL;
  }
  Serial.print("[web] ROI salva -> ");
  imprimirRoi();
  return enviarRoiJson(req);
}

static esp_err_t hRoiApagar(httpd_req_t* req) {
  apagarRoi();
  Serial.println("[web] ROI apagada");
  return enviarRoiJson(req);
}

// POST /flash?on=1 | on=0
static esp_err_t hFlash(httpd_req_t* req) {
  char q[16], v[4];
  if (httpd_req_get_url_query_str(req, q, sizeof(q)) == ESP_OK &&
      httpd_query_key_value(q, "on", v, sizeof(v)) == ESP_OK) {
    flashLigado = (v[0] == '1');
    digitalWrite(FLASH_LED_PIN, flashLigado ? HIGH : LOW);
  }
  httpd_resp_set_type(req, "application/json");
  return httpd_resp_send(req, flashLigado ? "{\"on\":true}" : "{\"on\":false}", HTTPD_RESP_USE_STRLEN);
}

void iniciarServidor() {
  httpd_config_t cfg = HTTPD_DEFAULT_CONFIG();
  cfg.lru_purge_enable = true;   // o navegador abre varias conexoes; recicla as antigas

  if (httpd_start(&servidor, &cfg) != ESP_OK) {
    Serial.println("[web] falha ao iniciar o servidor");
    return;
  }
  httpd_uri_t rotas[] = {
    {"/",           HTTP_GET,  hIndex,     nullptr},
    {"/frame",      HTTP_GET,  hFrame,     nullptr},
    {"/roi",        HTTP_GET,  hRoiGet,    nullptr},
    {"/roi",        HTTP_POST, hRoiPost,   nullptr},
    {"/roi/apagar", HTTP_POST, hRoiApagar, nullptr},
    {"/flash",      HTTP_POST, hFlash,     nullptr},
  };
  for (auto& r : rotas) httpd_register_uri_handler(servidor, &r);
}

// ----------------------------------------------------------------
String enderecoAtual() {
  if (WiFi.getMode() == WIFI_AP) return "http://" + WiFi.softAPIP().toString();
  return "http://" + WiFi.localIP().toString() + "  (ou http://" MDNS_NOME ".local)";
}

void iniciarWifi() {
  if (strlen(WIFI_SSID) > 0) {
    WiFi.mode(WIFI_STA);
    WiFi.setSleep(false);   // sem economia de energia: o video fica bem mais fluido
    WiFi.begin(WIFI_SSID, WIFI_SENHA);
    Serial.printf("[wifi] conectando a \"%s\"", WIFI_SSID);
    unsigned long t0 = millis();
    while (WiFi.status() != WL_CONNECTED && millis() - t0 < 15000) {
      delay(300);
      Serial.print('.');
    }
    Serial.println();
    if (WiFi.status() == WL_CONNECTED) {
      if (MDNS.begin(MDNS_NOME)) MDNS.addService("http", "tcp", 80);
      return;
    }
    Serial.println("[wifi] nao conectou; criando rede propria");
    WiFi.disconnect(true);
  }

  WiFi.mode(WIFI_AP);
  WiFi.softAP(AP_SSID, AP_SENHA);
  WiFi.setSleep(false);
  Serial.printf("[wifi] rede \"%s\" senha \"%s\"\n", AP_SSID, AP_SENHA);
}

// ----------------------------------------------------------------
void setup() {
  Serial.begin(115200);
  delay(300);
  Serial.println("\n=== calibrar_roi_esp32cam ===");

  pinMode(FLASH_LED_PIN, OUTPUT);
  digitalWrite(FLASH_LED_PIN, LOW);

  if (!psramFound()) Serial.println("[AVISO] PSRAM nao encontrada: habilite PSRAM no menu Ferramentas");
  if (!initCamera()) {
    Serial.println("[ERRO] sem camera; verifique o cabo flat e a alimentacao (5 V, >= 1 A)");
  }

  carregarRoi();
  imprimirRoi();

  iniciarWifi();
  iniciarServidor();
  Serial.println("[web] abra no navegador: " + enderecoAtual());
}

void loop() {
  if (Serial.available()) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();
    cmd.toUpperCase();
    if (cmd == "ROI") {
      imprimirRoi();
    } else if (cmd == "APAGAR") {
      apagarRoi();
      Serial.println("[roi] apagada");
    } else if (cmd == "IP") {
      Serial.println("[web] " + enderecoAtual());
    } else if (cmd.length() > 0) {
      Serial.println("[?] comandos: ROI | APAGAR | IP");
    }
  }
  delay(20);
}
