"""Publicacao local de quadros da ESP32-CAM com identidade e fronteiras
(design R2 §7). API aditiva usada SOMENTE no caminho novo; o CameraSerial
original de sistema_vigia.py nao foi alterado.

frame_id_local / published_at_monotonic / camera_epoch descrevem a
PUBLICACAO no computador. Nao sao o instante nem a idade de captura no
sensor, que o protocolo serial preservado nao informa.
"""

import threading
import time
from dataclasses import dataclass

MARCADOR = b"\xaa\x55\xaa\x55"
TAM_MIN = 100
TAM_MAX = 120000
PAUSA_LEITURA_S = 0.500
BACKLOG_MAX_BYTES = 256 * 1024


@dataclass(frozen=True)
class Publicacao:
    frame: object
    frame_id_local: int
    published_at_monotonic: float
    camera_epoch: int


class ParserJPEG:
    """Extrai JPEGs do fluxo marcador(4) + tamanho(4, LE) + dados."""

    def __init__(self):
        self.buf = bytearray()

    def limpar(self):
        self.buf.clear()

    def alimentar(self, dados):
        self.buf.extend(dados)
        saida = []
        while True:
            i = self.buf.find(MARCADOR)
            if i == -1:
                if len(self.buf) > 65536:
                    del self.buf[:-4]
                break
            if i > 0:
                del self.buf[:i]
            if len(self.buf) < 8:
                break
            tam = int.from_bytes(self.buf[4:8], "little")
            if tam > TAM_MAX or tam < TAM_MIN:
                del self.buf[:4]
                continue
            if len(self.buf) < 8 + tam:
                break
            saida.append(bytes(self.buf[8:8 + tam]))
            del self.buf[:8 + tam]
        return saida


class PublicadorQuadros:
    """Regras de fronteira, independentes de serial/OpenCV (testaveis).

    - Partida, pausa > 500 ms, erro, backlog acima do orcamento ou barreira
      externa: novo camera_epoch, parser limpo, entrada pendente descartada
      e o primeiro JPEG completo apos a fronteira ignorado.
    - Em cada lote lido, so o JPEG mais recente pode ser publicado.
    """

    def __init__(self, decodificar, relogio=time.monotonic, pausa_s=PAUSA_LEITURA_S,
                 backlog_max=BACKLOG_MAX_BYTES):
        self.decodificar = decodificar
        self.relogio = relogio
        self.pausa_s = pausa_s
        self.backlog_max = backlog_max
        self.parser = ParserJPEG()
        self.lock = threading.Lock()
        self.camera_epoch = 0
        self._prox_id = 1
        self._ultima_leitura = None
        self._ignorar_primeiro = True
        self._fronteira_pedida = "partida"
        self.ultima = None
        self.descartados = 0

    def fronteira(self, motivo):
        """Thread-safe: pedida pela barreira de cancelamento/falha."""
        with self.lock:
            self._fronteira_pedida = motivo
            self.ultima = None

    def _aplicar_fronteira(self, motivo, descartar_entrada):
        self.camera_epoch += 1
        self.parser.limpar()
        self._ignorar_primeiro = True
        self._fronteira_pedida = None
        self.ultima = None
        self.motivo_fronteira = motivo
        if descartar_entrada:
            descartar_entrada()

    def lote(self, dados, pendentes_na_porta=0, descartar_entrada=None):
        """Processa um lote lido. Retorna a Publicacao feita ou None."""
        agora = self.relogio()
        with self.lock:
            pausa = self._ultima_leitura is not None and (agora - self._ultima_leitura) > self.pausa_s
            self._ultima_leitura = agora
            motivo = self._fronteira_pedida
            if motivo is None and pausa:
                motivo = "pausa_leitura"
            if motivo is None and pendentes_na_porta > self.backlog_max:
                motivo = "backlog"
            if motivo is not None:
                # Bytes deste lote e da porta sao anteriores a fronteira: descarta.
                self._aplicar_fronteira(motivo, descartar_entrada)
                self.descartados += 1
                return None
            jpegs = self.parser.alimentar(dados)
            if not jpegs:
                return None
            self.descartados += len(jpegs) - 1
            jpg = jpegs[-1]
            if self._ignorar_primeiro:
                self._ignorar_primeiro = False
                self.descartados += 1
                return None
            ep = self.camera_epoch
        frame = self.decodificar(jpg)
        if frame is None:
            return None
        with self.lock:
            if ep != self.camera_epoch:
                return None  # fronteira chegou durante a decodificacao
            pub = Publicacao(frame, self._prox_id, self.relogio(), ep)
            self._prox_id += 1
            self.ultima = pub
            return pub

    def pegar(self):
        with self.lock:
            return self.ultima


class CameraSerialProtegida:
    """Leitor serial do caminho novo. Mesma porta/baud/rotacao do original."""

    def __init__(self, porta, baud=460800, rotacao=90, serial_mod=None, cv2_mod=None, np_mod=None):
        import cv2 as _cv2
        import numpy as _np
        import serial as _serial
        self.serial = serial_mod or _serial
        self.cv2 = cv2_mod or _cv2
        self.np = np_mod or _np
        self.porta = porta
        self.baud = baud
        self.rotacao = rotacao
        self.ser = None
        self.rodando = True
        self.pub = PublicadorQuadros(self._decodificar)
        self._conectar()
        self.thread = threading.Thread(target=self._loop, daemon=True, name="camera-protegida")
        self.thread.start()

    def _decodificar(self, jpg):
        arr = self.np.frombuffer(jpg, dtype=self.np.uint8)
        f = self.cv2.imdecode(arr, self.cv2.IMREAD_COLOR)
        if f is None:
            return None
        r = self.rotacao
        if r == 90:
            f = self.cv2.rotate(f, self.cv2.ROTATE_90_CLOCKWISE)
        elif r == 180:
            f = self.cv2.rotate(f, self.cv2.ROTATE_180)
        elif r == 270:
            f = self.cv2.rotate(f, self.cv2.ROTATE_90_COUNTERCLOCKWISE)
        return f

    def _conectar(self):
        try:
            if self.ser:
                try:
                    self.ser.close()
                except Exception:
                    pass
            s = self.serial.Serial()
            s.port = self.porta
            s.baudrate = self.baud
            s.timeout = 0.2
            s.open()
            s.dtr = False
            s.rts = False
            self.ser = s
            self.pub.fronteira("reconexao")
            return True
        except Exception:
            self.ser = None
            return False

    def girar(self):
        self.rotacao = (self.rotacao + 90) % 360
        self.pub.fronteira("rotacao")
        return self.rotacao

    def publicacao(self):
        return self.pub.pegar()

    def pegar(self):
        p = self.pub.pegar()
        return None if p is None else p.frame.copy()

    def fronteira(self, motivo):
        self.pub.fronteira(motivo)

    def _loop(self):
        while self.rodando:
            if not self.ser or not self.ser.is_open:
                time.sleep(0.5)
                self._conectar()
                continue
            try:
                esperando = self.ser.in_waiting
                pedaco = self.ser.read(esperando if esperando > 0 else 1024)
                restante = self.ser.in_waiting
                if pedaco:
                    self.pub.lote(pedaco, restante, self.ser.reset_input_buffer)
                else:
                    self.pub.lote(b"", restante, self.ser.reset_input_buffer)
                    time.sleep(0.01)
            except Exception:
                try:
                    self.ser.close()
                except Exception:
                    pass
                self.ser = None
                self.pub.fronteira("erro_serial")
                time.sleep(0.5)

    def fechar(self):
        self.rodando = False
        try:
            if self.ser:
                self.ser.close()
        except Exception:
            pass
