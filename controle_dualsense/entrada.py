"""Politica de entrada pura: rearme, bordas, prioridade, descontinuidade e
backlog HID (spec dualsense-input; design R2 §2).

Sem threads, sem I/O e com relogio injetado (segundos monotonicos). O
adaptador chama iteracao(t) a cada volta do laco de aquisicao e
relatorio(dados, t) para cada relatorio lido.
"""

from collections import deque
from dataclasses import dataclass

from . import relatorio as rel

LACUNA_S = 0.100           # pausa entre iteracoes que invalida o epoch
NEUTRO_PARA_ARMAR_S = 0.300
FRESCOR_S = 0.500          # HID mais antigo que isso nao sustenta lease
VALIDADE_EVENTO_S = 0.500
CAPACIDADE_EVENTOS = 8
DRENAR_MAX_RELATORIOS = 4096
DRENAR_MAX_S = 0.100

PRIORIDADE = ("circulo", "triangulo", "cruz", "quadrado")


@dataclass(frozen=True)
class Evento:
    tipo: str          # circulo | triangulo | cruz | quadrado | descontinuidade
    input_epoch: int
    t: float
    valido_ate: float
    motivo: str = ""


@dataclass(frozen=True)
class Instantaneo:
    seq: int
    input_epoch: int
    t_relatorio: object   # leitura do ultimo relatorio valido (None se nenhum)
    t_iteracao: object
    pan_vel: float
    armada: bool
    estado: str

    def saudavel(self, agora):
        """Entrada armada, laco vivo e relatorio recente. Nao prova a hora
        fisica da acao do operador."""
        if not self.armada or self.t_relatorio is None or self.t_iteracao is None:
            return False
        return (agora - self.t_relatorio) <= FRESCOR_S and (agora - self.t_iteracao) <= LACUNA_S


class PoliticaEntrada:
    def __init__(self, zona_morta=rel.ZONA_MORTA_PADRAO, lacuna_s=LACUNA_S, neutro_s=NEUTRO_PARA_ARMAR_S,
                 validade_evento_s=VALIDADE_EVENTO_S, capacidade_eventos=CAPACIDADE_EVENTOS):
        self.zona = zona_morta
        self.lacuna_s = lacuna_s
        self.neutro_s = neutro_s
        self.validade = validade_evento_s
        self.capacidade = max(2, capacidade_eventos)
        self.input_epoch = 1
        self.estado = "ARMANDO"
        self.precisa_drenar = False
        self.exige_nova_selecao_manual = False
        self.seq = 0
        self.descartados = 0
        self.invalidos = 0
        self._t_iter = None
        self._t_valido = None
        self._neutro_desde = None
        self._anteriores = (False, False, False, False)  # circulo, triangulo, cruz, quadrado
        self._pan = 0.0
        self._eventos = deque()

    # ----------------------------------------------------------- estado
    @property
    def armada(self):
        return self.estado == "ARMADA"

    def instantaneo(self, agora=None):
        return Instantaneo(self.seq, self.input_epoch, self._t_valido, self._t_iter,
                           self._pan if self.armada else 0.0, self.armada, self.estado)

    # ----------------------------------------------------------- invalidacao
    def _invalidar(self, motivo, t, exige_selecao):
        self.input_epoch += 1
        self.estado = "RESSINCRONIZACAO"
        self.precisa_drenar = True
        if exige_selecao:
            self.exige_nova_selecao_manual = True
        self._pan = 0.0
        self._neutro_desde = None
        # Intencoes inseguras sao descartadas; cancelamentos ja validos ficam.
        self._eventos = deque(e for e in self._eventos if e.tipo == "circulo")
        self._eventos.append(Evento("descontinuidade", self.input_epoch, t, t + self.validade, motivo))

    def perda(self, motivo, t):
        """Erro de leitura, remocao, reconexao ou sessao perdida."""
        self._invalidar(motivo, t, exige_selecao=True)

    def nova_fronteira(self, motivo, t, exige_selecao):
        """Fronteira imposta pelo controlador (ex.: fim de combate)."""
        self._invalidar(motivo, t, exige_selecao)

    def fronteira_vazia(self, t):
        """O adaptador observou a fila do driver vazia apos drenar."""
        if self.estado != "RESSINCRONIZACAO":
            return
        self.estado = "ARMANDO"
        self.precisa_drenar = False
        self._t_iter = t
        self._t_valido = None
        self._neutro_desde = None
        self._anteriores = (False, False, False, False)

    def confirmar_selecao_manual(self):
        self.exige_nova_selecao_manual = False

    # ----------------------------------------------------------- aquisicao
    def iteracao(self, t):
        if self._t_iter is not None and (t - self._t_iter) > self.lacuna_s and self.estado != "RESSINCRONIZACAO":
            self._invalidar("lacuna", t, exige_selecao=True)
        self._t_iter = t

    def relatorio(self, dados, t):
        if self.estado == "RESSINCRONIZACAO":
            self.descartados += 1
            return
        r = rel.interpretar(dados)
        if r is None:
            self.invalidos += 1
            return
        self.seq += 1
        self._t_valido = t
        atuais = (r.circulo, r.triangulo, r.cruz, r.quadrado)
        pan = rel.velocidade_pan(r, self.zona)

        if self.estado == "ARMANDO":
            if pan == 0.0 and not r.algum_botao:
                if self._neutro_desde is None:
                    self._neutro_desde = t
                if t - self._neutro_desde >= self.neutro_s - 1e-9:
                    self.estado = "ARMADA"
            else:
                self._neutro_desde = None
            self._anteriores = atuais
            self._pan = 0.0
            return

        # ARMADA: bordas deste relatorio antes do movimento (latest-wins).
        novas = [a and not b for a, b in zip(atuais, self._anteriores)]
        self._anteriores = atuais
        for i, tipo in enumerate(PRIORIDADE):
            if novas[i]:
                self._enfileirar(Evento(tipo, self.input_epoch, t, t + self.validade), t)
                break  # bordas simultaneas de menor prioridade sao descartadas
        if self.armada:
            self._pan = pan

    def _enfileirar(self, ev, t):
        if ev.tipo == "circulo":
            # Reserva: sempre cabe; coalesce com cancelamento ja pendente.
            self._eventos = deque(e for e in self._eventos if e.tipo != "circulo")
            self._eventos.append(ev)
            return
        nao_cancel = sum(1 for e in self._eventos if e.tipo not in ("circulo", "descontinuidade"))
        if nao_cancel >= self.capacidade - 1:
            self._invalidar("overflow_eventos", t, exige_selecao=True)
            return
        self._eventos.append(ev)

    def retirar_eventos(self, agora):
        """Eventos ainda validos; os do epoch atual, cancelamentos e avisos."""
        saida = []
        while self._eventos:
            e = self._eventos.popleft()
            if e.valido_ate < agora:
                continue
            if e.tipo in ("circulo", "descontinuidade") or e.input_epoch == self.input_epoch:
                saida.append(e)
        return saida


def drenar(dispositivo, politica, relogio, max_relatorios=DRENAR_MAX_RELATORIOS, max_s=DRENAR_MAX_S):
    """Le sem esperar e descarta ate a fila ficar vazia, com limites.

    Retorna True se observou fila vazia (e declara a fronteira). False se o
    limite foi atingido: a entrada continua desarmada e o chamador tenta de
    novo mais tarde, sem laco ocupado.
    """
    inicio = relogio()
    lidos = 0
    while True:
        if lidos >= max_relatorios or (relogio() - inicio) >= max_s:
            return False
        d = dispositivo.ler_sem_espera()
        if not d:
            politica.fronteira_vazia(relogio())
            return True
        lidos += 1
        politica.descartados += 1
