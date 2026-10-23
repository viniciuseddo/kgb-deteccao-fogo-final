"""Adaptador HID USB somente de ENTRADA (hidapi). Nao envia output/feature
reports, vibracao, LED ou atualizacao de firmware ao DualSense.

O modulo `hid` so e importado quando o adaptador e criado (recurso habilitado).
"""

import threading
import time

from . import entrada
from . import relatorio as rel

TIMEOUT_LEITURA_MS = 10
ESPERA_RECONEXAO_S = 0.5
ESPERA_DRENAR_DE_NOVO_S = 0.05


class _ComLock:
    """Expoe a politica para entrada.drenar tomando o lock so na fronteira."""

    def __init__(self, politica, lock):
        self._p = politica
        self._lock = lock
        self.descartados = 0

    def fronteira_vazia(self, t):
        with self._lock:
            self._p.descartados += self.descartados
            self._p.fronteira_vazia(t)


class Dispositivo:
    """Envolve hid.device expondo apenas leitura e fechamento.

    Como no diagnostico medido (hidapi 0.15.0): handle em modo nao bloqueante
    (configuracao local do handle, nada e enviado ao controle), leitura com
    timeout por hid_read_timeout e buffer de 128 bytes para que relatorios de
    outro comprimento sejam detectados e recusados pelo parser.
    """

    BUF = 128

    def __init__(self, dev):
        self._dev = dev
        dev.set_nonblocking(1)

    def ler(self, timeout_ms):
        d = self._dev.read(self.BUF, timeout_ms)
        return bytes(d) if d else None

    def ler_sem_espera(self):
        d = self._dev.read(self.BUF)
        return bytes(d) if d else None

    def fechar(self):
        try:
            self._dev.close()
        except Exception:
            pass


class AdaptadorHID:
    def __init__(self, politica, lock, modulo_hid=None, relogio=time.monotonic, ao_log=None):
        if modulo_hid is None:
            import hid as modulo_hid  # dependencia opcional: requirements-dualsense.txt
        self.hid = modulo_hid
        self.p = politica
        self.lock = lock
        self.relogio = relogio
        self.log = ao_log or (lambda *a, **k: None)
        self.dev = None
        self.motivo = "nao_iniciado"
        self.rodando = False
        self.thread = None

    # ------------------------------------------------------------ ciclo
    def abrir(self):
        sel = rel.selecionar(self.hid.enumerate(rel.VID, rel.PID))
        if sel.motivo:
            self.motivo = sel.motivo
            return False
        d = self.hid.device()
        d.open_path(sel.path)
        self.dev = Dispositivo(d)
        self.motivo = None
        self.log("hid", estado="aberto", interface=sel.interface)
        return True

    def fechar(self):
        if self.dev:
            self.dev.fechar()
        self.dev = None

    def _perda(self, motivo):
        self.fechar()
        self.motivo = motivo
        with self.lock:
            self.p.perda(motivo, self.relogio())
        self.log("hid", estado="perda", motivo=motivo)

    def iteracao(self):
        """Uma volta do laco de aquisicao (exposta para testes)."""
        if self.dev is None:
            try:
                if not self.abrir():
                    time.sleep(ESPERA_RECONEXAO_S)
                    return
            except Exception as e:
                self._perda(f"abrir:{type(e).__name__}")
                time.sleep(ESPERA_RECONEXAO_S)
                return
            with self.lock:
                self.p.perda("reconexao", self.relogio())
        with self.lock:
            self.p.iteracao(self.relogio())
            drenar = self.p.precisa_drenar
        if drenar:
            # Le e descarta SEM segurar o lock (o controle segue atendendo
            # cancelamento); so a declaracao da fronteira e feita sob lock.
            try:
                ok = entrada.drenar(self.dev, _ComLock(self.p, self.lock), self.relogio)
            except Exception as e:
                self._perda(f"drenagem:{type(e).__name__}")
                return
            if not ok:
                time.sleep(ESPERA_DRENAR_DE_NOVO_S)
            return
        try:
            d = self.dev.ler(TIMEOUT_LEITURA_MS)
        except Exception as e:
            self._perda(f"leitura:{type(e).__name__}")
            return
        if d:
            with self.lock:
                self.p.relatorio(d, self.relogio())

    def iniciar(self):
        self.rodando = True
        self.thread = threading.Thread(target=self._laco, daemon=True, name="dualsense-hid")
        self.thread.start()

    def _laco(self):
        while self.rodando:
            self.iteracao()
        self.fechar()

    def parar(self, timeout=1.0):
        self.rodando = False
        if self.thread:
            self.thread.join(timeout)
        self.fechar()
