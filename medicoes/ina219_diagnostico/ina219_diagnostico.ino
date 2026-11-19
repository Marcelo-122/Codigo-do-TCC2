// Diagnostico ao vivo da ligacao do INA219 no Arduino Uno (procurar mau contato).
//
// A cada 300 ms imprime uma linha dizendo o estado da ligacao naquele instante, para
// mexer nos fios e ver na hora o que muda. Nao usa biblioteca: le os registros direto.
//
//   OK      0x40 | bus 4.95 V | shunt  7.70 mV (77.0 mA)   -> modulo respondendo
//   SEM RESPOSTA | SDA=1 SCL=1                            -> barramento livre, mas ninguem
//                                                            responde: VCC/GND do modulo ou
//                                                            SDA/SCL solto/trocado
//   I2C TRAVOU   | SDA=0 SCL=1                            -> uma linha presa em 0: SDA ou SCL
//                                                            encostando no GND, ou modulo sem
//                                                            VCC segurando as linhas
//
// Ligacao: INA219 VCC->5V, GND->GND, SDA->A4, SCL->A5.
// Monitor: 115200 baud (Serial Monitor do IDE ou
//   .venv/Scripts/python -m serial.tools.miniterm COM6 115200 ; Ctrl+] sai).
// Quando estiver tudo OK, grave de volta o medicoes/ina219_logger para medir.

#include <Wire.h>

const uint8_t ENDERECO_PADRAO = 0x40;   // A0 e A1 sem jumper
const uint32_t PERIODO_MS = 300;

uint32_t contador = 0;
int8_t ultimoEstado = -1;               // para marcar as mudancas
uint32_t mudancas = 0;

bool lerRegistro(uint8_t end, uint8_t reg, uint16_t *valor) {
  Wire.beginTransmission(end);
  Wire.write(reg);
  if (Wire.endTransmission() != 0) return false;
  if (Wire.requestFrom(end, (uint8_t)2) != 2) return false;
  *valor = ((uint16_t)Wire.read() << 8) | Wire.read();
  return true;
}

int8_t procurar() {                     // endereco que respondeu entre 0x40 e 0x4F, ou -1
  for (uint8_t a = 0x40; a <= 0x4F; a++) {
    Wire.beginTransmission(a);
    if (Wire.endTransmission() == 0) return a;
  }
  return -1;
}

void setup() {
  Serial.begin(115200);
  Wire.begin();
  Wire.setClock(100000);                // devagar: mais tolerante a fio longo
  Wire.setWireTimeout(25000, true);     // nao trava com o barramento preso
  Serial.println();
  Serial.println("# diagnostico INA219: mexa nos fios e veja a linha mudar (* = mudou de estado)");
}

void loop() {
  contador++;
  Wire.clearWireTimeoutFlag();
  int8_t end = procurar();
  uint16_t rbus = 0, rshunt = 0;
  bool leu = end >= 0 && lerRegistro(end, 0x02, &rbus) && lerRegistro(end, 0x01, &rshunt);
  bool travou = Wire.getWireTimeoutFlag();

  int8_t estado = leu ? 0 : (travou ? 2 : 1);
  bool mudou = ultimoEstado >= 0 && estado != ultimoEstado;
  if (mudou) mudancas++;
  ultimoEstado = estado;

  char linha[96];
  if (leu) {
    float bus_V = (rbus >> 3) * 0.004f;
    float shunt_mV = (int16_t)rshunt * 0.01f;
    char sb[8], ss[9], si[9];
    dtostrf(bus_V, 5, 2, sb);
    dtostrf(shunt_mV, 6, 2, ss);
    dtostrf(shunt_mV * 10.0f, 6, 1, si);  // shunt de 0,1 ohm: mA = mV * 10
    snprintf(linha, sizeof(linha), "OK      0x%02X | bus %s V | shunt %s mV (%s mA)", end, sb, ss, si);
  } else {
    // Linhas em repouso devem estar em 1 (pull-up). 0 = presa no GND ou modulo sem VCC.
    int sda = digitalRead(SDA), scl = digitalRead(SCL);
    snprintf(linha, sizeof(linha), "%s | SDA=%d SCL=%d",
             travou ? "I2C TRAVOU  " : "SEM RESPOSTA", sda, scl);
  }
  Serial.print(mudou ? "* " : "  ");
  Serial.print(contador);
  Serial.print("  ");
  Serial.print(linha);
  Serial.print("  [mudancas: ");
  Serial.print(mudancas);
  Serial.println("]");
  delay(PERIODO_MS);
}
