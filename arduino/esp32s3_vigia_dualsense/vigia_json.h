// JSON minimo e estrito para o protocolo do Vigia.
// Entrada: um unico objeto plano {chave: string|numero|true|false|null}.
// Objetos/arrays aninhados, chaves repetidas, \u, lixo apos '}' e corpos
// acima do limite sao rejeitados. Sem alocacao dinamica.
#pragma once
#include <stddef.h>
#include <stdint.h>

namespace vigia {

enum TipoJson : uint8_t { J_STR, J_NUM, J_BOOL, J_NULL };

struct CampoJson {
  char chave[20];
  TipoJson tipo;
  char str[48];      // strings maiores sao rejeitadas
  bool inteiro;      // numero sem fracao/expoente
  int64_t i;
  double d;
  bool b;
};

struct ObjetoJson {
  static const int MAX = 16;
  CampoJson campos[MAX];
  int n;
  const CampoJson* achar(const char* chave) const;
};

// Retorna true se 'texto' (len bytes) e um objeto plano valido.
bool json_ler_plano(const char* texto, size_t len, ObjetoJson* saida);

// ------------------------------------------------------------- escrita
class EscritorJson {
 public:
  EscritorJson(char* buf, size_t cap);
  void abre();                    // {
  void fecha();                   // }
  void abre_lista(const char* k); // "k":[
  void fecha_lista();             // ]
  void abre_obj(const char* k);   // "k":{
  void item_str(const char* v);   // elemento de lista
  void str(const char* k, const char* v);  // v == nullptr -> null
  void num(const char* k, int64_t v);
  void bol(const char* k, bool v);
  void nulo(const char* k);
  size_t tamanho() const { return n_; }
  bool estourou() const { return estouro_; }
  const char* texto() const { return buf_; }

 private:
  void sep();
  void put(char c);
  void puts_(const char* s);
  void chave(const char* k);
  void escapado(const char* s);
  char* buf_;
  size_t cap_, n_;
  bool primeiro_[8];
  int nivel_;
  bool estouro_;
};

}  // namespace vigia
