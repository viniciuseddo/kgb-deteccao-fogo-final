// Aritmetica de tempo monotonico em uint32 (millis), segura na virada de 2^32.
#pragma once
#include <stdint.h>

namespace vigia {

// Diferenca com sinal: positivo se 'a' esta depois de 'b'. Valida para
// intervalos menores que ~24 dias, muito acima de qualquer prazo daqui.
inline int32_t dif_ms(uint32_t a, uint32_t b) { return (int32_t)(a - b); }

// 'agora' alcancou ou passou 'limite'.
inline bool alcancou(uint32_t agora, uint32_t limite) { return dif_ms(agora, limite) >= 0; }

// Quanto falta ate 'limite' (0 se ja passou).
inline uint32_t restante(uint32_t agora, uint32_t limite) {
  int32_t d = dif_ms(limite, agora);
  return d > 0 ? (uint32_t)d : 0u;
}

// O mais tardio de dois instantes.
inline uint32_t mais_tarde(uint32_t a, uint32_t b) { return dif_ms(a, b) >= 0 ? a : b; }

}  // namespace vigia
