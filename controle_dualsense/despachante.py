"""Despachante unico de HTTP do caminho novo (design R2 §5).

passo(agora) faz NO MAXIMO uma requisicao. Quem chama passo() em uma unica
thread garante "no maximo uma em voo". Prioridade: cancelamento > acoes
discretas > renovacao de lease > movimento (latest-wins, <= 20 Hz) >
renovacao de janelas. Intencoes sem validade sao descartadas, nunca adiadas.
Nao ha retry automatico: resultado desconhecido volta ao chamador.
"""

from collections import deque
from dataclasses import dataclass, field

HZ_MOVIMENTO = 20.0
PERIODO_RENOVAR_S = 0.250
PERIODO_JANELA_S = 0.250
KEEPALIVE_MOV_S = 0.200
CAPACIDADE = 4


@dataclass
class Intencao:
    acao: str
    campos: dict = field(default_factory=dict)
    valido_ate: float = 0.0
    geracao: int = 0
    input_epoch: object = None
    ao_resultado: object = None   # fn(intencao, resposta, corpo, motivo_local)
    contexto: dict = field(default_factory=dict)


class Despachante:
    def __init__(self, cliente, relogio, validade=None, capacidade=CAPACIDADE):
        self.c = cliente
        self.relogio = relogio
        self.validade = validade or (lambda i, agora: None)  # -> motivo de descarte ou None
        self.capacidade = capacidade
        self.fila = deque()
        self.cancelamento = None
        self.renovar_ativo = False
        self._ult_renovar = -1e9
        self._ult_janela = -1e9
        self._mov = None          # (vel, geracao, input_epoch)
        self._mov_enviado = 0.0
        self._ult_mov = -1e9
        self.enviados = []        # (agora, acao) para testes/telemetria; limitado
        self.descartes = deque(maxlen=64)

    # ----------------------------------------------------------- entrada
    def definir_movimento(self, vel, geracao, input_epoch):
        self._mov = (float(vel), geracao, input_epoch)

    def parar_movimento(self):
        self._mov = None

    def pedir(self, intencao):
        if len(self.fila) >= self.capacidade:
            self._descartar(intencao, "fila_cheia")
            return False
        self.fila.append(intencao)
        return True

    def pedir_cancelamento(self, intencao):
        if self.cancelamento is not None:
            self._descartar(self.cancelamento, "substituido")
        self.cancelamento = intencao
        # Pedidos anteriores ao cancelamento perdem a validade agora.
        self.limpar("cancelamento")

    def limpar(self, motivo):
        while self.fila:
            self._descartar(self.fila.popleft(), motivo)
        self._mov = None

    def _descartar(self, i, motivo):
        self.descartes.append((motivo, i.acao))
        if i.ao_resultado:
            i.ao_resultado(i, None, None, motivo)

    # ----------------------------------------------------------- saida
    def _enviar(self, acao, campos, agora):
        corpo, motivo = self.c.montar(acao, **dict(campos))
        if corpo is None:
            return None, None, motivo
        r = self.c.enviar(corpo)
        if len(self.enviados) < 100000:
            self.enviados.append((agora, acao))
        self._ult_janela = agora
        return r, corpo, None

    def _valida(self, i, agora):
        if i.valido_ate and agora > i.valido_ate:
            return "expirada"
        return self.validade(i, agora)

    def passo(self, agora):
        """Executa no maximo uma requisicao. Retorna a acao enviada ou None."""
        if self.c.sessao is None:
            return None

        if self.cancelamento is not None:
            i, self.cancelamento = self.cancelamento, None
            m = self._valida(i, agora)
            if m:
                self._descartar(i, m)
            else:
                r, corpo, m = self._enviar(i.acao, i.campos, agora)
                # Cancelamento que NAO chegou a atuar no S3 (sem janela local ou
                # janela expirada no recebimento) e tentado de novo ate a validade.
                # Nao e replay: o S3 provou que nao o executou.
                sem_janela = m == "sem_janela"
                expirada = r is not None and not r.desconhecido and r.motivo == "janela_expirada"
                if (sem_janela or expirada) and not (i.valido_ate and agora > i.valido_ate):
                    self.cancelamento = i
                    if sem_janela:
                        self._enviar("janela", {}, agora)
                        return "janela"
                    return i.acao
                if i.ao_resultado:
                    i.ao_resultado(i, r, corpo, m)
                return i.acao

        while self.fila:
            i = self.fila.popleft()
            m = self._valida(i, agora)
            if m:
                self._descartar(i, m)
                continue
            r, corpo, m = self._enviar(i.acao, i.campos, agora)
            if i.ao_resultado:
                i.ao_resultado(i, r, corpo, m)
            return i.acao

        if self.renovar_ativo and agora - self._ult_renovar >= PERIODO_RENOVAR_S:
            self._ult_renovar = agora
            self._enviar("renovar", {}, agora)
            return "renovar"

        if self._mov is not None and agora - self._ult_mov >= 1.0 / HZ_MOVIMENTO:
            vel, ger, ep = self._mov
            mudou = abs(vel - self._mov_enviado) > 1e-3
            manter = vel != 0.0 and agora - self._ult_mov >= KEEPALIVE_MOV_S
            if mudou or manter:
                i = Intencao("mover", {"vel": round(vel, 3)}, geracao=ger, input_epoch=ep)
                m = self.validade(i, agora)
                if m:
                    self._mov = None
                    self.descartes.append((m, "mover"))
                else:
                    self._ult_mov = agora
                    r, _, m = self._enviar("mover", i.campos, agora)
                    if r is not None and not r.desconhecido and r.aceito:
                        self._mov_enviado = vel
                    return "mover"

        if agora - self._ult_janela >= PERIODO_JANELA_S:
            self._enviar("janela", {}, agora)
            return "janela"
        return None
