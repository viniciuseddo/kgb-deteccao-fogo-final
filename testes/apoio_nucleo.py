"""Ponte de testes: o cliente Python fala com o NUCLEO C++ REAL (nucleo_cli)
como se fosse o S3, com relogio simulado e injecao de falhas de transporte.
"""

import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import apoio_cpp  # noqa: E402
from controle_dualsense.protocolo import Resposta  # noqa: E402


def executavel():
    return apoio_cpp.compilar("nucleo_cli", [os.path.join(apoio_cpp.NUCLEO_CPP, "nucleo_cli.cpp")])


class Nucleo:
    def __init__(self, exe=None, t0=0, falha=False):
        import threading
        self.lock = threading.Lock()
        args = [exe or executavel(), "--t0", str(t0)]
        if falha:
            args.append("--falha-protecao")
        self.p = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True, encoding="utf-8")

    def enviar(self, t, rota, corpo=""):
        dados = corpo.encode("utf-8")
        with self.lock:
            self.p.stdin.write(f"{t} {rota} {len(dados)} {corpo}\n")
            self.p.stdin.flush()
            linha = self.p.stdout.readline()
        if not linha:
            raise RuntimeError("nucleo_cli terminou: " + self.p.stderr.read())
        return json.loads(linha)

    def fechar(self):
        try:
            self.p.stdin.close()
            self.p.wait(timeout=5)
        except Exception:
            self.p.kill()
            self.p.wait(timeout=5)
        finally:
            self.p.stdout.close()
            self.p.stderr.close()


class Relogio:
    def __init__(self, t=0.0):
        self.t = t

    def __call__(self):
        return self.t

    def ms(self):
        return int(round(self.t * 1000))


class RelogioReal:
    """Tempo real para testes com threads; 'adiantar_ms' desloca o relogio do
    nucleo (ex.: passar a inibicao de boot sem esperar 12 s)."""

    def __init__(self, adiantar_ms=0):
        import time
        self._time = time
        self.inicio = time.monotonic()
        self.adiantar_ms = adiantar_ms

    def __call__(self):
        return self._time.monotonic() - self.inicio

    def ms(self):
        return int((self._time.monotonic() - self.inicio) * 1000) + self.adiantar_ms


class TransporteNucleo:
    """Implementa a interface do TransporteHTTP sobre o nucleo real."""

    def __init__(self, nucleo, relogio):
        self.n = nucleo
        self.r = relogio
        self.ultimo_ms = 0
        self.perder_resposta = set()   # acoes cuja PROXIMA resposta se perde (requisicao entregue)
        self.offline = False
        self.log = []

    def _t(self):
        self.ultimo_ms = max(self.ultimo_ms, self.r.ms())
        return self.ultimo_ms

    def enviar(self, rota, corpo):
        if self.offline:
            return Resposta(desconhecido=True, erro="timeout")
        saida = self.n.enviar(self._t(), rota, corpo or "")
        acao = None
        if rota == "comando" and corpo:
            acao = json.loads(corpo).get("acao")
        self.log.append((self.ultimo_ms, rota, acao, (saida.get("json") or {}).get("resultado"),
                         (saida.get("json") or {}).get("motivo")))
        if acao in self.perder_resposta:
            self.perder_resposta.discard(acao)
            return Resposta(desconhecido=True, erro="timeout")
        return Resposta(http=saida["http"], json=saida.get("json"))

    def telemetria(self):
        return self.n.enviar(self._t(), "avancar")["d"]

    def status(self):
        return self.n.enviar(self._t(), "status")["json"]

    def letra(self, c):
        return self.n.enviar(self._t(), "cmd", c)
