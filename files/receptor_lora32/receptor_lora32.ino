#include <SPI.h>
#include <LoRa.h>

// Pinos internos padronizados para LoRa32 V2 (TTGO/Heltec)
#define ss 18
#define rst 14
#define dio0 26

// Canal 64 do plano AU915 (primeiro canal de 500 kHz) = 915.9 MHz.
// Enquadramento pretendido: item 10.3 do Ato 14448/Anatel (sequência
// direta/outras técnicas de modulação digital) - exige BW >= 500 kHz,
// mas NAO exige hopping entre múltiplos canais (diferente do item 10.2).
// Por isso aqui usamos frequência FIXA, sem varredura.
const long FREQ_HZ = 915900000;

void setup() {
  Serial.begin(115200);
  while (!Serial); // Aguarda a porta serial estabilizar

  Serial.println("Iniciando Receptor LoRa - TCC (canal fixo 500 kHz)");

  LoRa.setPins(ss, rst, dio0);

  if (!LoRa.begin(FREQ_HZ)) {
    Serial.println("Falha de hardware: Rádio LoRa não encontrado!");
    while (1);
  }

  // Parâmetros ajustados para bater com o uplink do módulo Radioenge (RD49C)
  // configurado em DR6 (AT+DR=6) = SF8 / BW 500 kHz no plano AU915.
  LoRa.setSpreadingFactor(8);     // SF8 (equivalente ao DR6 do Radioenge)
  LoRa.setSignalBandwidth(500E3); // Banda de 500 kHz
  LoRa.setSyncWord(0x34);         // Sync Word 0x34 (padrão público LoRaWAN)

  Serial.println("LoRa iniciado. Escutando em 915.9 MHz (SF8/BW500), canal fixo...");
}

void loop() {
  int packetSize = LoRa.parsePacket();

  if (packetSize) {
    // Formato: HEX:<bytes>|RSSI:<valor>
    Serial.print("HEX:");
    while (LoRa.available()) {
      int b = LoRa.read();
      if (b < 0x10) Serial.print('0');
      Serial.print(b, HEX);
    }
    Serial.print("|RSSI:");
    Serial.println(LoRa.packetRssi());
  }
}
