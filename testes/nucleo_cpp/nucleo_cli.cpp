// Executor host do NUCLEO REAL do firmware (vigia_protecao + vigia_arbitro),
// com relogio simulado de 1 ms. Usado pelos vetores de contrato.
//
// Entrada (stdin), uma linha por requisicao:
//   <t_relativo> <rota> <tamanho> <corpo de 'tamanho' bytes>
//   rota: status | sessao | comando | cmd | serial | avancar
//   Para cmd/serial o corpo e a letra.
// Saida (stdout), uma linha JSON por requisicao:
//   {"http":N,"json":<corpo JSON ou null>,"texto":"...","d":{telemetria}}
// A cada ms simulado: protecao.tick(ms) e depois arbitro.passo(ms), como a
// tarefa de protecao de prioridade maior seguida do loop da aplicacao.
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "vigia_arbitro.h"
#include "vigia_protecao.h"

using namespace vigia;

struct ReleSim : SaidaRele {
  bool pino = false;
  bool teve_ligado = false, teve_desligado = false;
  uint32_t ligado_em = 0, desligado_em = 0;
  uint32_t* agora_rel = nullptr;
  void escrever(bool l) override {
    if (l && !pino) { teve_ligado = true; ligado_em = *agora_rel; }
    if (!l && pino) { teve_desligado = true; desligado_em = *agora_rel; }
    pino = l;
  }
  bool ler() override { return pino; }
};

struct SaidasSim : SaidasAplicacao {
  bool solto = false;
  int grau = 90;
  bool led_ = false;
  void soltar_servo() override { solto = true; }
  void prender_servo(int g) override { solto = false; grau = g; }
  void escrever_servo(int g) override { grau = g; }
  void led(bool l) override { led_ = l; }
};

static void escapar(const char* s, char* out, size_t cap) {
  size_t n = 0;
  for (; *s && n + 7 < cap; s++) {
    unsigned char c = (unsigned char)*s;
    if (c == '"' || c == '\\') { out[n++] = '\\'; out[n++] = (char)c; }
    else if (c < 0x20) { n += (size_t)snprintf(out + n, cap - n, "\\u%04x", c); }
    else out[n++] = (char)c;
  }
  out[n] = '\0';
}

int main(int argc, char** argv) {
  uint32_t t0 = 0, boot_id = 0x5eed0001u, segredo = 0x13579bdfu;
  bool falha = false;
  for (int i = 1; i < argc; i++) {
    if (!strcmp(argv[i], "--t0") && i + 1 < argc) t0 = (uint32_t)strtoul(argv[++i], nullptr, 10);
    else if (!strcmp(argv[i], "--boot-id") && i + 1 < argc) boot_id = (uint32_t)strtoul(argv[++i], nullptr, 16);
    else if (!strcmp(argv[i], "--segredo") && i + 1 < argc) segredo = (uint32_t)strtoul(argv[++i], nullptr, 16);
    else if (!strcmp(argv[i], "--falha-protecao")) falha = true;
  }

  static uint32_t rel = 0;
  ReleSim rele;
  rele.agora_rel = &rel;
  SaidasSim saidas;
  static Protecao prot;
  static Arbitro arb;
  prot.iniciar(&rele, t0, !falha);
  arb.iniciar(&prot, &saidas, t0, boot_id, segredo);

  static char linha[4096], corpo[2048], resp[RESPOSTA_MAX * 2], esc[RESPOSTA_MAX * 4];
  while (fgets(linha, sizeof linha, stdin)) {
    unsigned long t_rel = 0, tam = 0;
    char rota[16] = {0};
    int lidos = 0;
    if (sscanf(linha, "%lu %15s %lu %n", &t_rel, rota, &tam, &lidos) < 3) continue;
    if (tam >= sizeof corpo) tam = sizeof corpo - 1;
    memcpy(corpo, linha + lidos, tam);
    corpo[tam] = '\0';

    while (rel < (uint32_t)t_rel) {
      rel++;
      uint32_t abs_t = t0 + rel;
      if (!falha) prot.tick(abs_t);
      arb.passo(abs_t);
    }
    uint32_t agora = t0 + rel;

    int http = 200;
    bool eh_json = false;
    resp[0] = '\0';
    if (!strcmp(rota, "status")) { http = arb.status_json(agora, resp, sizeof resp); eh_json = true; }
    else if (!strcmp(rota, "sessao")) { http = arb.http_sessao(agora, corpo, tam, resp, sizeof resp); eh_json = true; }
    else if (!strcmp(rota, "comando")) { http = arb.http_comando(agora, corpo, tam, resp, sizeof resp); eh_json = true; }
    else if (!strcmp(rota, "cmd") || !strcmp(rota, "serial")) { http = arb.letra(agora, corpo[0], resp, sizeof resp); }
    else if (!strcmp(rota, "avancar")) { http = 0; }

    InstantaneoProtecao s{};
    prot.ler(&s);
    char ligado[16], desligado[16];
    if (rele.teve_ligado) snprintf(ligado, sizeof ligado, "%lu", (unsigned long)rele.ligado_em); else strcpy(ligado, "null");
    if (rele.teve_desligado) snprintf(desligado, sizeof desligado, "%lu", (unsigned long)rele.desligado_em); else strcpy(desligado, "null");
    escapar(eh_json ? "" : resp, esc, sizeof esc);
    printf("{\"http\":%d,\"json\":%s,\"texto\":\"%s\",\"d\":{\"t\":%lu,\"rele\":%s,\"rele_ligado_em\":%s,"
           "\"rele_desligado_em\":%s,\"servo_solto\":%s,\"pan\":%d,\"led\":%s,\"ticks\":%lu}}\n",
           http, eh_json && resp[0] ? resp : "null", esc, (unsigned long)rel, rele.pino ? "true" : "false",
           ligado, desligado, saidas.solto ? "true" : "false", saidas.grau, saidas.led_ ? "true" : "false",
           (unsigned long)s.ticks);
    fflush(stdout);
  }
  return 0;
}
