#include "vigia_json.h"
#include <stdio.h>
#include <string.h>

namespace vigia {

const CampoJson* ObjetoJson::achar(const char* chave) const {
  for (int k = 0; k < n; k++)
    if (strcmp(campos[k].chave, chave) == 0) return &campos[k];
  return nullptr;
}

namespace {

struct Leitor {
  const char* p;
  const char* fim;
  void ws() { while (p < fim && (*p == ' ' || *p == '\t' || *p == '\n' || *p == '\r')) p++; }
  bool tem() const { return p < fim; }
};

bool ler_string(Leitor& L, char* dst, size_t cap) {
  if (!L.tem() || *L.p != '"') return false;
  L.p++;
  size_t n = 0;
  while (L.tem()) {
    char c = *L.p++;
    if (c == '"') { dst[n] = '\0'; return true; }
    if ((unsigned char)c < 0x20) return false;
    if (c == '\\') {
      if (!L.tem()) return false;
      char e = *L.p++;
      switch (e) {
        case '"': c = '"'; break;
        case '\\': c = '\\'; break;
        case '/': c = '/'; break;
        case 'b': c = '\b'; break;
        case 'f': c = '\f'; break;
        case 'n': c = '\n'; break;
        case 'r': c = '\r'; break;
        case 't': c = '\t'; break;
        default: return false;  // \u e outros nao aceitos
      }
    }
    if (n + 1 >= cap) return false;
    dst[n++] = c;
  }
  return false;
}

bool ler_numero(Leitor& L, CampoJson* c) {
  const char* ini = L.p;
  if (L.tem() && *L.p == '-') L.p++;
  if (!L.tem()) return false;
  if (*L.p == '0') {
    L.p++;
  } else if (*L.p >= '1' && *L.p <= '9') {
    while (L.tem() && *L.p >= '0' && *L.p <= '9') L.p++;
  } else {
    return false;
  }
  bool inteiro = true;
  if (L.tem() && *L.p == '.') {
    inteiro = false;
    L.p++;
    if (!L.tem() || *L.p < '0' || *L.p > '9') return false;
    while (L.tem() && *L.p >= '0' && *L.p <= '9') L.p++;
  }
  if (L.tem() && (*L.p == 'e' || *L.p == 'E')) {
    inteiro = false;
    L.p++;
    if (L.tem() && (*L.p == '+' || *L.p == '-')) L.p++;
    if (!L.tem() || *L.p < '0' || *L.p > '9') return false;
    while (L.tem() && *L.p >= '0' && *L.p <= '9') L.p++;
  }
  size_t len = (size_t)(L.p - ini);
  if (len == 0 || len > 24) return false;
  char tmp[32];
  memcpy(tmp, ini, len);
  tmp[len] = '\0';
  c->tipo = J_NUM;
  c->inteiro = inteiro;
  c->d = 0;
  c->i = 0;
  if (inteiro) {
    // ate 18 digitos cabe em int64 sem estouro
    bool neg = tmp[0] == '-';
    size_t dig = len - (neg ? 1 : 0);
    if (dig > 18) return false;
    int64_t v = 0;
    for (size_t k = neg ? 1 : 0; k < len; k++) v = v * 10 + (tmp[k] - '0');
    c->i = neg ? -v : v;
    c->d = (double)c->i;
  } else {
    double v = 0;
    if (sscanf(tmp, "%lf", &v) != 1) return false;
    c->d = v;
  }
  return true;
}

bool ler_literal(Leitor& L, const char* lit) {
  size_t n = strlen(lit);
  if ((size_t)(L.fim - L.p) < n || memcmp(L.p, lit, n) != 0) return false;
  L.p += n;
  return true;
}

}  // namespace

bool json_ler_plano(const char* texto, size_t len, ObjetoJson* o) {
  o->n = 0;
  if (!texto) return false;
  Leitor L{texto, texto + len};
  L.ws();
  if (!L.tem() || *L.p != '{') return false;
  L.p++;
  L.ws();
  if (L.tem() && *L.p == '}') {
    L.p++;
    L.ws();
    return !L.tem();
  }
  while (true) {
    if (o->n >= ObjetoJson::MAX) return false;
    CampoJson* c = &o->campos[o->n];
    L.ws();
    if (!ler_string(L, c->chave, sizeof(c->chave))) return false;
    for (int k = 0; k < o->n; k++)
      if (strcmp(o->campos[k].chave, c->chave) == 0) return false;  // repetida
    L.ws();
    if (!L.tem() || *L.p != ':') return false;
    L.p++;
    L.ws();
    if (!L.tem()) return false;
    char ch = *L.p;
    if (ch == '"') {
      c->tipo = J_STR;
      if (!ler_string(L, c->str, sizeof(c->str))) return false;
    } else if (ch == 't') {
      if (!ler_literal(L, "true")) return false;
      c->tipo = J_BOOL; c->b = true;
    } else if (ch == 'f') {
      if (!ler_literal(L, "false")) return false;
      c->tipo = J_BOOL; c->b = false;
    } else if (ch == 'n') {
      if (!ler_literal(L, "null")) return false;
      c->tipo = J_NULL;
    } else if (ch == '-' || (ch >= '0' && ch <= '9')) {
      if (!ler_numero(L, c)) return false;
    } else {
      return false;  // objeto, lista ou lixo
    }
    o->n++;
    L.ws();
    if (!L.tem()) return false;
    if (*L.p == ',') { L.p++; continue; }
    if (*L.p == '}') { L.p++; break; }
    return false;
  }
  L.ws();
  return !L.tem();
}

// ------------------------------------------------------------- escrita
EscritorJson::EscritorJson(char* buf, size_t cap)
    : buf_(buf), cap_(cap), n_(0), nivel_(0), estouro_(false) {
  if (cap_) buf_[0] = '\0';
  for (bool& b : primeiro_) b = true;
}

void EscritorJson::put(char c) {
  if (n_ + 1 >= cap_) { estouro_ = true; return; }
  buf_[n_++] = c;
  buf_[n_] = '\0';
}
void EscritorJson::puts_(const char* s) { while (*s) put(*s++); }

void EscritorJson::sep() {
  if (nivel_ <= 0) return;
  if (!primeiro_[nivel_]) put(',');
  primeiro_[nivel_] = false;
}

void EscritorJson::escapado(const char* s) {
  put('"');
  for (; *s; s++) {
    unsigned char c = (unsigned char)*s;
    if (c == '"' || c == '\\') { put('\\'); put((char)c); }
    else if (c < 0x20) { char t[8]; snprintf(t, sizeof t, "\\u%04x", c); puts_(t); }
    else put((char)c);
  }
  put('"');
}

void EscritorJson::chave(const char* k) { sep(); escapado(k); put(':'); }

void EscritorJson::abre() {
  sep();
  put('{');
  if (nivel_ < 7) nivel_++;
  primeiro_[nivel_] = true;
}
void EscritorJson::fecha() { put('}'); if (nivel_ > 0) nivel_--; }
void EscritorJson::abre_obj(const char* k) {
  chave(k);
  put('{');
  if (nivel_ < 7) nivel_++;
  primeiro_[nivel_] = true;
}
void EscritorJson::abre_lista(const char* k) {
  chave(k);
  put('[');
  if (nivel_ < 7) nivel_++;
  primeiro_[nivel_] = true;
}
void EscritorJson::fecha_lista() { put(']'); if (nivel_ > 0) nivel_--; }
void EscritorJson::item_str(const char* v) { sep(); escapado(v); }

void EscritorJson::str(const char* k, const char* v) {
  chave(k);
  if (v) escapado(v); else puts_("null");
}
void EscritorJson::num(const char* k, int64_t v) {
  chave(k);
  char t[24];
  int p = 23;
  t[p] = '\0';
  bool neg = v < 0;
  uint64_t u = neg ? (uint64_t)(-(v + 1)) + 1u : (uint64_t)v;
  do { t[--p] = (char)('0' + (u % 10)); u /= 10; } while (u && p > 1);
  if (neg) t[--p] = '-';
  puts_(t + p);
}
void EscritorJson::bol(const char* k, bool v) { chave(k); puts_(v ? "true" : "false"); }
void EscritorJson::nulo(const char* k) { chave(k); puts_("null"); }

}  // namespace vigia
