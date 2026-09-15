#define LORA_RX_PIN 15 // Connected to Radioenge TX (Pino 3)
#define LORA_TX_PIN 14 // Connected to Radioenge RX (Pino 2)

HardwareSerial LoRaSerial(1);

// Intervalo entre envios (ms).
//
// IMPORTANTE: este valor depende de qual configuração do Radioenge estamos
// testando - o CHMASK e o AT+DR precisam bater com o cenário:
//
// (A) CHMASK=FFFF:FFFF:0007:0000:0000:0000 + AT+DR=5 (35 canais, 125 kHz,
//     hopping real - item 10.2.5.2 do Ato 14448): 2000 ms dá margem
//     confortável acima do piso regulatório (~215 ms de dwell por canal).
//
// (B) CHMASK=0000:0000:0000:0000:0001:0000 + AT+DR=6 (canal 64 fixo,
//     915.9 MHz, 500 kHz, sem hopping - hipótese do item 10.3 do Ato 14448):
//     o item 10.3 não define um intervalo mínimo entre transmissões (só
//     limites de potência e densidade espectral). Mantemos 2000 ms mesmo
//     assim por prudência prática (tempo do módulo processar cada AT+SENDB),
//     não por exigência regulatória nesse cenário, pode reduzir se quiser
//     testar mais rápido.
//
// NUNCA use um CHMASK de poucos canais (menos de 35) com BW=125kHz - isso
// não se enquadra em nenhum dos dois itens.
const unsigned long SAFE_INTERVAL_MS = 2000;

String toHexAscii(const String &s) {
  String hex = "";
  char buf[3];
  for (size_t i = 0; i < s.length(); i++) {
    sprintf(buf, "%02X", (unsigned char)s[i]);
    hex += buf;
  }
  return hex;
}

// Stub: troque pelo dado real do seu chunk (ex: pedaço da imagem em hex).
// Centralizado aqui pra SENDALL e RESEND usarem a mesma fonte de dados.
String getChunkDataHex(int index) {
  return "E07AD003BEEF4E3DEA29246DA7CB1C7AD0322177B130ABF37AD562E58F26801452E690C5A2800A7C6FB5B3923E94089EE6E92";
}

void sendChunk(int index, int total, const String &dataHex) {
  const int MAX_TENTATIVAS = 5;
  String msg = "CHUNK, " + String(index) + ", " + String(total) + ", " + dataHex;
  String cmd = "AT+SENDB=01:" + toHexAscii(msg);

  for (int tentativa = 1; tentativa <= MAX_TENTATIVAS; tentativa++) {
    while (LoRaSerial.available()) LoRaSerial.read(); // limpa lixo pendente

    LoRaSerial.println(cmd);
    Serial.print("-> ");
    Serial.println(cmd);

    // Espera a resposta real do módulo (TX_OK ou algum tipo de ERROR),
    // em vez de só esperar um tempo fixo cego.
    String resposta = "";
    unsigned long start = millis();
    while (millis() - start < 2000) {
      if (LoRaSerial.available()) {
        char c = LoRaSerial.read();
        Serial.write(c);
        resposta += c;
        if (resposta.indexOf("OK") != -1 || resposta.indexOf("ERROR") != -1) {
          delay(50); // pega o resto da linha
          while (LoRaSerial.available()) {
            char c2 = LoRaSerial.read();
            Serial.write(c2);
            resposta += c2;
          }
          break;
        }
      }
    }

    bool sucesso = (resposta.indexOf("TX_OK") != -1) ||
                   (resposta.indexOf("OK") != -1 && resposta.indexOf("ERROR") == -1);

    // Debug: mostra a resposta bruta completa do módulo, separada do stream
    // ao vivo acima. Se o Radioenge reportar canal/frequência em algum campo
    // aqui, vai aparecer nessa linha
    Serial.print("[resposta bruta do modulo]: ");
    Serial.println(resposta);

    if (sucesso) return; // chunk realmente saiu, pode seguir pro próximo

    Serial.print("[aviso] chunk ");
    Serial.print(index);
    Serial.print(" - modulo ocupado (tentativa ");
    Serial.print(tentativa);
    Serial.println("), tentando de novo...");
    delay(SAFE_INTERVAL_MS); // espera mais um ciclo antes de tentar de novo
  }

  Serial.print("[ERRO] chunk ");
  Serial.print(index);
  Serial.println(" falhou apos varias tentativas - confira manualmente!");
}

void setup() {
  Serial.begin(115200);
  LoRaSerial.begin(9600, SERIAL_8N1, LORA_RX_PIN, LORA_TX_PIN);

  delay(1000);
  Serial.println("ESP32-CAM to Radioenge Bridge Ready.");
  Serial.println("Digite comandos AT normalmente,");
  Serial.println("'SENDALL:<quantidade>' para enviar o lote inteiro,");
  Serial.println("ou 'RESEND:<indices separados por virgula>' para reenviar so os que faltaram.");
}

void loop() {
  // Bridge normal: qualquer coisa que o Radioenge mandar, repassa pro PC
  while (LoRaSerial.available()) {
    Serial.write(LoRaSerial.read());
  }

  if (Serial.available()) {
    String linha = Serial.readStringUntil('\n');
    linha.trim();

    if (linha.startsWith("SENDALL:")) {
      int total = linha.substring(8).toInt();
      Serial.print("Enviando lote completo de ");
      Serial.print(total);
      Serial.println(" chunks, respeitando o intervalo configurado...");

      for (int i = 1; i <= total; i++) {
        sendChunk(i, total, getChunkDataHex(i));
        delay(SAFE_INTERVAL_MS);
      }

      Serial.println("Envio concluido.");
    } else if (linha.startsWith("RESEND:")) {
      // Ex: "RESEND:2,7,15,23" reenvia so esses indices (o 'total' usado na
      // mensagem CHUNK precisa bater com o do lote original - ajuste TOTAL_ORIGINAL).
      const int TOTAL_ORIGINAL = 50; // <-- ajuste para o total do lote 

      String lista = linha.substring(7);
      Serial.print("Reenviando indices: ");
      Serial.println(lista);

      int start = 0;
      while (start < (int)lista.length()) {
        int comma = lista.indexOf(',', start);
        String token = (comma == -1) ? lista.substring(start) : lista.substring(start, comma);
        token.trim();
        if (token.length() > 0) {
          int idx = token.toInt();
          sendChunk(idx, TOTAL_ORIGINAL, getChunkDataHex(idx));
          delay(SAFE_INTERVAL_MS);
        }
        if (comma == -1) break;
        start = comma + 1;
      }

      Serial.println("Reenvio concluido.");
    } else if (linha.startsWith("SEND:")) {
      // Formato: SEND:<indice>:<total>:<dados-hex>
      // Usado pelo orquestrador no PC, que já sabe (via decode_lorawan.py)
      // o que falta e manda exatamente o chunk que quer, com o dado real.
      String resto = linha.substring(5);
      int p1 = resto.indexOf(':');
      int p2 = (p1 == -1) ? -1 : resto.indexOf(':', p1 + 1);
      if (p1 == -1 || p2 == -1) {
        Serial.println("[ERRO] formato invalido. Use SEND:<indice>:<total>:<dados-hex>");
      } else {
        int idx = resto.substring(0, p1).toInt();
        int total = resto.substring(p1 + 1, p2).toInt();
        String dataHex = resto.substring(p2 + 1);
        sendChunk(idx, total, dataHex);
      }
    } else {
      // Comando AT normal, repassa direto pro Radioenge
      LoRaSerial.println(linha);
    }
  }
}
