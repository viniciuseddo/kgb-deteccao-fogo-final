// Parametros da variante DualSense do Vigia (design R2, tabela de parametros).
// Valores iniciais aprovados para desenvolvimento; NAO sao calibracao fisica.
#pragma once
#include <stdint.h>

namespace vigia {

// ------------------------------------------------------------- protocolo
static const int      PROTOCOLO_V          = 1;
static const char     FW_NOME[]            = "vigia-dualsense-0.1";

// ------------------------------------------------------------- bomba
static const uint32_t PRAZO_AGUA_MS        = 5000;   // desde a energizacao GPIO
static const uint32_t COOLDOWN_MS          = 12000;  // entre INICIOS energizados
static const uint32_t INIBICAO_BOOT_MS     = 12000;
static const uint32_t INIBICAO_CANCEL_MS   = 12000;

// ------------------------------------------------------------- arbitragem
static const uint32_t LEASE_MS             = 1500;
static const uint32_t JANELA_MS            = 500;
static const uint32_t VEL_VALIDADE_MS      = 500;
static const int32_t  VEL_MAX_MDPS         = 30000;  // 30 graus/s em milesimos
static const uint32_t DEDUP_RETENCAO_MS    = 120000;
static const int      DEDUP_CAPACIDADE     = 32;
static const int      ABERTURAS_GUARDADAS  = 8;
static const uint32_t SILENCIO_COMPAT_MS   = 8000;   // regra legada, so no perfil COMPAT

// ------------------------------------------------------------- PAN (graus)
static const int PAN_MIN      = 10;
static const int PAN_MAX      = 170;
static const int PAN_ESQUERDA = 150;   // limite superior da varredura
static const int PAN_CENTRO   = 90;
static const int PAN_DIREITA  = 30;    // limite inferior da varredura
static const int PASSO_AJUSTE = 10;    // letras 4 / 6

static const int32_t VARRE_MDPS          = 55555;  // ~1 grau / 18 ms, como o original
static const int32_t RETORNO_FAIXA_MDPS  = 30000;  // volta gradual para a faixa
static const int32_t LEGADO_MOVE_MDPS    = 125000; // ~1 grau / 8 ms, como moveSuave
static const uint32_t PASSO_MAX_MS       = 100;    // nao integra saltos maiores que isso

// ------------------------------------------------------------- limites de texto
static const int CORPO_MAX     = 512;
static const int ID_MAX        = 32;
static const int RESPOSTA_MAX  = 1024;

}  // namespace vigia
