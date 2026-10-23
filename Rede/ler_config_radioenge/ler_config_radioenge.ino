// ler_config_radioenge.ino
//
// Consulta o módulo Radioenge RD49C pela UART da ESP32-CAM e mostra no Monitor
// Serial (115200 baud) o DevAddr, a NwkSKey, a AppSKey e o modo de ativação.
//
// Comandos enviados (formato "=?" = leitura, conforme o manual da Radioenge):
//   AT+DADDR=?     DevAddr  (4 bytes)
//   AT+NWKSKEY=?   NwkSKey  (16 bytes)
//   AT+APPSKEY=?   AppSKey  (16 bytes)
//   AT+NJM=?       0 = ABP, 1 = OTAA
//
// Uso: grave na ESP32-CAM (placa "AI Thinker ESP32-CAM"), abra o Monitor Serial
// em 115200 baud e veja a saída. Para consultar de novo, envie qualquer
// caractere (por exemplo "r") pelo Monitor Serial.
//
// ATENÇÃO: este sketch imprime CHAVES SECRETAS no Monitor Serial. Não cole a
// saída em chats, issues ou commits. Copie os valores só para o seu .env.
//
// Ligação (a mesma do transmissor_esp32cam):
//   GPIO 15 (RX da ESP32-CAM) <- TX do Radioenge (pino 3)
//   GPIO 14 (TX da ESP32-CAM) -> RX do Radioenge (pino 2)

#define LORA_RX_PIN 15 // Connected to Radioenge TX (Pino 3)
#define LORA_TX_PIN 14 // Connected to Radioenge RX (Pino 2)

HardwareSerial LoRaSerial(1);

const unsigned long TIMEOUT_TOTAL_MS = 3000;   // espera máxima por comando
const unsigned long SILENCIO_FIM_MS  = 400;    // sem bytes por este tempo = resposta completa

const char *COMANDOS[] = {
  "AT+DADDR=?",
  "AT+NWKSKEY=?",
  "AT+APPSKEY=?",
  "AT+NJM=?",
};
const int N_COMANDOS = sizeof(COMANDOS) / sizeof(COMANDOS[0]);

// Envia um comando AT e devolve a resposta bruta (sem espaços nas pontas).
String consultar(const char *cmd) {
  while (LoRaSerial.available()) LoRaSerial.read(); // descarta lixo pendente
  LoRaSerial.println(cmd);

  String resposta = "";
  unsigned long inicio = millis();
  unsigned long ultimoByte = 0;

  while (millis() - inicio < TIMEOUT_TOTAL_MS) {
    while (LoRaSerial.available()) {
      resposta += (char)LoRaSerial.read();
      ultimoByte = millis();
    }
    if (resposta.length() > 0 && millis() - ultimoByte > SILENCIO_FIM_MS) break;
    delay(5);
  }
  resposta.trim();
  return resposta;
}

void lerTudo() {
  Serial.println();
  Serial.println("=== Configuração do Radioenge ===");
  for (int i = 0; i < N_COMANDOS; i++) {
    String r = consultar(COMANDOS[i]);
    Serial.print(COMANDOS[i]);
    Serial.print("  ->  ");
    if (r.length() == 0) {
      Serial.println("(sem resposta: confira a fiação, o baud 9600 e a alimentação do módulo)");
    } else {
      r.replace("\r", " ");
      r.replace("\n", " ");
      Serial.println(r);
    }
  }
  Serial.println("=== Fim. Envie qualquer caractere para consultar de novo ===");
}

void setup() {
  Serial.begin(115200);
  LoRaSerial.begin(9600, SERIAL_8N1, LORA_RX_PIN, LORA_TX_PIN);
  delay(2000); // dá tempo de abrir o Monitor Serial e do módulo iniciar
  lerTudo();
}

void loop() {
  if (Serial.available()) {
    while (Serial.available()) Serial.read();
    lerTudo();
  }
}
