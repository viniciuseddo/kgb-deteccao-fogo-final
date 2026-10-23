"""Lado cliente do protocolo protegido (vetores em testes/contratos/).

Sem I/O: monta corpos, interpreta respostas e guarda sessao/seq/janelas.
O transporte e injetado.
"""

import json
import re
import uuid
from dataclasses import dataclass, field

V = 1
CAPS_EXIGIDAS = ("pan_manual", "watchdog", "bomba_protegida", "cancelar_sem_modo", "idempotencia")
ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
CORPO_MAX = 512
ACOES_COM_SEQ = frozenset({"manual", "auto", "renovar", "mover", "disparar", "cancelar"})
ORIGENS = frozenset({"ia", "operador", "teclado"})
LIMITES_ESPERADOS = {  # cliente usa politica pelo menos tao restritiva quanto a publicada
    "prazo_agua_ms": 5000, "cooldown_ms": 12000, "lease_ms": 1500, "janela_ms": 500,
}


def novo_id(prefixo="c"):
    return f"{prefixo}{uuid.uuid4().hex[:20]}"


def compacto(obj):
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=True)


def verificar_compatibilidade(status):
    """None se compativel; senao o motivo (sem fallback para letras)."""
    if not isinstance(status, dict):
        return "status_invalido"
    if status.get("v") != V:
        return "versao_incompativel"
    caps = status.get("caps")
    if not isinstance(caps, list) or any(c not in caps for c in CAPS_EXIGIDAS):
        return "capacidades_ausentes"
    if not isinstance(status.get("boot_id"), str) or not isinstance(status.get("janela_abertura"), str):
        return "status_incompleto"
    lim = status.get("limites") or {}
    for k, v in LIMITES_ESPERADOS.items():
        if not isinstance(lim.get(k), int):
            return f"limite_ausente:{k}"
    if lim["prazo_agua_ms"] > LIMITES_ESPERADOS["prazo_agua_ms"] or lim["cooldown_ms"] < LIMITES_ESPERADOS["cooldown_ms"]:
        return "limites_menos_restritivos"
    return None


def validar_corpo_comando(c):
    """Espelho do esquema estrito do S3, para nunca enviar algo que ele recusaria
    por forma. Devolve None ou o motivo."""
    obrig = {"v", "boot_id", "sessao", "acao"}
    acao = c.get("acao")
    permitidos = {
        "consultar": {"ref"}, "janela": set(), "manual": {"seq", "id", "janela"},
        "auto": {"seq", "id", "janela"}, "renovar": {"seq", "id", "janela"},
        "mover": {"seq", "id", "janela", "vel"}, "disparar": {"seq", "id", "janela", "origem"},
        "cancelar": {"seq", "id", "janela", "cancel_ate", "alvo"},
    }
    if acao not in permitidos:
        return "acao_desconhecida"
    extras = set(c) - obrig - permitidos[acao]
    if extras:
        return "campo_desconhecido"
    if not obrig <= set(c):
        return "campo_ausente"
    if acao in ACOES_COM_SEQ:
        if not isinstance(c.get("seq"), int) or isinstance(c.get("seq"), bool) or not 1 <= c["seq"] <= 2**31 - 1:
            return "valor_invalido"
        if not isinstance(c.get("id"), str) or not ID_RE.match(c["id"]):
            return "valor_invalido"
        if not isinstance(c.get("janela"), str):
            return "campo_ausente"
    if acao == "mover":
        v = c.get("vel")
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not -1.0 <= v <= 1.0:
            return "valor_invalido"
    if acao == "disparar" and c.get("origem") not in ORIGENS:
        return "valor_invalido"
    if acao == "cancelar":
        if ("cancel_ate" in c) == ("alvo" in c):
            return "valor_invalido"
        if "cancel_ate" in c and not (isinstance(c["cancel_ate"], int) and 0 <= c["cancel_ate"] < c["seq"]):
            return "valor_invalido"
    if len(compacto(c).encode()) > CORPO_MAX:
        return "corpo_grande"
    return None


@dataclass
class Resposta:
    """Resultado de uma chamada. desconhecido=True: timeout/erro de transporte
    depois do envio; o efeito no S3 NAO e conhecido."""
    http: int = 0
    json: dict = None
    desconhecido: bool = False
    erro: str = ""

    @property
    def aceito(self):
        return bool(self.json) and self.json.get("resultado") == "aceito"

    @property
    def motivo(self):
        return (self.json or {}).get("motivo")


@dataclass
class EstadoS3:
    modo: str = "AUTO"
    fase: str = "OCIOSA"
    control_epoch: int = 0
    estado_sessao: object = None
    cooldown_restante_ms: int = 0
    lease_restante_ms: int = 0
    acao_id: object = None
    perfil: str = "COMPAT"
    pan: object = None
    retorno_auto: bool = False
    visto_em: float = 0.0

    @classmethod
    def de(cls, d, agora):
        e = cls()
        for k in ("modo", "fase", "control_epoch", "estado_sessao", "cooldown_restante_ms",
                  "lease_restante_ms", "acao_id", "perfil", "pan", "retorno_auto"):
            if k in d:
                setattr(e, k, d[k])
        e.visto_em = agora
        return e

    def cooldown_restante(self, agora):
        return max(0.0, self.cooldown_restante_ms / 1000.0 - (agora - self.visto_em))


@dataclass
class Sessao:
    boot_id: str
    sessao: str
    estado_sessao: str
    acao_recuperar: object = None
    seq: int = 0
    janelas: dict = field(default_factory=dict)       # jc / jx / jr -> (token, recebido_em)
    limites: dict = field(default_factory=dict)


class ClienteProtocolo:
    """Monta e interpreta mensagens. Nao repete comandos com ID novo."""

    JANELA_UTIL_S = 0.40  # nao usa janela com mais de 400 ms de idade local (S3: 500 ms)

    def __init__(self, transporte, relogio):
        self.t = transporte
        self.relogio = relogio
        self.sessao = None
        self.estado = EstadoS3()
        self.incompatibilidade = None
        self.status = None
        self._abertura_pendente = None  # (open_id, corpo) para repetir byte a byte

    # ----------------------------------------------------------- status/sessao
    def consultar_status(self):
        r = self.t.enviar("status", None)
        if r.json is not None and not r.desconhecido:
            self.status = r.json
            self.incompatibilidade = verificar_compatibilidade(r.json)
        return r

    def abrir_sessao(self):
        """Abre (ou reconcilia) a sessao. Repete o MESMO session_open_id ate
        saber a decisao; so cria outro quando o S3 prova que nao recebeu."""
        if self._abertura_pendente is None:
            r = self.consultar_status()
            if r.desconhecido or self.incompatibilidade:
                return r
            oid = novo_id("o")
            corpo = compacto({"v": V, "boot_id": self.status["boot_id"], "session_open_id": oid,
                              "janela": self.status["janela_abertura"]})
            self._abertura_pendente = (oid, corpo)
        oid, corpo = self._abertura_pendente
        r = self.t.enviar("sessao", corpo)
        if r.desconhecido:
            return r  # resultado incerto: na proxima tentativa repete o mesmo corpo
        self._abertura_pendente = None
        js = r.json or {}
        if js.get("resultado") == "aceito" and js.get("sessao_vigente", True):
            boot = json.loads(corpo)["boot_id"]
            self.sessao = Sessao(boot, js["sessao"], js.get("estado_sessao"), js.get("acao_recuperar"),
                                 limites=(self.status or {}).get("limites", {}))
            self._guardar_janelas(js)
        if isinstance(js.get("estado"), dict):
            self.estado = EstadoS3.de(js["estado"], self.relogio())
        return r

    # ----------------------------------------------------------- comandos
    def _guardar_janelas(self, js):
        agora = self.relogio()
        for chave, curto in (("janela_c", "jc"), ("janela_x", "jx"), ("janela_r", "jr")):
            if chave in js:
                if js[chave]:
                    self.sessao.janelas[curto] = (js[chave], agora)
                else:
                    self.sessao.janelas.pop(curto, None)

    def janela(self, curto):
        if not self.sessao or curto not in self.sessao.janelas:
            return None
        tok, em = self.sessao.janelas[curto]
        if self.relogio() - em > self.JANELA_UTIL_S:
            return None
        return tok

    def ultimo_seq(self):
        return self.sessao.seq if self.sessao else 0

    def montar(self, acao, **campos):
        """Corpo pronto (dict) ou (None, motivo). Consome seq so se for enviar."""
        if not self.sessao:
            return None, "sem_sessao"
        c = {"v": V, "boot_id": self.sessao.boot_id, "sessao": self.sessao.sessao, "acao": acao}
        if acao in ACOES_COM_SEQ:
            if acao == "cancelar":
                curto = "jr" if "alvo" in campos else "jx"
            else:
                curto = "jc"
            tok = self.janela(curto)
            if tok is None:
                return None, "sem_janela"
            c["seq"] = self.sessao.seq + 1
            c["id"] = campos.pop("id", None) or novo_id()
            c["janela"] = tok
        c.update(campos)
        m = validar_corpo_comando(c)
        if m:
            return None, m
        if acao in ACOES_COM_SEQ:
            self.sessao.seq = c["seq"]
        return c, None

    def enviar(self, corpo):
        r = self.t.enviar("comando", compacto(corpo))
        js = r.json or {}
        if not r.desconhecido and self.sessao:
            if js.get("motivo") in ("sessao_obsoleta", "boot", "sem_sessao"):
                self.sessao = None
            else:
                self._guardar_janelas(js)
                if isinstance(js.get("estado"), dict):
                    self.estado = EstadoS3.de(js["estado"], self.relogio())
                    if self.sessao:
                        self.sessao.estado_sessao = js["estado"].get("estado_sessao") or self.sessao.estado_sessao
        return r

    def reconciliar(self, ref):
        c, m = self.montar("consultar", ref=ref)
        if c is None:
            return None
        r = self.enviar(c)
        if r.desconhecido or not r.json:
            return None
        return r.json.get("ref_resultado")
