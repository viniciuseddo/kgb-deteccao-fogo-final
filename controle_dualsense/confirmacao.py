"""Confirmacao automatica por publicacoes locais (spec arbitration:
'Confirmação por publicações locais sem prometer idade de captura').

Conta N frame_id_local DISTINTOS, do camera_epoch corrente e da geracao
causal corrente, com idade desde a publicacao local <= limite. Nao afirma
nada sobre a idade real da cena no sensor.
"""

FRAMES_PADRAO = 3
IDADE_MAX_S = 1.0


class ConfirmacaoAutomatica:
    def __init__(self, n=FRAMES_PADRAO, idade_max_s=IDADE_MAX_S):
        self.n = n
        self.idade_max = idade_max_s
        self.invalidar()

    def invalidar(self):
        self._ids = []
        self._epoch = None
        self._geracao = None

    @property
    def contagem(self):
        return len(self._ids)

    def registrar(self, pub, achou, geracao_inferencia, geracao_atual, agora):
        """pub: Publicacao inferida; geracao_inferencia: geracao no INICIO da inferencia.
        Retorna True quando a confirmacao esta completa (e zera para a proxima)."""
        if pub is None or geracao_inferencia != geracao_atual:
            return False  # resultado de antes da barreira nao conta nem zera
        if (agora - pub.published_at_monotonic) > self.idade_max:
            self.invalidar()
            return False
        if self._epoch != pub.camera_epoch or self._geracao != geracao_atual:
            self.invalidar()
            self._epoch = pub.camera_epoch
            self._geracao = geracao_atual
        if not achou:
            self._ids = []
            return False
        if pub.frame_id_local in self._ids:
            return False  # mesmo quadro inferido de novo nao conta
        self._ids.append(pub.frame_id_local)
        if len(self._ids) >= self.n:
            self._ids = []
            return True
        return False
