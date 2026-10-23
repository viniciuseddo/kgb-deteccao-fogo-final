"""Montagem do caminho novo com threads: HID (aquisicao) e controle
(controlador + despachante, uma requisicao por vez). A inferencia YOLO fica
na thread principal do sistema_vigia e so enfileira pedidos.
"""

import threading
import time

from .adaptador_hid import AdaptadorHID
from .controlador import Controlador
from .entrada import PoliticaEntrada
from .protocolo import ClienteProtocolo
from .transporte import TransporteHTTP

PERIODO_CONTROLE_S = 0.005


class ControleDualSense:
    def __init__(self, ip, registro, ao_fronteira_camera, ao_resultado_ia, modulo_hid=None,
                 transporte=None, relogio=time.monotonic):
        self.relogio = relogio
        self.politica = PoliticaEntrada()
        self.cliente = ClienteProtocolo(transporte or TransporteHTTP(ip), relogio)
        self.ctl = Controlador(self.cliente, self.politica, relogio, registro=registro,
                               ao_fronteira_camera=ao_fronteira_camera, ao_resultado_ia=ao_resultado_ia)
        self.hid = AdaptadorHID(self.politica, self.ctl.lock, modulo_hid=modulo_hid, relogio=relogio,
                                ao_log=registro.escrever if registro else None)
        self.rodando = False
        self._thread = None

    def iniciar(self):
        self.rodando = True
        self.hid.iniciar()
        self._thread = threading.Thread(target=self._laco, daemon=True, name="dualsense-controle")
        self._thread.start()

    def _laco(self):
        while self.rodando:
            try:
                self.ctl.passo(self.relogio())
            except Exception as e:  # nunca derruba o video; o S3 tem watchdog proprio
                if self.ctl.reg:
                    self.ctl.reg.escrever("erro_controle", erro=repr(e))
                time.sleep(0.2)
            time.sleep(PERIODO_CONTROLE_S)

    # API usada pelo sistema_vigia (thread-safe)
    def geracao(self):
        return self.ctl.geracao_atual()

    def pedir_disparo_ia(self, contexto):
        self.ctl.pedir_disparo_ia(contexto)

    def tecla_disparo(self):
        self.ctl.tecla_disparo()

    def texto(self):
        return self.ctl.texto()

    def parar(self, timeout=1.0):
        """Libera HID e threads. Nao depende de comando final ao S3: o lease
        expira sozinho no firmware."""
        self.rodando = False
        if self._thread:
            self._thread.join(timeout)
        self.hid.parar(timeout)
