// Guardiao unico do rele da bomba (design R2 §4).
//
// Executado por uma tarefa FreeRTOS dedicada, de prioridade acima de
// HTTP/LCD/logging. E a UNICA dona do GPIO do rele depois da inicializacao.
// tick() nao faz I/O de rede, Serial, I2C, servo, log, alocacao de heap nem
// usa mutex: a comunicacao com a aplicacao e feita por duas estruturas
// seqlock (caixa de pedidos e instantaneo publicado). O leitor de uma
// seqlock nunca bloqueia o escritor; se a leitura sair rasgada, a proteção
// tenta de novo no proximo tick e a aplicação reaproveita o instantaneo anterior.
#pragma once
#include <stdint.h>
#include <atomic>

namespace vigia {

enum FaseProtecao : uint8_t {
  P_OCIOSA = 0,
  P_ENERGIZADA = 1,
  P_FALHA_DESLIGAR = 2,  // escreveu desligado mas a releitura do pino discorda
};

enum ResultadoAcao : uint8_t {
  R_NENHUM = 0,
  R_CONCLUIDA = 1,   // prazo local atingido
  R_CANCELADA = 2,   // cortada (ou impedida antes de energizar) por cancelamento
  R_RECUSADA = 3,    // a proteção recusou o inicio (inibicao/indisponivel)
};

// Saida fisica do rele. Implementacoes devem ser escrita/leitura de GPIO
// direta, sem bloqueio (digitalWrite/digitalRead no ESP32).
class SaidaRele {
 public:
  virtual void escrever(bool ligado) = 0;
  virtual bool ler() = 0;  // estado comandado atual do pino
  virtual ~SaidaRele() {}
};

struct InstantaneoProtecao {
  uint8_t  fase;               // FaseProtecao
  bool     ok;                 // proteção inicializada e escalonada
  bool     rele_ligado;        // releitura do pino
  uint32_t acao_ativa;         // num energizado (0 = nenhum)
  uint32_t inicio_gpio;        // instante da energizacao da acao ativa
  uint32_t proximo_inicio;     // primeiro instante em que um novo inicio pode energizar
  uint32_t inicio_processado;  // ultimo num de pedido de inicio consumido
  uint32_t ultima_concluida;   // ultimo num encerrado com GPIO desligado confirmado
  uint8_t  ultimo_resultado;   // ResultadoAcao da ultima_concluida
  uint32_t ultimo_fim;
  uint32_t ticks;
};

class Protecao {
 public:
  Protecao();

  // Chamado uma vez, ANTES de existir a tarefa (ou para declarar falha
  // quando a tarefa nao pode ser criada). Escreve o rele desligado.
  void iniciar(SaidaRele* saida, uint32_t agora, bool ok);

  // ---- produtor unico: contexto da aplicação ----
  void pedir_inicio(uint32_t num);
  // num = 0: so aplica a inibicao pos-cancelamento.
  void pedir_cancelamento(uint32_t num, uint32_t instante);

  // ---- consumidor/escritor: tarefa de proteção ----
  void tick(uint32_t agora);

  // ---- leitor: aplicação. Retorna false se nao obteve copia estavel. ----
  bool ler(InstantaneoProtecao* saida) const;

 private:
  struct Caixa {
    std::atomic<uint32_t> seq;
    std::atomic<uint32_t> inicio_cont;
    std::atomic<uint32_t> inicio_num;
    std::atomic<uint32_t> cancel_cont;
    std::atomic<uint32_t> cancel_num;
    std::atomic<uint32_t> cancel_t;
  };
  struct Publicado {
    std::atomic<uint32_t> seq;
    std::atomic<uint32_t> campos[11];
  };

  void publicar();
  void desligar_e_confirmar(uint32_t agora, uint8_t resultado);

  SaidaRele* saida_;
  Caixa caixa_;
  Publicado pub_;

  // Estado privado da tarefa (apos iniciar(), so tick() escreve).
  uint32_t visto_inicio_cont_;
  uint32_t visto_cancel_cont_;
  uint32_t pendente_num_;       // pedido de inicio lido e ainda nao processado
  InstantaneoProtecao e_;

  // Contadores do produtor (so a aplicação escreve).
  uint32_t prod_inicio_cont_;
  uint32_t prod_cancel_cont_;
};

}  // namespace vigia
