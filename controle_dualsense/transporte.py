"""Transporte HTTP limitado para o S3 (somente rede local confiavel).

Uma chamada por vez (o despachante garante), timeout curto e NENHUM retry.
Timeout ou erro depois de enviar -> Resposta(desconhecido=True).
"""

import http.client
import ipaddress
import json
import socket

from .protocolo import Resposta

TIMEOUT_S = 0.200
ROTAS = {"status": ("GET", "/status"), "sessao": ("POST", "/api/v1/session"), "comando": ("POST", "/api/v1/command")}
RESPOSTA_MAX = 4096


def validar_host(ip):
    """Aceita somente IP literal privado/loopback/link-local (sem nomes, sem porta)."""
    try:
        end = ipaddress.ip_address(ip)
    except ValueError:
        raise ValueError(f"IP invalido para o atuador: {ip!r}")
    if not (end.is_private or end.is_loopback or end.is_link_local):
        raise ValueError(f"o controle protegido so fala com IP de rede local: {ip}")
    return str(end)


class TransporteHTTP:
    def __init__(self, ip, timeout=TIMEOUT_S, porta=80):
        self.host = validar_host(ip)
        self.porta = porta
        self.timeout = timeout

    def enviar(self, rota, corpo):
        metodo, caminho = ROTAS[rota]
        conn = http.client.HTTPConnection(self.host, self.porta, timeout=self.timeout)
        try:
            dados = corpo.encode("utf-8") if corpo is not None else None
            cab = {"Content-Type": "application/json"} if dados is not None else {}
            conn.request(metodo, caminho, body=dados, headers=cab)
            r = conn.getresponse()
            bruto = r.read(RESPOSTA_MAX + 1)
            if len(bruto) > RESPOSTA_MAX:
                return Resposta(http=r.status, desconhecido=True, erro="resposta_grande")
            try:
                js = json.loads(bruto.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                return Resposta(http=r.status, desconhecido=True, erro="resposta_nao_json")
            if not isinstance(js, dict):
                return Resposta(http=r.status, desconhecido=True, erro="resposta_nao_objeto")
            return Resposta(http=r.status, json=js)
        except (socket.timeout, TimeoutError):
            return Resposta(desconhecido=True, erro="timeout")
        except (OSError, http.client.HTTPException) as e:
            # Conexao recusada antes de enviar tambem cai aqui; tratar como
            # desconhecido e conservador (nunca leva a repetir com ID novo).
            return Resposta(desconhecido=True, erro=type(e).__name__)
        finally:
            conn.close()
