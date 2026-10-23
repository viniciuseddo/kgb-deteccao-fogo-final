#include "vigia_protecao.h"
#include "vigia_config.h"
#include "vigia_tempo.h"

namespace vigia {

Protecao::Protecao()
    : saida_(nullptr), visto_inicio_cont_(0), visto_cancel_cont_(0), pendente_num_(0),
      prod_inicio_cont_(0), prod_cancel_cont_(0) {
  caixa_.seq.store(0);
  caixa_.inicio_cont.store(0);
  caixa_.inicio_num.store(0);
  caixa_.cancel_cont.store(0);
  caixa_.cancel_num.store(0);
  caixa_.cancel_t.store(0);
  pub_.seq.store(0);
  for (auto& c : pub_.campos) c.store(0);
  e_ = InstantaneoProtecao();
}

void Protecao::iniciar(SaidaRele* saida, uint32_t agora, bool ok) {
  saida_ = saida;
  if (saida_) saida_->escrever(false);
  e_ = InstantaneoProtecao();
  e_.fase = P_OCIOSA;
  e_.ok = ok && saida_ != nullptr;
  e_.rele_ligado = saida_ ? saida_->ler() : false;
  e_.proximo_inicio = agora + INIBICAO_BOOT_MS;
  e_.ultimo_resultado = R_NENHUM;
  visto_inicio_cont_ = caixa_.inicio_cont.load(std::memory_order_relaxed);
  visto_cancel_cont_ = caixa_.cancel_cont.load(std::memory_order_relaxed);
  pendente_num_ = 0;
  publicar();
}

// ------------------------------------------------------- produtor (app)
void Protecao::pedir_inicio(uint32_t num) {
  uint32_t s = caixa_.seq.load(std::memory_order_relaxed);
  caixa_.seq.store(s + 1, std::memory_order_relaxed);  // impar: escrevendo
  std::atomic_thread_fence(std::memory_order_release);
  caixa_.inicio_num.store(num, std::memory_order_relaxed);
  caixa_.inicio_cont.store(++prod_inicio_cont_, std::memory_order_relaxed);
  caixa_.seq.store(s + 2, std::memory_order_release);
}

void Protecao::pedir_cancelamento(uint32_t num, uint32_t instante) {
  uint32_t s = caixa_.seq.load(std::memory_order_relaxed);
  caixa_.seq.store(s + 1, std::memory_order_relaxed);
  std::atomic_thread_fence(std::memory_order_release);
  caixa_.cancel_num.store(num, std::memory_order_relaxed);
  caixa_.cancel_t.store(instante, std::memory_order_relaxed);
  caixa_.cancel_cont.store(++prod_cancel_cont_, std::memory_order_relaxed);
  caixa_.seq.store(s + 2, std::memory_order_release);
}

// ------------------------------------------------------- tarefa
void Protecao::desligar_e_confirmar(uint32_t agora, uint8_t resultado) {
  saida_->escrever(false);
  if (saida_->ler()) {
    // Escrita nao confirmada: continua tentando a cada tick, sem declarar fim.
    e_.fase = P_FALHA_DESLIGAR;
    e_.ultimo_resultado = resultado;
    return;
  }
  e_.fase = P_OCIOSA;
  e_.ultima_concluida = e_.acao_ativa;
  e_.ultimo_resultado = resultado;
  e_.ultimo_fim = agora;
  e_.acao_ativa = 0;
}

void Protecao::tick(uint32_t agora) {
  if (!saida_) return;
  e_.ticks++;

  // 1) Caixa de pedidos (leitura seqlock nao bloqueante).
  bool novo_cancel = false, novo_inicio = false;
  uint32_t c_num = 0, c_t = 0, i_num = 0;
  uint32_t s1 = caixa_.seq.load(std::memory_order_acquire);
  if ((s1 & 1u) == 0) {
    uint32_t ic = caixa_.inicio_cont.load(std::memory_order_relaxed);
    i_num = caixa_.inicio_num.load(std::memory_order_relaxed);
    uint32_t cc = caixa_.cancel_cont.load(std::memory_order_relaxed);
    c_num = caixa_.cancel_num.load(std::memory_order_relaxed);
    c_t = caixa_.cancel_t.load(std::memory_order_relaxed);
    std::atomic_thread_fence(std::memory_order_acquire);
    uint32_t s2 = caixa_.seq.load(std::memory_order_relaxed);
    if (s1 == s2) {
      if (ic != visto_inicio_cont_) { visto_inicio_cont_ = ic; novo_inicio = true; }
      if (cc != visto_cancel_cont_) { visto_cancel_cont_ = cc; novo_cancel = true; }
    }
  }
  if (novo_inicio) pendente_num_ = i_num;

  // 2) Cancelamento antes de inicio: um pedido pendente pode ser impedido.
  if (novo_cancel) {
    e_.proximo_inicio = mais_tarde(e_.proximo_inicio, c_t + INIBICAO_CANCEL_MS);
    if (c_num != 0) {
      if (e_.fase != P_OCIOSA && e_.acao_ativa == c_num) {
        desligar_e_confirmar(agora, R_CANCELADA);
      } else if (pendente_num_ == c_num) {
        e_.inicio_processado = pendente_num_;
        e_.ultima_concluida = pendente_num_;
        e_.ultimo_resultado = R_CANCELADA;
        e_.ultimo_fim = agora;
        pendente_num_ = 0;
      }
    }
  }

  // 3) Inicio pendente.
  if (pendente_num_ != 0) {
    uint32_t num = pendente_num_;
    pendente_num_ = 0;
    e_.inicio_processado = num;
    if (!e_.ok || e_.fase != P_OCIOSA || !alcancou(agora, e_.proximo_inicio)) {
      e_.ultima_concluida = num;
      e_.ultimo_resultado = R_RECUSADA;
      e_.ultimo_fim = agora;
    } else {
      saida_->escrever(true);
      e_.fase = P_ENERGIZADA;
      e_.acao_ativa = num;
      e_.inicio_gpio = agora;
      e_.proximo_inicio = mais_tarde(e_.proximo_inicio, agora + COOLDOWN_MS);
    }
  }

  // 4) Prazo local. Nenhum pedido reinicia inicio_gpio.
  if (e_.fase == P_ENERGIZADA && alcancou(agora, e_.inicio_gpio + PRAZO_AGUA_MS)) {
    desligar_e_confirmar(agora, R_CONCLUIDA);
  } else if (e_.fase == P_FALHA_DESLIGAR) {
    desligar_e_confirmar(agora, e_.ultimo_resultado);
  } else if (e_.fase == P_OCIOSA && saida_->ler()) {
    // Defesa: ocioso com pino ligado nunca e aceitavel.
    saida_->escrever(false);
  }

  e_.rele_ligado = saida_->ler();
  publicar();
}

// ------------------------------------------------------- publicacao
void Protecao::publicar() {
  uint32_t s = pub_.seq.load(std::memory_order_relaxed);
  pub_.seq.store(s + 1, std::memory_order_relaxed);
  std::atomic_thread_fence(std::memory_order_release);
  uint32_t v[11] = {
      e_.fase, e_.ok ? 1u : 0u, e_.rele_ligado ? 1u : 0u, e_.acao_ativa, e_.inicio_gpio,
      e_.proximo_inicio, e_.inicio_processado, e_.ultima_concluida, e_.ultimo_resultado,
      e_.ultimo_fim, e_.ticks};
  for (int i = 0; i < 11; i++) pub_.campos[i].store(v[i], std::memory_order_relaxed);
  pub_.seq.store(s + 2, std::memory_order_release);
}

bool Protecao::ler(InstantaneoProtecao* o) const {
  for (int tentativa = 0; tentativa < 4; tentativa++) {
    uint32_t s1 = pub_.seq.load(std::memory_order_acquire);
    if (s1 & 1u) continue;
    uint32_t v[11];
    for (int i = 0; i < 11; i++) v[i] = pub_.campos[i].load(std::memory_order_relaxed);
    std::atomic_thread_fence(std::memory_order_acquire);
    if (pub_.seq.load(std::memory_order_relaxed) != s1) continue;
    o->fase = (uint8_t)v[0];
    o->ok = v[1] != 0;
    o->rele_ligado = v[2] != 0;
    o->acao_ativa = v[3];
    o->inicio_gpio = v[4];
    o->proximo_inicio = v[5];
    o->inicio_processado = v[6];
    o->ultima_concluida = v[7];
    o->ultimo_resultado = (uint8_t)v[8];
    o->ultimo_fim = v[9];
    o->ticks = v[10];
    return true;
  }
  return false;
}

}  // namespace vigia
