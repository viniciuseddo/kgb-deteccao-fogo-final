// Testes unitarios HOST do nucleo real (vigia_protecao / vigia_arbitro / vigia_json).
// Complementam os vetores de contrato com casos que dependem de controlar o
// escalonamento: aplicacao retida, falha de releitura, passos grandes de tempo.
#include <stdio.h>
#include <string.h>

#include <atomic>
#include <thread>

#include "vigia_arbitro.h"
#include "vigia_json.h"
#include "vigia_protecao.h"

using namespace vigia;

static int falhas = 0, verificacoes = 0;
#define CHECA(c, ...) do { verificacoes++; if (!(c)) { printf("FALHA %s:%d: ", __func__, __LINE__); printf(__VA_ARGS__); printf("\n"); falhas++; } } while (0)

struct Rele : SaidaRele {
  bool pino = true;  // comeca LIGADO para provar que iniciar() desliga
  int travar_desligado = 0;  // quantas escritas de desligar "nao pegam"
  int escritas = 0;
  void escrever(bool l) override {
    escritas++;
    if (!l && travar_desligado > 0) { travar_desligado--; return; }
    pino = l;
  }
  bool ler() override { return pino; }
};

struct Saidas : SaidasAplicacao {
  bool solto = false;
  int grau = 90;
  void soltar_servo() override { solto = true; }
  void prender_servo(int g) override { solto = false; grau = g; }
  void escrever_servo(int g) override { grau = g; }
  void led(bool) override {}
};

static char buf[2048];

// Aplicacao retida: so a protecao recebe ticks; o corte acontece no prazo.
static void protecao_corta_com_aplicacao_retida() {
  Rele r; Saidas s; Protecao p; Arbitro a;
  p.iniciar(&r, 0, true);
  CHECA(!r.pino, "iniciar deve desligar o rele");
  a.iniciar(&p, &s, 0, 1, 2);
  for (uint32_t t = 1; t <= 12000; t++) { p.tick(t); a.passo(t); }
  a.letra(12000, 'B', buf, sizeof buf);
  CHECA(!strcmp(buf, "ok"), "B: %s", buf);
  CHECA(s.solto, "servo deve ser solto antes de energizar");
  uint32_t on = 0, off = 0;
  // A partir daqui a aplicacao NAO roda passo() por 7 s.
  for (uint32_t t = 12001; t <= 19000; t++) {
    bool antes = r.pino;
    p.tick(t);
    if (!antes && r.pino) on = t;
    if (antes && !r.pino) off = t;
  }
  CHECA(on == 12001, "energizou em %u", (unsigned)on);
  CHECA(off == on + 5000, "desligou em %u (on %u)", (unsigned)off, (unsigned)on);
  CHECA(a.em_combate(), "app ainda nao viu o fim (estava retida)");
  a.passo(19001);
  CHECA(!a.em_combate() && !s.solto, "app processa o fim ao voltar");
}

// Novos pedidos durante a agua nao reiniciam nem prolongam o prazo.
static void pedidos_repetidos_nao_estendem() {
  Rele r; Protecao p;
  p.iniciar(&r, 0, true);
  p.pedir_inicio(1);
  p.tick(12000);
  CHECA(r.pino, "deveria energizar em 12000");
  for (uint32_t t = 12001; t < 17000; t++) {
    if (t % 500 == 0) p.pedir_inicio(100 + t);
    p.tick(t);
  }
  CHECA(r.pino, "ainda ligado antes do prazo");
  p.tick(17000);
  CHECA(!r.pino, "desligado exatamente no prazo original");
  InstantaneoProtecao s{};
  CHECA(p.ler(&s), "leitura estavel");
  CHECA(s.proximo_inicio == 24000, "cooldown medido da energizacao: %u", (unsigned)s.proximo_inicio);
}

// Releitura do pino discorda: nao declara fim e continua tentando.
static void falha_de_desligamento_mantem_combate() {
  Rele r; Saidas s; Protecao p; Arbitro a;
  p.iniciar(&r, 0, true);
  a.iniciar(&p, &s, 0, 1, 2);
  for (uint32_t t = 1; t <= 12000; t++) { p.tick(t); a.passo(t); }
  a.letra(12000, 'B', buf, sizeof buf);
  for (uint32_t t = 12001; t < 17001; t++) { p.tick(t); a.passo(t); }
  r.travar_desligado = 3;
  for (uint32_t t = 17001; t <= 17003; t++) { p.tick(t); a.passo(t); }
  CHECA(r.pino, "simulacao: pino travado ligado");
  CHECA(a.em_combate(), "nao pode sair do combate sem confirmar desligado");
  CHECA(a.fase(17003) == F_ENERGIZADA || a.fase(17003) == F_DESLIGAMENTO_PENDENTE, "fase %d", a.fase(17003));
  p.tick(17004); a.passo(17004);
  CHECA(!r.pino && !a.em_combate(), "confirmado na 4a tentativa");
}

// Falha de criacao da protecao: tudo recusado e rele desligado.
static void protecao_indisponivel() {
  Rele r; Saidas s; Protecao p; Arbitro a;
  p.iniciar(&r, 0, false);
  a.iniciar(&p, &s, 0, 1, 2);
  a.passo(13000);
  a.letra(13000, 'B', buf, sizeof buf);
  CHECA(strstr(buf, "protecao_indisponivel"), "B: %s", buf);
  p.pedir_inicio(7);
  p.tick(13001);
  CHECA(!r.pino, "inicio recusado pela propria protecao");
}

// Passo de tempo grande nao gera salto do angulo.
static void passo_grande_limitado() {
  Rele r; Saidas s; Protecao p; Arbitro a;
  p.iniciar(&r, 0, true);
  a.iniciar(&p, &s, 0, 1, 2);
  int antes = a.pan_graus();
  a.passo(10000);  // 10 s de uma vez em AUTO
  int d = a.pan_graus() - antes;
  if (d < 0) d = -d;
  CHECA(d <= 6, "varredura saltou %d graus em um passo", d);
}

static void json_estrito() {
  ObjetoJson o;
  const char* ruins[] = {"", "{", "[]", "{\"a\":1,}", "{\"a\":1}x", "{\"a\":{}}", "{\"a\":[1]}", "{\"a\":\"\\u0041\"}",
                         "{\"a\":01}", "{\"a\":1.}", "{\"a\":-}", "{\"a\":tru}", "{\"a\":1,\"a\":2}", "{a:1}",
                         "{\"a\":\"x\ny\"}", "{\"a\":1e}", "{\"a\":1234567890123456789}"};
  for (const char* t : ruins) CHECA(!json_ler_plano(t, strlen(t), &o), "deveria rejeitar: %s", t);
  const char* bom = " { \"v\" : 1 , \"vel\":-0.25,\"s\":\"a\\\"b\",\"b\":true,\"n\":null,\"e\":1e2 } ";
  CHECA(json_ler_plano(bom, strlen(bom), &o), "deveria aceitar");
  CHECA(o.n == 6, "n=%d", o.n);
  const CampoJson* v = o.achar("v");
  CHECA(v && v->inteiro && v->i == 1, "v");
  const CampoJson* vel = o.achar("vel");
  CHECA(vel && !vel->inteiro && vel->d == -0.25, "vel");
  const CampoJson* s = o.achar("s");
  CHECA(s && !strcmp(s->str, "a\"b"), "string com escape");
  const CampoJson* e = o.achar("e");
  CHECA(e && !e->inteiro, "expoente nao e inteiro");
  // corpo grande demais e recusado pela rota
  Rele r; Saidas sa; Protecao p; Arbitro a;
  p.iniciar(&r, 0, true);
  a.iniciar(&p, &sa, 0, 1, 2);
  static char grande[700];
  memset(grande, ' ', sizeof grande);
  grande[0] = '{'; grande[sizeof grande - 2] = '}'; grande[sizeof grande - 1] = 0;
  int cod = a.http_comando(1, grande, strlen(grande), buf, sizeof buf);
  CHECA(cod == 400 && strstr(buf, "json_invalido"), "corpo grande: %d %s", cod, buf);
}

// Leitor e escritor concorrentes do instantaneo seqlock (threads reais).
static void seqlock_concorrente() {
  Rele r; Protecao p;
  p.iniciar(&r, 0, true);
  std::atomic<bool> fim{false};
  std::atomic<long> inconsistentes{0}, leituras{0};
  std::thread leitor([&] {
    InstantaneoProtecao s{};
    while (!fim) {
      if (p.ler(&s)) {
        leituras++;
        // Invariante publicado junto: ligado <=> acao_ativa != 0 (fora de falha).
        if (s.fase == P_ENERGIZADA && (s.acao_ativa == 0 || !s.rele_ligado)) inconsistentes++;
        if (s.fase == P_OCIOSA && s.rele_ligado) inconsistentes++;
      }
    }
  });
  uint32_t num = 1;
  for (uint32_t t = 12000; t < 12000 + 200000; t++) {
    if (t % 13000 == 0) p.pedir_inicio(num++);
    if (t % 13000 == 3000) p.pedir_cancelamento(num - 1, t);
    p.tick(t);
  }
  fim = true;
  leitor.join();
  CHECA(leituras > 0, "sem leituras");
  CHECA(inconsistentes == 0, "%ld leituras inconsistentes", (long)inconsistentes);
}

static void token(const char* json, const char* chave, char* out, size_t cap) {
  char padrao[32];
  snprintf(padrao, sizeof padrao, "\"%s\":\"", chave);
  const char* p = strstr(json, padrao);
  out[0] = 0;
  if (!p) return;
  p += strlen(padrao);
  size_t n = 0;
  while (*p && *p != '"' && n + 1 < cap) out[n++] = *p++;
  out[n] = 0;
}

// Achado 6: lease vencido nao pode ser renovado por requisicao atendida
// antes do proximo passo() (handleClient retido).
static void lease_expira_no_recebimento() {
  Rele r; Saidas s; Protecao p; Arbitro a;
  p.iniciar(&r, 0, true);
  a.iniciar(&p, &s, 0, 0x5eed0001u, 7);
  for (uint32_t t = 1; t <= 100; t++) { p.tick(t); a.passo(t); }
  static char st[2048], corpo[512], jan[64];
  a.status_json(100, st, sizeof st);
  token(st, "janela_abertura", jan, sizeof jan);
  snprintf(corpo, sizeof corpo, "{\"v\":1,\"boot_id\":\"5eed0001\",\"session_open_id\":\"o1\",\"janela\":\"%s\"}", jan);
  a.http_sessao(100, corpo, strlen(corpo), buf, sizeof buf);
  token(buf, "janela_c", jan, sizeof jan);
  snprintf(corpo, sizeof corpo, "{\"v\":1,\"boot_id\":\"5eed0001\",\"sessao\":\"s1\",\"acao\":\"manual\",\"seq\":1,\"id\":\"m1\",\"janela\":\"%s\"}", jan);
  a.http_comando(100, corpo, strlen(corpo), buf, sizeof buf);
  CHECA(a.modo() == M_MANUAL, "manual");
  // passo() nao roda depois de 100; lease vence em 1600. Pedido em 1601.
  snprintf(corpo, sizeof corpo, "{\"v\":1,\"boot_id\":\"5eed0001\",\"sessao\":\"s1\",\"acao\":\"janela\"}");
  a.http_comando(1601, corpo, strlen(corpo), buf, sizeof buf);
  token(buf, "janela_c", jan, sizeof jan);
  snprintf(corpo, sizeof corpo, "{\"v\":1,\"boot_id\":\"5eed0001\",\"sessao\":\"s1\",\"acao\":\"renovar\",\"seq\":2,\"id\":\"r2\",\"janela\":\"%s\"}", jan);
  a.http_comando(1601, corpo, strlen(corpo), buf, sizeof buf);
  CHECA(strstr(buf, "\"resultado\":\"recusado\"") && strstr(buf, "sem_lease"), "renovou lease vencido: %s", buf);
  CHECA(a.modo() == M_AUTO, "deveria estar AUTO");
}

int main() {
  lease_expira_no_recebimento();
  protecao_corta_com_aplicacao_retida();
  pedidos_repetidos_nao_estendem();
  falha_de_desligamento_mantem_combate();
  protecao_indisponivel();
  passo_grande_limitado();
  json_estrito();
  seqlock_concorrente();
  printf("verificacoes=%d falhas=%d\n", verificacoes, falhas);
  return falhas ? 1 : 0;
}
