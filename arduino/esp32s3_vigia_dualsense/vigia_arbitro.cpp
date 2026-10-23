#include "vigia_arbitro.h"

#include <stdio.h>
#include <string.h>

#include "vigia_tempo.h"

namespace vigia {

namespace {

const char* const MOTIVOS[MOT_TOTAL] = {
    nullptr, "json_invalido", "campo_desconhecido", "campo_ausente", "tipo_invalido", "valor_invalido",
    "versao", "boot", "sem_sessao", "sessao_obsoleta", "seq_antiga", "id_conflito",
    "janela_expirada", "janela_invalida", "epoch_obsoleto", "escopo",
    "acao_desconhecida", "recuperacao", "modo_auto", "sem_lease", "combate", "ocupado",
    "cooldown", "protecao_indisponivel", "alvo_obsoleto", "agua_legada_ativa", "perfil_protegido"};

const char* const FASES[] = {"OCIOSA", "ACEITA_PENDENTE", "ENERGIZADA", "DESLIGAMENTO_PENDENTE"};
const char* const ORIGENS[] = {"ia", "operador", "teclado", "legado"};
const char* const CAPS[] = {"pan_manual", "watchdog", "bomba_protegida", "cancelar_sem_modo", "idempotencia"};

enum CodAcao : uint8_t { A_CONSULTAR, A_JANELA, A_MANUAL, A_AUTO, A_RENOVAR, A_MOVER, A_DISPARAR, A_CANCELAR, A_N };
const char* const ACOES[A_N] = {"consultar", "janela", "manual", "auto", "renovar", "mover", "disparar", "cancelar"};

// Campos aceitos no corpo de /api/v1/command e seus tipos.
enum TipoCampo : uint8_t { T_INT, T_STR, T_NUM };
struct DefCampo { const char* nome; TipoCampo tipo; };
const DefCampo CAMPOS[] = {
    {"v", T_INT}, {"boot_id", T_STR}, {"sessao", T_STR}, {"acao", T_STR}, {"seq", T_INT},
    {"id", T_STR}, {"janela", T_STR}, {"vel", T_NUM}, {"origem", T_STR}, {"cancel_ate", T_INT},
    {"alvo", T_STR}, {"ref", T_STR}};
const int N_CAMPOS = sizeof(CAMPOS) / sizeof(CAMPOS[0]);

// Mascara de campos (indices de CAMPOS) por acao: obrigatorios / permitidos.
constexpr uint32_t B(int i) { return 1u << i; }
const uint32_t COMUNS = B(0) | B(1) | B(2) | B(3);
const uint32_t SEQ_ID_JAN = B(4) | B(5) | B(6);
struct DefAcao { uint32_t obrig; uint32_t permit; };
const DefAcao DEF_ACOES[A_N] = {
    {COMUNS | B(11), COMUNS | B(11)},                     // consultar
    {COMUNS, COMUNS},                                     // janela
    {COMUNS | SEQ_ID_JAN, COMUNS | SEQ_ID_JAN},           // manual
    {COMUNS | SEQ_ID_JAN, COMUNS | SEQ_ID_JAN},           // auto
    {COMUNS | SEQ_ID_JAN, COMUNS | SEQ_ID_JAN},           // renovar
    {COMUNS | SEQ_ID_JAN | B(7), COMUNS | SEQ_ID_JAN | B(7)},     // mover
    {COMUNS | SEQ_ID_JAN | B(8), COMUNS | SEQ_ID_JAN | B(8)},     // disparar
    {COMUNS | SEQ_ID_JAN, COMUNS | SEQ_ID_JAN | B(9) | B(10)},    // cancelar (um de 9/10)
};

uint32_t fnv(uint32_t h, const void* p, size_t n) {
  const uint8_t* b = (const uint8_t*)p;
  for (size_t i = 0; i < n; i++) { h ^= b[i]; h *= 16777619u; }
  return h;
}
uint32_t hash_texto(const char* s, size_t n) { return fnv(2166136261u, s, n); }

bool id_valido(const char* s) {
  size_t n = strlen(s);
  if (n < 1 || n > (size_t)ID_MAX) return false;
  for (size_t i = 0; i < n; i++) {
    char c = s[i];
    bool ok = (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '_' || c == '-';
    if (!ok) return false;
  }
  return true;
}

void copiar(char* dst, const char* src, size_t cap) {
  size_t n = strlen(src);
  if (n >= cap) n = cap - 1;
  memcpy(dst, src, n);
  dst[n] = '\0';
}

int32_t limitar(int32_t v, int32_t lo, int32_t hi) { return v < lo ? lo : (v > hi ? hi : v); }

bool eh_schema(Motivo m) {
  return m == MOT_JSON || m == MOT_CAMPO_DESCONHECIDO || m == MOT_CAMPO_AUSENTE || m == MOT_TIPO ||
         m == MOT_VALOR || m == MOT_ACAO_DESCONHECIDA;
}

// Valida o corpo contra CAMPOS. Devolve MOT_NENHUM ou o motivo do erro.
Motivo validar_tipos(const ObjetoJson& o, uint32_t* presentes) {
  *presentes = 0;
  for (int k = 0; k < o.n; k++) {
    int idx = -1;
    for (int c = 0; c < N_CAMPOS; c++)
      if (!strcmp(o.campos[k].chave, CAMPOS[c].nome)) idx = c;
    if (idx < 0) return MOT_CAMPO_DESCONHECIDO;
    *presentes |= B(idx);
  }
  for (int k = 0; k < o.n; k++) {
    const CampoJson& f = o.campos[k];
    for (int c = 0; c < N_CAMPOS; c++) {
      if (strcmp(f.chave, CAMPOS[c].nome)) continue;
      bool ok = (CAMPOS[c].tipo == T_STR && f.tipo == J_STR) ||
                (CAMPOS[c].tipo == T_INT && f.tipo == J_NUM && f.inteiro) ||
                (CAMPOS[c].tipo == T_NUM && f.tipo == J_NUM);
      if (!ok) return MOT_TIPO;
    }
  }
  return MOT_NENHUM;
}

}  // namespace

const char* nome_motivo(Motivo m) { return m < MOT_TOTAL ? MOTIVOS[m] : "?"; }

// =================================================================== base
Arbitro::Arbitro() { memset((void*)this, 0, sizeof(*this)); }

void Arbitro::iniciar(Protecao* p, SaidasAplicacao* s, uint32_t agora, uint32_t boot_id, uint32_t segredo) {
  prot_ = p;
  out_ = s;
  boot_id_ = boot_id;
  segredo_ = segredo;
  perfil_ = PERFIL_COMPAT;
  modo_ = M_AUTO;
  retorno_auto_ = false;
  vel_mdps_ = 0;
  epoch_ = 1;
  ang_mdeg_ = PAN_CENTRO * 1000;
  resto_ = 0;
  direcao_ = 1;
  ultimo_passo_ = agora;
  ultimo_grau_escrito_ = PAN_CENTRO;
  compat_parado_ = false;
  compat_tem_alvo_ = false;
  compat_ultimo_cmd_ = agora;
  fogo_compat_ = false;
  sessao_ = 0;
  contador_sessoes_ = 0;
  estado_sessao_ = ES_NENHUMA;
  ultimo_seq_ = 0;
  memset(&acao_, 0, sizeof(acao_));
  contador_acoes_ = 0;
  proximo_local_ = agora + INIBICAO_BOOT_MS;
  ultimo_id_[0] = '\0';
  ultimo_resultado_ = R_NENHUM;
  memset(dedup_, 0, sizeof(dedup_));
  dedup_pos_ = 0;
  memset(aberturas_, 0, sizeof(aberturas_));
  abertura_pos_ = 0;
  memset(&snap_, 0, sizeof(snap_));
  if (prot_) prot_->ler(&snap_);
  if (out_) { out_->escrever_servo(PAN_CENTRO); out_->led(false); }
}

int Arbitro::pan_graus() const { return (ang_mdeg_ + 500) / 1000; }

bool Arbitro::vigiando() const {
  return !acao_.ativa && modo_ == M_AUTO && !(perfil_ == PERFIL_COMPAT && compat_parado_);
}

bool Arbitro::fogo() const {
  return fogo_compat_ || (acao_.ativa && acao_.origem == 0);
}

FaseAcao Arbitro::fase(uint32_t) const {
  if (!acao_.ativa) return F_OCIOSA;
  if (acao_.cancel_pedido || snap_.ultima_concluida == acao_.num) return F_DESLIGAMENTO_PENDENTE;
  if (snap_.acao_ativa == acao_.num && snap_.fase != P_OCIOSA) return F_ENERGIZADA;
  return F_ACEITA_PENDENTE;
}

uint32_t Arbitro::proximo_efetivo() const { return mais_tarde(snap_.proximo_inicio, proximo_local_); }

// =================================================================== passo
void Arbitro::passo(uint32_t agora) {
  InstantaneoProtecao s;
  if (prot_ && prot_->ler(&s)) snap_ = s;

  if (acao_.ativa && snap_.ultima_concluida == acao_.num && snap_.fase != P_FALHA_DESLIGAR) {
    encerrar_combate(snap_.ultimo_resultado);
  }

  expirar_lease(agora);

  // Regra legada de silencio, somente no perfil COMPAT.
  if (perfil_ == PERFIL_COMPAT && compat_parado_ && !acao_.ativa &&
      alcancou(agora, compat_ultimo_cmd_ + SILENCIO_COMPAT_MS)) {
    compat_parado_ = false;
    compat_tem_alvo_ = false;
    fogo_compat_ = false;
    if (out_) out_->led(false);
  }

  integrar(agora);
}

// Lease manual no relogio local. Chamado em passo() e tambem no recebimento de
// cada requisicao, para que um handleClient retido nao reviva lease vencido.
void Arbitro::expirar_lease(uint32_t agora) {
  if (modo_ == M_MANUAL && alcancou(agora, lease_ate_)) {
    if (acao_.ativa) retorno_auto_ = true;
    else ir_auto();
  }
}

void Arbitro::ir_auto() {
  modo_ = M_AUTO;
  vel_mdps_ = 0;
  lease_ate_ = 0;
  resto_ = 0;
}

void Arbitro::mover_para(int32_t alvo, int32_t vel_mdps, uint32_t dt) {
  resto_ += (int64_t)vel_mdps * dt;
  int32_t delta = (int32_t)(resto_ / 1000);
  resto_ %= 1000;
  if (ang_mdeg_ < alvo) ang_mdeg_ = (ang_mdeg_ + delta > alvo) ? alvo : ang_mdeg_ + delta;
  else if (ang_mdeg_ > alvo) ang_mdeg_ = (ang_mdeg_ - delta < alvo) ? alvo : ang_mdeg_ - delta;
  if (ang_mdeg_ == alvo) resto_ = 0;
}

void Arbitro::integrar(uint32_t agora) {
  uint32_t anterior = ultimo_passo_;
  ultimo_passo_ = agora;
  if (acao_.ativa) return;  // mira congelada; nada e integrado retroativamente depois
  int32_t dif = dif_ms(agora, anterior);
  if (dif <= 0) return;
  uint32_t dt = (uint32_t)dif > PASSO_MAX_MS ? PASSO_MAX_MS : (uint32_t)dif;

  if (modo_ == M_MANUAL) {
    // Validade da velocidade avaliada antes de integrar.
    if (vel_mdps_ != 0) {
      int32_t util = dif_ms(vel_ate_, anterior);
      if (util <= 0) {
        vel_mdps_ = 0;
        resto_ = 0;
      } else {
        uint32_t dv = (uint32_t)util < dt ? (uint32_t)util : dt;
        resto_ += (int64_t)vel_mdps_ * dv;
        int32_t delta = (int32_t)(resto_ / 1000);
        resto_ %= 1000;
        int32_t novo = limitar(ang_mdeg_ + delta, PAN_MIN * 1000, PAN_MAX * 1000);
        if (novo != ang_mdeg_ + delta) resto_ = 0;
        ang_mdeg_ = novo;
        if (!alcancou(vel_ate_, agora)) { vel_mdps_ = 0; resto_ = 0; }
      }
    }
  } else if (perfil_ == PERFIL_COMPAT && compat_parado_) {
    if (compat_tem_alvo_) mover_para(compat_alvo_mdeg_, LEGADO_MOVE_MDPS, dt);
  } else {
    const int32_t hi = PAN_ESQUERDA * 1000, lo = PAN_DIREITA * 1000;
    if (ang_mdeg_ > hi) {
      mover_para(hi, RETORNO_FAIXA_MDPS, dt);
      direcao_ = -1;
    } else if (ang_mdeg_ < lo) {
      mover_para(lo, RETORNO_FAIXA_MDPS, dt);
      direcao_ = 1;
    } else {
      resto_ += (int64_t)VARRE_MDPS * dt;
      int32_t delta = (int32_t)(resto_ / 1000);
      resto_ %= 1000;
      ang_mdeg_ += direcao_ * delta;
      if (ang_mdeg_ >= hi) { ang_mdeg_ = hi; direcao_ = -1; }
      if (ang_mdeg_ <= lo) { ang_mdeg_ = lo; direcao_ = 1; }
    }
  }

  int g = pan_graus();
  if (g != ultimo_grau_escrito_ && out_) {
    out_->escrever_servo(g);
    ultimo_grau_escrito_ = g;
  }
}

// =================================================================== combate
Motivo Arbitro::pode_disparar(uint32_t agora) const {
  if (!snap_.ok) return MOT_PROTECAO;
  if (acao_.ativa) return MOT_OCUPADO;
  if (!alcancou(agora, proximo_efetivo())) return MOT_COOLDOWN;
  return MOT_NENHUM;
}

void Arbitro::iniciar_acao(uint32_t, const char* id, int64_t seq, uint8_t origem, bool legado) {
  acao_.ativa = true;
  acao_.legado = legado;
  acao_.cancel_pedido = false;
  acao_.num = ++contador_acoes_;
  acao_.sessao = legado ? 0 : sessao_;
  acao_.seq = seq;
  acao_.origem = origem;
  if (id) copiar(acao_.id, id, sizeof acao_.id);
  else snprintf(acao_.id, sizeof acao_.id, "legado-%lu", (unsigned long)acao_.num);
  epoch_++;          // entrada no combate
  vel_mdps_ = 0;
  resto_ = 0;
  // Como no sketch original: servo solto ANTES de energizar.
  if (out_) { out_->soltar_servo(); out_->led(true); }
  prot_->pedir_inicio(acao_.num);
}

void Arbitro::cancelar_acao(uint32_t agora) {
  proximo_local_ = mais_tarde(proximo_local_, agora + INIBICAO_CANCEL_MS);
  if (acao_.ativa) {
    acao_.cancel_pedido = true;
    prot_->pedir_cancelamento(acao_.num, agora);
  } else {
    prot_->pedir_cancelamento(0, agora);
  }
}

void Arbitro::encerrar_combate(uint8_t resultado) {
  copiar(ultimo_id_, acao_.id, sizeof ultimo_id_);
  ultimo_resultado_ = resultado;
  bool legado = acao_.legado;
  acao_.ativa = false;
  acao_.cancel_pedido = false;
  epoch_++;  // saida do combate (natural ou cancelada)
  vel_mdps_ = 0;
  resto_ = 0;
  if (estado_sessao_ == ES_RECUPERACAO) {
    estado_sessao_ = ES_NORMAL;
    retorno_auto_ = true;
  }
  if (modo_ == M_MANUAL && (retorno_auto_ || alcancou(ultimo_passo_, lease_ate_))) ir_auto();
  retorno_auto_ = false;
  if (out_) {
    out_->prender_servo(pan_graus());
    out_->led(legado && fogo_compat_);
  }
}

// =================================================================== janelas
uint32_t Arbitro::mac(char escopo, uint32_t vinc, uint32_t t, uint32_t sessao) const {
  uint32_t h = 2166136261u;
  h = fnv(h, &segredo_, 4);
  h = fnv(h, &boot_id_, 4);
  h = fnv(h, &escopo, 1);
  h = fnv(h, &vinc, 4);
  h = fnv(h, &t, 4);
  h = fnv(h, &sessao, 4);
  return h;
}

void Arbitro::cunhar(char escopo, uint32_t vinc, uint32_t agora, char* out, size_t cap) const {
  uint32_t sess = (escopo == 'A') ? 0 : sessao_;
  snprintf(out, cap, "%c%lu.%lu.%08lx", escopo, (unsigned long)vinc, (unsigned long)agora,
           (unsigned long)mac(escopo, vinc, agora, sess));
}

Motivo Arbitro::validar_janela(const char* tok, char escopo, uint32_t agora) const {
  if (!tok || !*tok) return MOT_JANELA_INVALIDA;
  char e = tok[0];
  if (e != 'A' && e != 'C' && e != 'X' && e != 'R') return MOT_JANELA_INVALIDA;
  const char* p = tok + 1;
  uint32_t campos[2] = {0, 0};
  for (int k = 0; k < 2; k++) {
    if (*p < '0' || *p > '9') return MOT_JANELA_INVALIDA;
    uint64_t v = 0;
    int dig = 0;
    while (*p >= '0' && *p <= '9') { v = v * 10 + (uint64_t)(*p - '0'); p++; if (++dig > 10) return MOT_JANELA_INVALIDA; }
    if (v > 0xFFFFFFFFull || *p != '.') return MOT_JANELA_INVALIDA;
    campos[k] = (uint32_t)v;
    p++;
  }
  uint32_t m = 0;
  for (int k = 0; k < 8; k++) {
    char c = p[k];
    uint32_t d;
    if (c >= '0' && c <= '9') d = (uint32_t)(c - '0');
    else if (c >= 'a' && c <= 'f') d = (uint32_t)(c - 'a' + 10);
    else return MOT_JANELA_INVALIDA;
    m = (m << 4) | d;
  }
  if (p[8] != '\0') return MOT_JANELA_INVALIDA;
  if (e != escopo) return MOT_ESCOPO;
  uint32_t vinc = campos[0], t = campos[1];
  uint32_t sess = (e == 'A') ? 0 : sessao_;
  if (m != mac(e, vinc, t, sess)) return MOT_JANELA_INVALIDA;
  if ((uint32_t)(agora - t) > JANELA_MS) return MOT_JANELA_EXPIRADA;
  if (e == 'C' && vinc != epoch_) return MOT_EPOCH_OBSOLETO;
  if (e == 'R' && (estado_sessao_ != ES_RECUPERACAO || !acao_.ativa || vinc != acao_.num))
    return MOT_ALVO_OBSOLETO;
  return MOT_NENHUM;
}

// =================================================================== respostas
void Arbitro::nome_sessao(uint32_t num, char* out, size_t cap) const {
  snprintf(out, cap, "s%lu", (unsigned long)num);
}

uint32_t Arbitro::ler_sessao(const char* s) const {
  if (!s || s[0] != 's' || !s[1]) return 0;
  uint64_t v = 0;
  for (const char* p = s + 1; *p; p++) {
    if (*p < '0' || *p > '9') return 0;
    v = v * 10 + (uint64_t)(*p - '0');
    if (v > 0xFFFFFFFFull) return 0;
  }
  return (uint32_t)v;
}

void Arbitro::escrever_estado(EscritorJson& w, uint32_t agora) {
  char s[16];
  w.abre_obj("estado");
  w.str("modo", modo_ == M_MANUAL ? "MANUAL" : "AUTO");
  w.str("fase", FASES[fase(agora)]);
  w.num("control_epoch", epoch_);
  w.str("perfil", perfil_ == PERFIL_PROTEGIDO ? "PROTEGIDO" : "COMPAT");
  if (sessao_) { nome_sessao(sessao_, s, sizeof s); w.str("sessao", s); } else w.nulo("sessao");
  w.str("estado_sessao", estado_sessao_ == ES_RECUPERACAO ? "RECUPERACAO" : (estado_sessao_ == ES_NORMAL ? "NORMAL" : nullptr));
  w.num("lease_restante_ms", modo_ == M_MANUAL ? restante(agora, lease_ate_) : 0);
  w.num("cooldown_restante_ms", restante(agora, proximo_efetivo()));
  w.str("acao_id", acao_.ativa ? acao_.id : nullptr);
  w.num("pan", pan_graus());
  w.bol("vigiando", vigiando());
  w.bol("retorno_auto", retorno_auto_);
  w.bol("bomba", snap_.rele_ligado);
  w.fecha();
}

void Arbitro::escrever_janelas(EscritorJson& w, uint32_t agora) {
  char tok[48];
  bool normal = sessao_ && estado_sessao_ == ES_NORMAL;
  bool recup = sessao_ && estado_sessao_ == ES_RECUPERACAO && acao_.ativa;
  if (normal) { cunhar('C', epoch_, agora, tok, sizeof tok); w.str("janela_c", tok); } else w.nulo("janela_c");
  if (normal) { cunhar('X', 0, agora, tok, sizeof tok); w.str("janela_x", tok); } else w.nulo("janela_x");
  if (recup) { cunhar('R', acao_.num, agora, tok, sizeof tok); w.str("janela_r", tok); } else w.nulo("janela_r");
}

int Arbitro::responder_cmd(uint32_t agora, char* out, size_t cap, bool aceito, Motivo m, const char* acao,
                           const char* id, bool duplicado) {
  EscritorJson w(out, cap);
  w.abre();
  w.bol("ok", aceito);
  w.str("resultado", aceito ? "aceito" : "recusado");
  w.str("motivo", aceito ? nullptr : nome_motivo(m));
  w.str("acao", acao);
  w.str("id", id);
  w.bol("duplicado", duplicado);
  escrever_estado(w, agora);
  escrever_janelas(w, agora);
  w.fecha();
  if (aceito) return 200;
  return eh_schema(m) ? 400 : 409;
}

Arbitro::Dedup* Arbitro::achar_dedup(const char* id, uint32_t agora) {
  for (Dedup& d : dedup_) {
    if (!d.usado) continue;
    if ((uint32_t)(agora - d.t) > DEDUP_RETENCAO_MS) { d.usado = false; continue; }
    if (!strcmp(d.id, id)) return &d;
  }
  return nullptr;
}

void Arbitro::gravar_dedup(uint32_t agora, const char* id, uint32_t hash, uint8_t acao, bool aceito, Motivo m) {
  Dedup& d = dedup_[dedup_pos_];
  dedup_pos_ = (dedup_pos_ + 1) % DEDUP_CAPACIDADE;
  d.usado = true;
  d.sessao = sessao_;
  d.hash = hash;
  d.t = agora;
  d.acao = acao;
  d.aceito = aceito;
  d.motivo = (uint8_t)m;
  copiar(d.id, id, sizeof d.id);
}

// =================================================================== status
int Arbitro::status_json(uint32_t agora, char* out, size_t cap) {
  char tok[48], s[16];
  EscritorJson w(out, cap);
  w.abre();
  w.num("pan", pan_graus());
  w.bol("vigiando", vigiando());
  w.bol("fogo", fogo());
  w.bol("bomba", snap_.rele_ligado);
  w.num("v", PROTOCOLO_V);
  w.str("fw", FW_NOME);
  w.abre_lista("caps");
  for (const char* c : CAPS) w.item_str(c);
  w.fecha_lista();
  snprintf(s, sizeof s, "%08lx", (unsigned long)boot_id_);
  w.str("boot_id", s);
  w.str("perfil", perfil_ == PERFIL_PROTEGIDO ? "PROTEGIDO" : "COMPAT");
  w.str("modo", modo_ == M_MANUAL ? "MANUAL" : "AUTO");
  w.str("fase", FASES[fase(agora)]);
  if (sessao_) { nome_sessao(sessao_, s, sizeof s); w.str("sessao", s); } else w.nulo("sessao");
  w.str("estado_sessao", estado_sessao_ == ES_RECUPERACAO ? "RECUPERACAO" : (estado_sessao_ == ES_NORMAL ? "NORMAL" : nullptr));
  w.num("control_epoch", epoch_);
  w.str("acao_id", acao_.ativa ? acao_.id : nullptr);
  w.str("acao_origem", acao_.ativa ? ORIGENS[acao_.origem] : nullptr);
  w.num("lease_restante_ms", modo_ == M_MANUAL ? restante(agora, lease_ate_) : 0);
  w.num("cooldown_restante_ms", restante(agora, proximo_efetivo()));
  w.bol("retorno_auto", retorno_auto_);
  w.bol("protecao_ok", snap_.ok);
  cunhar('A', 0, agora, tok, sizeof tok);
  w.str("janela_abertura", tok);
  w.num("t_ms", agora);
  w.abre_obj("ultimo");
  w.str("id", ultimo_id_[0] ? ultimo_id_ : nullptr);
  const char* res = nullptr;
  if (ultimo_resultado_ == R_CONCLUIDA) res = "concluida";
  else if (ultimo_resultado_ == R_CANCELADA) res = "cancelada";
  else if (ultimo_resultado_ == R_RECUSADA) res = "recusada";
  w.str("resultado", res);
  w.fecha();
  w.abre_obj("limites");
  w.num("prazo_agua_ms", PRAZO_AGUA_MS);
  w.num("cooldown_ms", COOLDOWN_MS);
  w.num("inibicao_boot_ms", INIBICAO_BOOT_MS);
  w.num("inibicao_cancel_ms", INIBICAO_CANCEL_MS);
  w.num("lease_ms", LEASE_MS);
  w.num("janela_ms", JANELA_MS);
  w.num("vel_validade_ms", VEL_VALIDADE_MS);
  w.num("vel_max_dps", VEL_MAX_MDPS / 1000);
  w.num("pan_min", PAN_MIN);
  w.num("pan_max", PAN_MAX);
  w.num("varre_min", PAN_DIREITA);
  w.num("varre_max", PAN_ESQUERDA);
  w.num("dedup_retencao_ms", DEDUP_RETENCAO_MS);
  w.num("dedup_capacidade", DEDUP_CAPACIDADE);  // retencao efetiva: o menor dos dois
  w.fecha();
  w.fecha();
  return 200;
}

// =================================================================== sessao
int Arbitro::http_sessao(uint32_t agora, const char* corpo, size_t len, char* out, size_t cap) {
  expirar_lease(agora);
  ObjetoJson o;
  Motivo m = MOT_NENHUM;
  const CampoJson *v = nullptr, *boot = nullptr, *oid = nullptr, *jan = nullptr;
  if (len > (size_t)CORPO_MAX || !json_ler_plano(corpo, len, &o)) {
    m = MOT_JSON;
  } else {
    for (int k = 0; k < o.n && !m; k++) {
      const char* c = o.campos[k].chave;
      if (strcmp(c, "v") && strcmp(c, "boot_id") && strcmp(c, "session_open_id") && strcmp(c, "janela"))
        m = MOT_CAMPO_DESCONHECIDO;
    }
    v = o.achar("v"); boot = o.achar("boot_id"); oid = o.achar("session_open_id"); jan = o.achar("janela");
    if (!m && (!v || !boot || !oid || !jan)) m = MOT_CAMPO_AUSENTE;
    if (!m && (v->tipo != J_NUM || !v->inteiro || boot->tipo != J_STR || oid->tipo != J_STR || jan->tipo != J_STR))
      m = MOT_TIPO;
    if (!m && !id_valido(oid->str)) m = MOT_VALOR;
  }

  char bs[12];
  snprintf(bs, sizeof bs, "%08lx", (unsigned long)boot_id_);
  if (!m && v->i != PROTOCOLO_V) m = MOT_VERSAO;
  if (!m && strcmp(boot->str, bs)) m = MOT_BOOT;

  // Abertura repetida: devolve a decisao original sem novo takeover.
  Abertura* ant = nullptr;
  uint32_t h = hash_texto(corpo, len);
  if (!m) {
    for (Abertura& a : aberturas_)
      if (a.usado && !strcmp(a.open_id, oid->str)) ant = &a;
    if (ant && ant->hash != h) { m = MOT_ID_CONFLITO; ant = nullptr; }
  }

  bool aceito = false, duplicado = false;
  uint32_t sessao_resp = 0;
  uint8_t estado_resp = ES_NENHUMA;
  const char* recuperar = nullptr;

  if (!m && ant) {
    duplicado = true;
    aceito = ant->aceito;
    m = (Motivo)ant->motivo;
    sessao_resp = ant->sessao;
    estado_resp = ant->estado_sessao;
    recuperar = ant->acao_recuperar[0] ? ant->acao_recuperar : nullptr;
    if (aceito && sessao_resp == sessao_) estado_resp = (uint8_t)estado_sessao_;
  } else if (!m) {
    m = validar_janela(jan->str, 'A', agora);
    if (!m && acao_.ativa && acao_.legado) m = MOT_AGUA_LEGADA;
    if (!m) {
      aceito = true;
      perfil_ = PERFIL_PROTEGIDO;  // fixado ate o proximo boot
      compat_parado_ = false;
      compat_tem_alvo_ = false;
      fogo_compat_ = false;
      sessao_ = ++contador_sessoes_;
      ultimo_seq_ = 0;
      vel_mdps_ = 0;
      lease_ate_ = agora;  // lease anterior nao e herdado
      if (acao_.ativa) {
        // RECUPERACAO: comandos da anterior revogados; so pode cancelar esta acao.
        // Modo-base passa a AUTO ja (a mira segue congelada ate o fim do combate).
        estado_sessao_ = ES_RECUPERACAO;
        ir_auto();
        retorno_auto_ = true;
        recuperar = acao_.id;
      } else {
        estado_sessao_ = ES_NORMAL;
        ir_auto();
      }
      sessao_resp = sessao_;
      estado_resp = (uint8_t)estado_sessao_;
    }
    // Guarda a decisao (aceita ou recusada) para repeticoes do mesmo open_id.
    Abertura& a = aberturas_[abertura_pos_];
    abertura_pos_ = (abertura_pos_ + 1) % ABERTURAS_GUARDADAS;
    memset(&a, 0, sizeof a);
    a.usado = true;
    a.hash = h;
    a.aceito = aceito;
    a.motivo = (uint8_t)m;
    a.sessao = sessao_resp;
    a.estado_sessao = estado_resp;
    copiar(a.open_id, oid->str, sizeof a.open_id);
    if (recuperar) copiar(a.acao_recuperar, recuperar, sizeof a.acao_recuperar);
  }

  bool vigente = aceito && sessao_resp == sessao_;
  EscritorJson w(out, cap);
  char s[16];
  w.abre();
  w.bol("ok", aceito);
  w.str("resultado", aceito ? "aceito" : "recusado");
  w.str("motivo", aceito ? nullptr : nome_motivo(m));
  if (aceito) { nome_sessao(sessao_resp, s, sizeof s); w.str("sessao", s); } else w.nulo("sessao");
  w.str("estado_sessao", !aceito ? nullptr : (estado_resp == ES_RECUPERACAO ? "RECUPERACAO" : "NORMAL"));
  w.str("acao_recuperar", aceito && estado_resp == ES_RECUPERACAO ? recuperar : nullptr);
  w.bol("duplicado", duplicado);
  w.bol("sessao_vigente", vigente);
  escrever_estado(w, agora);
  if (vigente) escrever_janelas(w, agora);
  else { w.nulo("janela_c"); w.nulo("janela_x"); w.nulo("janela_r"); }
  w.fecha();
  if (aceito) return 200;
  return eh_schema(m) ? 400 : 409;
}

// =================================================================== comando
int Arbitro::http_comando(uint32_t agora, const char* corpo, size_t len, char* out, size_t cap) {
  expirar_lease(agora);
  ObjetoJson o;
  if (len > (size_t)CORPO_MAX || !json_ler_plano(corpo, len, &o))
    return responder_cmd(agora, out, cap, false, MOT_JSON, nullptr, nullptr, false);

  uint32_t presentes = 0;
  Motivo m = validar_tipos(o, &presentes);
  const CampoJson* fa = o.achar("acao");
  int cod = -1;
  if (!m && fa) {
    for (int k = 0; k < A_N; k++)
      if (!strcmp(fa->str, ACOES[k])) cod = k;
    if (cod < 0) m = MOT_ACAO_DESCONHECIDA;
  }
  if (!m && !fa) m = MOT_CAMPO_AUSENTE;
  if (!m && (presentes & ~DEF_ACOES[cod].permit)) m = MOT_CAMPO_DESCONHECIDO;
  if (!m && (DEF_ACOES[cod].obrig & ~presentes)) m = MOT_CAMPO_AUSENTE;
  const char* nome_acao = cod >= 0 ? ACOES[cod] : nullptr;

  const CampoJson* fid = o.achar("id");
  const CampoJson* fseq = o.achar("seq");
  const CampoJson* fcan = o.achar("cancel_ate");
  const CampoJson* falvo = o.achar("alvo");
  const CampoJson* forig = o.achar("origem");
  const CampoJson* fvel = o.achar("vel");
  if (!m && cod == A_CANCELAR && !!fcan == !!falvo) m = fcan ? MOT_VALOR : MOT_CAMPO_AUSENTE;
  if (!m && fid && !id_valido(fid->str)) m = MOT_VALOR;
  if (!m && fseq && (fseq->i < 1 || fseq->i > 2147483647LL)) m = MOT_VALOR;
  if (!m && fcan && (fcan->i < 0 || fcan->i >= fseq->i)) m = MOT_VALOR;
  if (!m && falvo && !id_valido(falvo->str)) m = MOT_VALOR;
  if (!m && fvel && !(fvel->d >= -1.0 && fvel->d <= 1.0)) m = MOT_VALOR;
  uint8_t origem = 0;
  if (!m && forig) {
    if (!strcmp(forig->str, "ia")) origem = 0;
    else if (!strcmp(forig->str, "operador")) origem = 1;
    else if (!strcmp(forig->str, "teclado")) origem = 2;
    else m = MOT_VALOR;
  }
  const char* id = fid ? fid->str : nullptr;
  if (m) return responder_cmd(agora, out, cap, false, m, nome_acao, id, false);

  char bs[12];
  snprintf(bs, sizeof bs, "%08lx", (unsigned long)boot_id_);
  if (o.achar("v")->i != PROTOCOLO_V) return responder_cmd(agora, out, cap, false, MOT_VERSAO, nome_acao, id, false);
  if (strcmp(o.achar("boot_id")->str, bs)) return responder_cmd(agora, out, cap, false, MOT_BOOT, nome_acao, id, false);
  uint32_t sess = ler_sessao(o.achar("sessao")->str);
  if (!sessao_) return responder_cmd(agora, out, cap, false, MOT_SEM_SESSAO, nome_acao, id, false);
  if (sess != sessao_) return responder_cmd(agora, out, cap, false, MOT_SESSAO_OBSOLETA, nome_acao, id, false);

  // ---- consultas sem efeito ----
  if (cod == A_JANELA) return responder_cmd(agora, out, cap, true, MOT_NENHUM, nome_acao, nullptr, false);
  if (cod == A_CONSULTAR) {
    Dedup* d = achar_dedup(o.achar("ref")->str, agora);
    EscritorJson w(out, cap);
    w.abre();
    w.bol("ok", true);
    w.str("resultado", "aceito");
    w.nulo("motivo");
    w.str("acao", "consultar");
    w.str("ref", o.achar("ref")->str);
    w.str("ref_resultado", d ? (d->aceito ? "aceito" : "recusado") : "desconhecido");
    w.str("ref_motivo", d && !d->aceito ? nome_motivo((Motivo)d->motivo) : nullptr);
    w.str("ref_acao", d ? ACOES[d->acao] : nullptr);
    w.bol("duplicado", false);
    escrever_estado(w, agora);
    escrever_janelas(w, agora);
    w.fecha();
    return 200;
  }

  // ---- identidade e ordem ----
  uint32_t h = hash_texto(corpo, len);
  bool discreto = cod == A_MANUAL || cod == A_AUTO || cod == A_DISPARAR || cod == A_CANCELAR;
  Dedup* d = achar_dedup(id, agora);
  if (d) {
    if (d->hash != h || d->sessao != sessao_)
      return responder_cmd(agora, out, cap, false, MOT_ID_CONFLITO, nome_acao, id, false);
    return responder_cmd(agora, out, cap, d->aceito, (Motivo)d->motivo, nome_acao, id, true);
  }
  int64_t seq = fseq->i;
  if (seq <= ultimo_seq_) return responder_cmd(agora, out, cap, false, MOT_SEQ_ANTIGA, nome_acao, id, false);
  ultimo_seq_ = seq;

  // ---- RECUPERACAO: somente cancelar a acao herdada ----
  if (estado_sessao_ == ES_RECUPERACAO && !(cod == A_CANCELAR && falvo)) m = MOT_RECUPERACAO;

  // ---- janela de frescor emitida por este S3 ----
  if (!m) {
    char escopo = 'C';
    if (cod == A_CANCELAR) escopo = falvo ? 'R' : 'X';
    m = validar_janela(o.achar("janela")->str, escopo, agora);
  }

  // ---- decisao ----
  if (!m) {
    switch (cod) {
      case A_MANUAL:
        if (acao_.ativa) { m = MOT_COMBATE; break; }
        modo_ = M_MANUAL;
        lease_ate_ = agora + LEASE_MS;
        vel_mdps_ = 0;
        resto_ = 0;
        break;
      case A_AUTO:
        if (acao_.ativa) { m = MOT_COMBATE; break; }
        ir_auto();
        break;
      case A_RENOVAR:
        if (modo_ != M_MANUAL) { m = MOT_SEM_LEASE; break; }
        lease_ate_ = agora + LEASE_MS;
        break;
      case A_MOVER: {
        if (acao_.ativa) { m = MOT_COMBATE; break; }
        if (modo_ != M_MANUAL) { m = MOT_MODO_AUTO; break; }
        double vv = fvel->d * (double)VEL_MAX_MDPS;
        int32_t nv = (int32_t)(vv >= 0 ? vv + 0.5 : vv - 0.5);
        if (nv != vel_mdps_) resto_ = 0;
        vel_mdps_ = nv;
        vel_ate_ = agora + VEL_VALIDADE_MS;
        break;
      }
      case A_DISPARAR:
        if (!snap_.ok) { m = MOT_PROTECAO; break; }
        if (origem != 0 && modo_ != M_MANUAL) { m = MOT_MODO_AUTO; break; }
        m = pode_disparar(agora);
        if (!m) iniciar_acao(agora, id, seq, origem, false);
        break;
      case A_CANCELAR:
        if (falvo) {
          // validar_janela ja garantiu RECUPERACAO com a acao vinculada ativa.
          if (strcmp(falvo->str, acao_.id)) { m = MOT_ALVO_OBSOLETO; break; }
          cancelar_acao(agora);
        } else {
          int64_t barreira = fcan->i;
          if (acao_.ativa && !(acao_.sessao == sessao_ && acao_.seq <= barreira)) { m = MOT_ALVO_OBSOLETO; break; }
          cancelar_acao(agora);
        }
        break;
      default:
        break;
    }
  }

  // Estado de RECUPERACAO termina quando a acao herdada termina; uma
  // capacidade R atrasada so pode recusar (ver validar_janela).
  if (discreto) gravar_dedup(agora, id, h, (uint8_t)cod, m == MOT_NENHUM, m);
  return responder_cmd(agora, out, cap, m == MOT_NENHUM, m, nome_acao, id, false);
}

// =================================================================== letras
int Arbitro::letra(uint32_t agora, char c, char* out, size_t cap) {
  if (c >= 'a' && c <= 'z') c = (char)(c - 32);
  const char* atuantes = "VLCR46FXB";
  if (c == 'H') {
    snprintf(out, cap, "V varre | L C R aponta | 4 6 ajuste | F fogo | X cancela | B bomba | perfil %s",
             perfil_ == PERFIL_PROTEGIDO ? "PROTEGIDO (letras atuantes bloqueadas)" : "COMPAT");
    return 200;
  }
  if (!c || !strchr(atuantes, c)) {
    snprintf(out, cap, "comando invalido");
    return 400;
  }
  if (perfil_ == PERFIL_PROTEGIDO) {
    snprintf(out, cap, "recusado:perfil_protegido");
    return 403;
  }
  compat_ultimo_cmd_ = agora;
  Motivo m = MOT_NENHUM;
  switch (c) {
    case 'V':
    case 'X':
      if (acao_.ativa) cancelar_acao(agora);
      compat_parado_ = false;
      compat_tem_alvo_ = false;
      fogo_compat_ = false;
      if (out_ && !acao_.ativa) out_->led(false);
      break;
    case 'L': case 'C': case 'R': case '4': case '6': {
      if (acao_.ativa) { m = MOT_COMBATE; break; }
      int32_t base = compat_tem_alvo_ ? compat_alvo_mdeg_ : ang_mdeg_;
      int32_t dest = 0;
      if (c == 'L') dest = PAN_ESQUERDA * 1000;
      else if (c == 'C') dest = PAN_CENTRO * 1000;
      else if (c == 'R') dest = PAN_DIREITA * 1000;
      else if (c == '4') dest = base + PASSO_AJUSTE * 1000;
      else dest = base - PASSO_AJUSTE * 1000;
      compat_parado_ = true;
      compat_tem_alvo_ = true;
      compat_alvo_mdeg_ = limitar(dest, PAN_MIN * 1000, PAN_MAX * 1000);
      resto_ = 0;
      break;
    }
    case 'F':
      compat_parado_ = true;
      compat_tem_alvo_ = false;
      fogo_compat_ = true;
      if (out_) out_->led(true);
      m = pode_disparar(agora);
      if (!m) iniciar_acao(agora, nullptr, 0, 3, true);
      break;
    case 'B':
      m = pode_disparar(agora);
      if (!m) iniciar_acao(agora, nullptr, 0, 3, true);
      break;
  }
  if (m) snprintf(out, cap, "recusado:%s", nome_motivo(m));
  else snprintf(out, cap, "ok");
  return 200;
}

}  // namespace vigia
