// Nucleo da aplicacao do Vigia DualSense: arbitragem de modos, lease,
// trajetoria nao bloqueante, sessoes/RECUPERACAO, janelas de frescor,
// deduplicacao e perfis COMPAT/PROTEGIDO (design R2 §3, §5, §6).
//
// Roda no contexto da aplicacao (loop/HTTP). Nao toca no rele: pede inicio e
// cancelamento a Protecao e le o instantaneo publicado por ela. Sem I/O,
// sem heap: os adaptadores (.ino) cuidam de Wi-Fi, servo, LED e LCD.
#pragma once
#include <stddef.h>
#include <stdint.h>
#include "vigia_config.h"
#include "vigia_json.h"
#include "vigia_protecao.h"

namespace vigia {

// Saidas nao criticas, chamadas sincronamente no contexto da aplicacao.
class SaidasAplicacao {
 public:
  virtual void soltar_servo() = 0;            // antes de pedir energizacao
  virtual void prender_servo(int graus) = 0;  // ao fim do combate
  virtual void escrever_servo(int graus) = 0; // so quando o grau inteiro muda
  virtual void led(bool ligado) = 0;
  virtual ~SaidasAplicacao() {}
};

enum Modo : uint8_t { M_AUTO = 0, M_MANUAL = 1 };
enum Perfil : uint8_t { PERFIL_COMPAT = 0, PERFIL_PROTEGIDO = 1 };
enum EstadoSessao : uint8_t { ES_NENHUMA = 0, ES_NORMAL = 1, ES_RECUPERACAO = 2 };
enum FaseAcao : uint8_t { F_OCIOSA = 0, F_ACEITA_PENDENTE = 1, F_ENERGIZADA = 2, F_DESLIGAMENTO_PENDENTE = 3 };

enum Motivo : uint8_t {
  MOT_NENHUM = 0, MOT_JSON, MOT_CAMPO_DESCONHECIDO, MOT_CAMPO_AUSENTE, MOT_TIPO, MOT_VALOR,
  MOT_VERSAO, MOT_BOOT, MOT_SEM_SESSAO, MOT_SESSAO_OBSOLETA, MOT_SEQ_ANTIGA, MOT_ID_CONFLITO,
  MOT_JANELA_EXPIRADA, MOT_JANELA_INVALIDA, MOT_EPOCH_OBSOLETO, MOT_ESCOPO,
  MOT_ACAO_DESCONHECIDA, MOT_RECUPERACAO, MOT_MODO_AUTO, MOT_SEM_LEASE, MOT_COMBATE, MOT_OCUPADO,
  MOT_COOLDOWN, MOT_PROTECAO, MOT_ALVO_OBSOLETO, MOT_AGUA_LEGADA, MOT_PERFIL_PROTEGIDO,
  MOT_TOTAL
};
const char* nome_motivo(Motivo m);

class Arbitro {
 public:
  Arbitro();
  void iniciar(Protecao* p, SaidasAplicacao* s, uint32_t agora, uint32_t boot_id, uint32_t segredo);

  // Um passo da aplicacao: le o instantaneo da protecao, aplica fim de
  // combate, expira lease/velocidade e integra a trajetoria.
  void passo(uint32_t agora);

  // Rotas. Retornam o codigo HTTP e escrevem o corpo em 'saida'.
  int status_json(uint32_t agora, char* saida, size_t cap);
  int http_sessao(uint32_t agora, const char* corpo, size_t len, char* saida, size_t cap);
  int http_comando(uint32_t agora, const char* corpo, size_t len, char* saida, size_t cap);
  // Letras legadas (via /cmd ou Serial). Resposta em texto.
  int letra(uint32_t agora, char c, char* saida, size_t cap);

  // Consultas para adaptadores (LCD/log) e simulacao.
  int pan_graus() const;
  bool servo_solto() const { return acao_.ativa; }
  bool vigiando() const;
  bool em_combate() const { return acao_.ativa; }
  Modo modo() const { return modo_; }
  Perfil perfil() const { return perfil_; }
  FaseAcao fase(uint32_t agora) const;
  bool fogo() const;
  uint32_t control_epoch() const { return epoch_; }

 private:
  struct Acao {
    bool ativa;
    bool legado;
    bool cancel_pedido;
    uint32_t num;
    uint32_t sessao;
    int64_t seq;
    uint8_t origem;  // 0 ia, 1 operador, 2 teclado, 3 legado
    char id[ID_MAX + 1];
  };
  struct Dedup {
    bool usado;
    uint32_t sessao;
    uint32_t hash;
    uint32_t t;
    uint8_t acao;
    bool aceito;
    uint8_t motivo;
    char id[ID_MAX + 1];
  };
  struct Abertura {
    bool usado;
    uint32_t hash;
    bool aceito;
    uint8_t motivo;
    uint32_t sessao;
    uint8_t estado_sessao;
    char open_id[ID_MAX + 1];
    char acao_recuperar[ID_MAX + 1];
  };

  // tempo/trajetoria
  void integrar(uint32_t agora);
  void mover_para(int32_t alvo_mdeg, int32_t vel_mdps, uint32_t dt);
  void ir_auto();
  void expirar_lease(uint32_t agora);
  // combate
  void iniciar_acao(uint32_t agora, const char* id, int64_t seq, uint8_t origem, bool legado);
  void encerrar_combate(uint8_t resultado);
  void cancelar_acao(uint32_t agora);
  uint32_t proximo_efetivo() const;
  Motivo pode_disparar(uint32_t agora) const;
  // janelas
  void cunhar(char escopo, uint32_t vinc, uint32_t agora, char* out, size_t cap) const;
  Motivo validar_janela(const char* tok, char escopo, uint32_t agora) const;
  uint32_t mac(char escopo, uint32_t vinc, uint32_t t, uint32_t sessao) const;
  // respostas
  void escrever_estado(EscritorJson& w, uint32_t agora);
  void escrever_janelas(EscritorJson& w, uint32_t agora);
  int responder_cmd(uint32_t agora, char* out, size_t cap, bool aceito, Motivo m, const char* acao,
                    const char* id, bool duplicado);
  Dedup* achar_dedup(const char* id, uint32_t agora);
  void gravar_dedup(uint32_t agora, const char* id, uint32_t hash, uint8_t acao, bool aceito, Motivo m);
  void nome_sessao(uint32_t num, char* out, size_t cap) const;
  uint32_t ler_sessao(const char* s) const;

  Protecao* prot_;
  SaidasAplicacao* out_;
  InstantaneoProtecao snap_;
  uint32_t boot_id_, segredo_;

  Perfil perfil_;
  Modo modo_;
  bool retorno_auto_;
  uint32_t lease_ate_;
  int32_t vel_mdps_;
  uint32_t vel_ate_;
  uint32_t epoch_;

  int32_t ang_mdeg_;
  int64_t resto_;
  int direcao_;
  uint32_t ultimo_passo_;
  int ultimo_grau_escrito_;

  // perfil COMPAT
  bool compat_parado_;
  bool compat_tem_alvo_;
  int32_t compat_alvo_mdeg_;
  uint32_t compat_ultimo_cmd_;
  bool fogo_compat_;

  // sessao
  uint32_t sessao_;
  uint32_t contador_sessoes_;
  EstadoSessao estado_sessao_;
  int64_t ultimo_seq_;

  Acao acao_;
  uint32_t contador_acoes_;
  uint32_t proximo_local_;
  char ultimo_id_[ID_MAX + 1];
  uint8_t ultimo_resultado_;

  Dedup dedup_[DEDUP_CAPACIDADE];
  int dedup_pos_;
  Abertura aberturas_[ABERTURAS_GUARDADAS];
  int abertura_pos_;
};

}  // namespace vigia
