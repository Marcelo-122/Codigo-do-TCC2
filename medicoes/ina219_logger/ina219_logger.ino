// ============================================================
// ina219_logger.ino
// Registra a corrente do no (ESP32-CAM + Radioenge) lendo um INA219 e manda
// pela Serial linhas "t_us,shunt_mV,bus_V" (CSV). Quem processa e
// medicoes/corrente.py.
//
// Roda numa SEGUNDA placa (um ESP32 qualquer, p.ex. DevKit), nunca na ESP32-CAM
// que esta sendo medida. Biblioteca: "Adafruit INA219" (Library Manager).
//
// Ligacao (ver medicoes/medir_corrente.md):
//   INA219 VCC -> 3V3 do logger     INA219 GND -> GND do logger (e do no)
//   INA219 SDA -> GPIO21            INA219 SCL -> GPIO22   (padrao do Wire no ESP32)
//   Fonte + -> Vin+   |   Vin- -> alimentacao do no   |   Fonte - -> GND do no
//
// A corrente NAO sai do registrador de corrente: sai da tensao do shunt
// (passo fixo de 10 uV), que com 0,1 ohm da 0,1 mA por passo. O calculo
// I = shunt_mV / 0,1 ohm e feito no script.
// ============================================================
#include <Wire.h>
#include <Adafruit_INA219.h>

// Periodo entre amostras. Uma conversao do INA219 (12 bits, sem media) leva ~0,53 ms
// por canal; 2 ms evita ler a mesma conversao duas vezes. 500 amostras/s cobrem
// os ~136 ms de cada pacote LoRa. Em Arduino Uno (115200 baud) use PERIODO_US = 10000.
const uint32_t PERIODO_US = 2000;
const uint32_t BAUD = 921600;  // Uno: 115200

Adafruit_INA219 ina;
uint32_t proximo = 0;

void setup() {
  Serial.begin(BAUD);
  Wire.begin();
  Wire.setClock(400000);
  if (!ina.begin()) {
    Serial.println("# INA219 nao encontrado: confira SDA/SCL/VCC/GND");
    while (true) delay(1000);
  }
  ina.setCalibration_32V_2A();  // PGA /8 (ate 320 mV no shunt): nao satura nos picos de TX
  Serial.println("# ina219_logger: shunt 0,1 ohm; t_us e micros() (zera a cada ~71 min)");
  Serial.println("t_us,shunt_mV,bus_V");
  proximo = micros();
}

void loop() {
  uint32_t agora = micros();
  if ((int32_t)(agora - proximo) < 0) return;
  proximo = agora + PERIODO_US;  // sem "recuperar" amostras atrasadas

  float shunt_mV = ina.getShuntVoltage_mV();
  float bus_V = ina.getBusVoltage_V();  // tensao depois do shunt (Vin-)

  Serial.print(agora);
  Serial.print(',');
  Serial.print(shunt_mV, 2);
  Serial.print(',');
  Serial.println(bus_V, 3);
}
