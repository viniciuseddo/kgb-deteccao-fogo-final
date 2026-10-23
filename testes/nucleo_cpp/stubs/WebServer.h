#pragma once
#include <map>
#include "Arduino.h"
enum HTTPMethod { HTTP_ANY = 0, HTTP_GET = 1, HTTP_POST = 3 };

class WebServer {
 public:
  struct Pedido {
    Pedido() : metodo(0) {}
    Pedido(std::string u, int m, std::map<std::string, std::string> a) : uri(u), metodo(m), args(a) {}
    std::string uri; int metodo; std::map<std::string, std::string> args;
    std::string host = "192.168.4.1"; std::map<std::string, std::string> headers;
  };
  struct Resposta { int codigo; std::string tipo; std::string corpo; };
  explicit WebServer(int) {}
  void on(const char* uri, void (*h)()) { rotas_.push_back({uri, HTTP_ANY, h}); }
  void on(const char* uri, HTTPMethod m, void (*h)()) { rotas_.push_back({uri, (int)m, h}); }
  void begin() { iniciado = true; }
  void handleClient();
  bool hasArg(const char* k) const { return atual_.args.count(k) > 0; }
  const String& arg(const char* k);
  String hostHeader() const { return String(atual_.host); }
  void collectHeaders(const char**, size_t) {}
  String header(const char* k) const {
    auto it = atual_.headers.find(k);
    return String(it == atual_.headers.end() ? std::string() : it->second);
  }
  void send(int codigo, const char* tipo, const char* corpo) { respostas.push_back({codigo, tipo, corpo}); }

  // ---- controle do teste ----
  std::deque<Pedido> fila;
  std::vector<Resposta> respostas;
  bool iniciado = false;

 private:
  struct Rota { std::string uri; int metodo; void (*h)(); };
  std::vector<Rota> rotas_;
  Pedido atual_;
  String arg_;
};
