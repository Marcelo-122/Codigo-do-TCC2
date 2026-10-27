// ============================================================
// ina219_logger.ino
// Registra a corrente do no (ESP32-CAM + Radioenge) lendo um INA219 e manda
// pela Serial linhas "t_us,shunt_mV,bus_V" (CSV). Quem processa e
// medicoes/corrente.py.
//
// Roda numa SEGUNDA placa, nunca na ESP32-CAM que esta sendo medida. Usado com um
// Arduino Uno; tambem compila para ESP32. Biblioteca: "Adafruit INA219" (Library Manager).
//
// Ligacao (ver medicoes/medir_corrente.md):
//   Uno:   INA219 VCC -> 5V    GND -> GND (e do no)    SDA -> A4    SCL -> A5
//   ESP32: INA219 VCC -> 3V3   GND -> GND (e do no)    SDA -> SDA_PIN    SCL -> SCL_PIN
//          (ESP32-S3: GPIO8/GPIO9, padrao do Wire. ESP32 classico: troque para 21/22.)
//   Fonte + -> Vin+   |   Vin- -> alimentacao do no   |   Fonte - -> GND do no
//
// A corrente NAO sai do registrador de corrente: sai da tensao do shunt
// (passo fixo de 10 uV), que com 0,1 ohm da 0,1 mA por passo. O calculo
// I = shunt_mV / 0,1 ohm e feito no script.
// ============================================================
#include <Wire.h>
#include <Adafruit_INA219.h>

// Periodo entre amostras. Uma conversao do INA219 (12 bits, sem media) leva ~0,53 ms
// por canal; 2 ms evita ler a mesma conversao duas vezes. 500 amostras/s (ESP32, 921600
// baud) cobrem os ~136 ms de cada pacote LoRa. No Arduino Uno (115200 baud) o periodo e de
// 10 ms (100 amostras/s); pinos, baud e periodo sao escolhidos abaixo pela placa. Capture
// com "corrente.py capturar <porta> <csv> --baud 115200".
#if defined(ARDUINO_ARCH_ESP32)
const uint32_t PERIODO_US = 2000;
const uint32_t BAUD = 921600;
const int SDA_PIN = 8;         // ESP32-S3; ESP32 classico: 21
const int SCL_PIN = 9;         // ESP32-S3; ESP32 classico: 22
#else
// Arduino Uno: SDA = A4, SCL = A5 (pinos fixos do Wire)
const uint32_t PERIODO_US = 10000;
const uint32_t BAUD = 115200;
#endif

Adafruit_INA219 ina;
uint32_t proximo = 0;

void setup() {
  Serial.begin(BAUD);
#if defined(ARDUINO_ARCH_ESP32)
  Wire.begin(SDA_PIN, SCL_PIN);
#else
  Wire.begin();
#endif
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
