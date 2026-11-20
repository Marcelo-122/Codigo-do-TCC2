// ============================================================
// medir_cpu.h - uso de CPU por nucleo, frequencia e pico de memoria de cada ciclo.
// O mesmo arquivo esta em transmissor_esp32cam/ e transmissor_ocr_esp32cam/ (o Arduino so enxerga
// a pasta do sketch); se mudar um, copie para o outro.
//
// Desligado por padrao (MEDIR_CPU 0): com ele ligado, a tarefa idle nao executa o WAITI e o no gasta
// mais corrente acordado, entao as medicoes de energia usam o firmware sem ele. Para medir, compile com
//   arduino-cli compile -b esp32:esp32:esp32cam --build-property "build.defines=-DMEDIR_CPU=1" ...
// e use o medicoes/medir_cpu.py, que le a linha [CPU_FIM] impressa antes de cada [CICLO_FIM].
//
// Como mede o uso: as bibliotecas do core 3.0.7 vem sem as estatisticas de tempo de execucao do
// FreeRTOS, entao o uso e estimado pela tarefa idle de cada nucleo. Um gancho de idle que devolve false
// faz a idle girar sem dormir, contando voltas. No power-on, com os dois nucleos livres por
// CPU_CALIBRA_MS, mede-se a taxa ociosa (voltas/s) de cada nucleo, guardada na RTC (sobrevive ao deep
// sleep). Num intervalo de s segundos com v voltas: uso = 1 - v / (taxa * s). Interrupcoes contam como
// uso, e a precisao e de alguns pontos percentuais.
//
// Frequencia: getCpuFrequencyMhz()/getApbFrequency(). As bibliotecas do core 3.0.7 vem sem o
// CONFIG_PM_ENABLE (sem DFS), entao a frequencia nao muda durante o ciclo; a linha imprime "pm=0/1"
// para confirmar.
//
// Memoria: pico do ciclo = total - menor livre desde o boot (heap_caps_get_minimum_free_size), para a
// PSRAM e para a RAM interna. Como o ESP32 reinicia a cada despertar, o pico e o do ciclo.
// ============================================================
#pragma once
#ifndef MEDIR_CPU
#define MEDIR_CPU 0
#endif

#if MEDIR_CPU
#include "esp_freertos_hooks.h"
#include "esp_heap_caps.h"
#include "esp_timer.h"
#include "esp32-hal-cpu.h"
#include "sdkconfig.h"

static const uint32_t CPU_CALIBRA_MS = 1000;

static volatile uint32_t cpuVoltas[2] = {0, 0};
RTC_DATA_ATTR static uint32_t cpuTaxa[2] = {0, 0};   // voltas/s com o nucleo ocioso (0 = nao calibrado)

static bool cpuIdle0() { cpuVoltas[0]++; return false; }
static bool cpuIdle1() { cpuVoltas[1]++; return false; }

struct CpuMarca { int64_t t_us; uint32_t v[2]; };

static CpuMarca cpuMarca() {
  CpuMarca m;
  m.t_us = esp_timer_get_time();
  m.v[0] = cpuVoltas[0];
  m.v[1] = cpuVoltas[1];
  return m;
}

// Uso (%) do nucleo entre duas marcas; -1 se nao calibrado ou intervalo nulo.
static float cpuUso(const CpuMarca& a, const CpuMarca& b, int nucleo) {
  double s = (double)(b.t_us - a.t_us) / 1e6;
  if (s <= 0 || cpuTaxa[nucleo] == 0) return -1;
  double u = 1.0 - (double)(uint32_t)(b.v[nucleo] - a.v[nucleo]) / ((double)cpuTaxa[nucleo] * s);
  if (u < 0) u = 0;
  if (u > 1) u = 1;
  return (float)(100.0 * u);
}

static CpuMarca cpuInicio, cpuUltima;
static char cpuFases[320];
static int cpuFasesLen = 0;

// Zera a contagem do ciclo (o setup() chama via cpuIniciar; o AUTO pela serial chama de novo, para o
// primeiro ciclo nao contar a espera pelo comando).
static void cpuReiniciar() {
  cpuInicio = cpuUltima = cpuMarca();
  cpuFasesLen = 0;
  cpuFases[0] = '\0';
}

// Registra os ganchos e, so no power-on, calibra a taxa ociosa. Chamar no comeco do setup().
static void cpuIniciar() {
  esp_register_freertos_idle_hook_for_cpu(cpuIdle0, 0);
  esp_register_freertos_idle_hook_for_cpu(cpuIdle1, 1);
  if (cpuTaxa[0] == 0 || cpuTaxa[1] == 0) {
    CpuMarca a = cpuMarca();
    vTaskDelay(pdMS_TO_TICKS(CPU_CALIBRA_MS));   // o loopTask para; os dois nucleos ficam livres
    CpuMarca b = cpuMarca();
    double s = (double)(b.t_us - a.t_us) / 1e6;
    cpuTaxa[0] = (uint32_t)((uint32_t)(b.v[0] - a.v[0]) / s);
    cpuTaxa[1] = (uint32_t)((uint32_t)(b.v[1] - a.v[1]) / s);
  }
  cpuReiniciar();
}

// Fecha a fase que comecou na marca anterior: " nome=uso0/uso1/ms".
static void cpuFase(const char* nome) {
  CpuMarca m = cpuMarca();
  if (cpuFasesLen < (int)sizeof(cpuFases) - 40) {
    cpuFasesLen += snprintf(cpuFases + cpuFasesLen, sizeof(cpuFases) - cpuFasesLen, " %s=%.1f/%.1f/%lu",
                            nome, cpuUso(cpuUltima, m, 0), cpuUso(cpuUltima, m, 1),
                            (unsigned long)((m.t_us - cpuUltima.t_us) / 1000));
  }
  cpuUltima = m;
}

static void cpuImprimir(uint32_t ciclo) {
  CpuMarca m = cpuMarca();
  float u0 = cpuUso(cpuInicio, m, 0), u1 = cpuUso(cpuInicio, m, 1);
  unsigned long ms = (unsigned long)((m.t_us - cpuInicio.t_us) / 1000);
#ifdef CONFIG_PM_ENABLE
  const int pm = 1;
#else
  const int pm = 0;
#endif
  size_t psTot = heap_caps_get_total_size(MALLOC_CAP_SPIRAM);
  size_t psMin = heap_caps_get_minimum_free_size(MALLOC_CAP_SPIRAM);
  size_t inTot = heap_caps_get_total_size(MALLOC_CAP_INTERNAL);
  size_t inMin = heap_caps_get_minimum_free_size(MALLOC_CAP_INTERNAL);
  Serial.printf("[CPU_FIM] ciclo=%u f_cpu_mhz=%u f_apb_mhz=%u f_xtal_mhz=%u pm=%d taxa0=%u taxa1=%u "
                "t_ms=%lu uso0=%.1f uso1=%.1f ocupado0_ms=%lu ocupado1_ms=%lu "
                "psram_total=%u psram_pico=%u interna_total=%u interna_pico=%u fases:%s\n",
                (unsigned)ciclo, (unsigned)getCpuFrequencyMhz(), (unsigned)(getApbFrequency() / 1000000),
                (unsigned)getXtalFrequencyMhz(), pm, (unsigned)cpuTaxa[0], (unsigned)cpuTaxa[1], ms, u0, u1,
                (unsigned long)(u0 * ms / 100), (unsigned long)(u1 * ms / 100),
                (unsigned)psTot, (unsigned)(psTot - psMin), (unsigned)inTot, (unsigned)(inTot - inMin), cpuFases);
}
#else
static inline void cpuIniciar() {}
static inline void cpuReiniciar() {}
static inline void cpuFase(const char*) {}
static inline void cpuImprimir(uint32_t) {}
#endif
