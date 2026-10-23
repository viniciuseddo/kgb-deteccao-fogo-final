"""Controlador do caminho novo: liga politica de entrada, sessao protegida,
despachante, confirmacao automatica e registro (specs arbitration/guarded-pump).

Sem threads proprias aqui: passo(agora) e chamado por uma unica thread de
controle (ver executor.py). self.lock protege SO a politica de entrada
(compartilhada com a thread HID) e nunca e mantido durante HTTP. A thread do
YOLO so chama os metodos marcados "thread-safe", que nao esperam HTTP.
"""

import threading
from collections import deque

from .despachante import Despachante, Intencao

VALIDADE_DISPARO_S = 0.5
PERIODO_SESSAO_S = 1.0
PERIODO_RECONCILIAR_S = 0.25
IDADE_MAX_PEDIDO_S = 1.0   # pedido/evidencia mais velha que isso nao vira agua
MAX_EXTERNOS = 8


class Controlador:
    def __init__(self, cliente, politica, relogio, registro=None, ao_fronteira_camera=None,
                 ao_resultado_ia=None):
        self.c = cliente
        self.p = politica
        self.relogio = relogio
        self.reg = registro
        self.ao_fronteira_camera = ao_fronteira_camera or (lambda motivo: None)
        self.ao_resultado_ia = ao_resultado_ia or (lambda contexto, resultado, motivo: None)
        self.lock = threading.RLock()       # protege SO a politica (thread HID); nunca durante HTTP
        self.d = Despachante(cliente, relogio, validade=self._validade)
        self.geracao = 1
        self.estado_texto = "iniciando"
        self.incerto = {}                   # id -> (origem, contexto, desde)
        self._fase_anterior = "OCIOSA"
        self._epoch_anterior = None
        self._prox_sessao = 0.0
        self._prox_reconciliar = 0.0
        self._externos = deque()            # (tipo, contexto, t_pedido) da thread do YOLO
        self.aviso = ""

    # =========================================================== thread-safe
    def geracao_atual(self):
        return self.geracao

    def pedir_disparo_ia(self, contexto):
        """contexto: dict com geracao (da inferencia), confianca, publicado_em...
        Devolve imediatamente; o resultado chega por ao_resultado_ia."""
        self._externo_entrar("ia", dict(contexto))

    def tecla_disparo(self):
        self._externo_entrar("teclado", {"geracao": self.geracao})

    def _externo_entrar(self, tipo, ctx):
        # deque.append/popleft sao atomicos; excesso e descartado na hora, com motivo.
        if len(self._externos) >= MAX_EXTERNOS:
            self._descartar_externo(tipo, ctx, "fila_cheia")
            return
        self._externos.append((tipo, ctx, self.relogio()))

    def _descartar_externo(self, tipo, ctx, motivo):
        if tipo == "ia":
            self.ao_resultado_ia(ctx, "descartado", motivo)
        else:
            self._log("entrada", botao="tecla_f", resultado="descartado", motivo=motivo)

    def _descartar_externos(self, motivo):
        while self._externos:
            tipo, ctx, _ = self._externos.popleft()
            self._descartar_externo(tipo, ctx, motivo)

    def texto(self):
        return self.estado_texto

    # =========================================================== registro
    def _log(self, evento, **kw):
        if self.reg:
            self.reg.escrever(evento, **kw)

    # =========================================================== validade
    def _validade(self, i, agora):
        if i.geracao and i.geracao != self.geracao:
            return "geracao_antiga"
        if i.acao == "mover" and (i.input_epoch != self.p.input_epoch or not self._pode_mover(agora)):
            return "entrada_invalida"
        if i.input_epoch is not None and i.acao in ("manual", "auto", "disparar") \
                and i.input_epoch != self.p.input_epoch:
            return "entrada_invalida"
        if i.acao == "disparar":
            e = self.c.estado
            if e.fase != "OCIOSA":
                return "ocupado_local"
            if e.cooldown_restante(agora) > 0:
                return "cooldown_local"
            if i.contexto.get("origem") in ("operador", "teclado") and e.modo != "MANUAL":
                return "modo_auto_local"
            if self.incerto:
                return "resultado_incerto_pendente"
        return None

    def _pode_mover(self, agora):
        with self.lock:
            s = self.p.instantaneo(agora)
        return (self.c.estado.modo == "MANUAL" and self.c.estado.fase == "OCIOSA" and s.saudavel(agora)
                and not self.p.exige_nova_selecao_manual and self._sessao_normal())

    def _sessao_normal(self):
        return self.c.sessao is not None and self.c.sessao.estado_sessao == "NORMAL"

    # =========================================================== resultados
    def _resultado(self, i, r, corpo, motivo_local):
        origem = i.contexto.get("origem", i.acao)
        cid = corpo.get("id") if corpo else None
        if r is None:
            res, mot = "descartado", motivo_local
        elif r.desconhecido:
            res, mot = "desconhecido", r.erro
            if i.acao in ("disparar", "cancelar") and cid:
                self.incerto[cid] = (i.acao, i.contexto, self.relogio())
        else:
            res, mot = ("aceito" if r.aceito else "recusado"), r.motivo
        self._log("comando", acao=i.acao, origem=origem, id=cid, seq=(corpo or {}).get("seq"),
                  resultado=res, motivo=mot, estado=self._estado_resumo())
        if i.acao == "manual" and res == "aceito":
            with self.lock:
                if i.input_epoch is None or i.input_epoch == self.p.input_epoch:
                    self.p.confirmar_selecao_manual()
        if i.acao == "cancelar":
            self.aviso = "" if res == "aceito" else f"cancelamento nao confirmado ({mot})"
        if i.acao == "disparar" and origem == "ia":
            self.ao_resultado_ia(i.contexto, res, mot)

    def _estado_resumo(self):
        e = self.c.estado
        return {"modo": e.modo, "fase": e.fase, "epoch": e.control_epoch, "sessao": e.estado_sessao,
                "cooldown_ms": e.cooldown_restante_ms}

    # =========================================================== fronteiras
    def nova_geracao(self, motivo, agora, drenar_hid, exige_selecao):
        self.geracao += 1
        self.d.limpar(motivo)
        self.ao_fronteira_camera(motivo)
        if drenar_hid:
            with self.lock:
                self.p.nova_fronteira(motivo, agora, exige_selecao=exige_selecao)
        self._log("fronteira", motivo=motivo, geracao=self.geracao)

    def _observar_estado(self, agora):
        e = self.c.estado
        if self._epoch_anterior is not None and e.control_epoch != self._epoch_anterior:
            if self._fase_anterior == "OCIOSA" and e.fase != "OCIOSA":
                # entrada no combate: movimento e intencoes manuais pendentes caem
                self.d.limpar("inicio_combate")
            elif e.fase == "OCIOSA":
                # saida do combate (natural ou cancelada): nova fronteira de leitura
                self.nova_geracao("fim_combate", agora, drenar_hid=True, exige_selecao=False)
        self._epoch_anterior = e.control_epoch
        self._fase_anterior = e.fase

    # =========================================================== passo
    def passo(self, agora):
        self._passo(agora)

    def _passo(self, agora):
        # 1) sessao
        if self.c.incompatibilidade:
            self.estado_texto = f"controle desabilitado: {self.c.incompatibilidade}"
            self._descartar_externos(f"controle_incompativel:{self.c.incompatibilidade}")
            return
        if self.c.sessao is None:
            if agora >= self._prox_sessao:
                self._prox_sessao = agora + PERIODO_SESSAO_S
                r = self.c.abrir_sessao()
                motivo = self.c.incompatibilidade or (r.motivo if r and r.json else (r.erro if r else ""))
                if self.c.sessao is None:
                    self.estado_texto = f"sem sessao protegida ({motivo or 'sem resposta'})"
                    self._log("sessao", resultado="falhou", motivo=motivo)
                    self._descartar_externos("sem_sessao")
                    return
                self._log("sessao", resultado="aberta", estado_sessao=self.c.sessao.estado_sessao,
                          acao_recuperar=self.c.sessao.acao_recuperar)
                with self.lock:
                    self.p.nova_fronteira("sessao_nova", agora, exige_selecao=True)
                self._epoch_anterior = None
                self._descartar_externos("sessao_nova")
            else:
                self._descartar_externos("sem_sessao")
                return

        # 2) eventos de entrada (bordas ja priorizadas pela politica)
        with self.lock:
            eventos = self.p.retirar_eventos(agora)
        for ev in eventos:
            self._evento(ev, agora)

        # 3) pedidos externos (IA, teclado)
        while self._externos:
            tipo, ctx, t_pedido = self._externos.popleft()
            self._externo(tipo, ctx, agora, t_pedido)

        # 4) lease e movimento so com HID fresco
        with self.lock:
            s = self.p.instantaneo(agora)
            exige = self.p.exige_nova_selecao_manual
        manual = self.c.estado.modo == "MANUAL"
        self.d.renovar_ativo = manual and s.saudavel(agora) and self._sessao_normal() and not exige
        if self._pode_mover(agora):
            self.d.definir_movimento(s.pan_vel, self.geracao, s.input_epoch)
        else:
            self.d.parar_movimento()

        # 5) reconciliar resultados incertos sem repetir atuacao
        if self.incerto and agora >= self._prox_reconciliar:
            self._prox_reconciliar = agora + PERIODO_RECONCILIAR_S
            for cid in list(self.incerto)[:1]:
                ref = self.c.reconciliar(cid)
                if ref in ("aceito", "recusado"):
                    acao, ctx, _ = self.incerto.pop(cid)
                    self._log("reconciliado", id=cid, acao=acao, resultado=ref)
                    if acao == "disparar" and ctx.get("origem") == "ia":
                        self.ao_resultado_ia(ctx, ref, "reconciliado")
                elif ref == "desconhecido":
                    acao, ctx, _ = self.incerto.pop(cid)
                    self._log("reconciliado", id=cid, acao=acao, resultado="desconhecido_definitivo")

        # 6) uma requisicao
        self.d.passo(agora)
        self._observar_estado(agora)
        self._atualizar_texto(agora)

    def _evento(self, ev, agora):
        e = self.c.estado
        if ev.tipo == "descontinuidade":
            self._log("entrada", botao="descontinuidade", motivo=ev.motivo)
            return
        if ev.tipo == "circulo":
            self._cancelar(agora)
            return
        if e.fase != "OCIOSA":
            self._log("entrada", botao=ev.tipo, resultado="descartado", motivo="combate")
            return
        if not self._sessao_normal():
            self._log("entrada", botao=ev.tipo, resultado="descartado", motivo="recuperacao")
            return
        if ev.tipo == "cruz":
            self.d.pedir(Intencao("manual", valido_ate=agora + VALIDADE_DISPARO_S, geracao=self.geracao,
                                  input_epoch=ev.input_epoch, ao_resultado=self._resultado,
                                  contexto={"origem": "operador"}))
        elif ev.tipo == "triangulo":
            self.d.pedir(Intencao("auto", valido_ate=agora + VALIDADE_DISPARO_S, geracao=self.geracao,
                                  input_epoch=ev.input_epoch, ao_resultado=self._resultado,
                                  contexto={"origem": "operador"}))
        elif ev.tipo == "quadrado":
            if e.modo != "MANUAL" or self.p.exige_nova_selecao_manual:
                self._log("entrada", botao="quadrado", resultado="recusado_local", motivo="modo_auto")
                return
            self._disparo("operador", {"geracao": self.geracao}, agora, input_epoch=ev.input_epoch)

    def _externo(self, tipo, ctx, agora, t_pedido):
        if agora - t_pedido > IDADE_MAX_PEDIDO_S:
            self._descartar_externo(tipo, ctx, "pedido_antigo")
            return
        if tipo == "ia":
            if ctx.get("geracao") != self.geracao:
                self.ao_resultado_ia(ctx, "descartado", "geracao_antiga")
                return
            pub = ctx.get("publicado_em")
            if pub is not None and agora - pub > IDADE_MAX_PEDIDO_S:
                self.ao_resultado_ia(ctx, "descartado", "evidencia_antiga")
                return
            self._disparo("ia", ctx, agora)
        elif tipo == "teclado":
            if self.c.estado.modo != "MANUAL":
                self._log("entrada", botao="tecla_f", resultado="recusado_local", motivo="modo_auto")
                return
            self._disparo("teclado", ctx, agora)

    def _disparo(self, origem, ctx, agora, input_epoch=None):
        ctx = dict(ctx, origem=origem)
        i = Intencao("disparar", {"origem": origem}, valido_ate=agora + VALIDADE_DISPARO_S,
                     geracao=ctx.get("geracao", self.geracao), input_epoch=input_epoch,
                     ao_resultado=self._resultado, contexto=ctx)
        m = self._validade(i, agora)
        if m:
            self._resultado(i, None, None, m)
            return
        self.d.pedir(i)

    def _cancelar(self, agora):
        # Barreira local primeiro: geracao nova invalida inferencias e filas anteriores.
        self.geracao += 1
        self.ao_fronteira_camera("cancelamento")
        sess = self.c.sessao
        if sess and sess.estado_sessao == "RECUPERACAO" and sess.acao_recuperar:
            campos = {"alvo": sess.acao_recuperar}
        else:
            campos = {"cancel_ate": self.c.ultimo_seq()}
        i = Intencao("cancelar", campos, valido_ate=agora + VALIDADE_DISPARO_S, geracao=0,
                     ao_resultado=self._resultado, contexto={"origem": "operador"})
        self.d.pedir_cancelamento(i)
        self._log("entrada", botao="circulo", geracao=self.geracao)

    def _atualizar_texto(self, agora):
        e = self.c.estado
        with self.lock:
            s = self.p.instantaneo(agora)
        partes = [e.modo]
        if e.fase != "OCIOSA":
            partes.append("AGUA " + e.fase)
        if self.c.sessao and self.c.sessao.estado_sessao == "RECUPERACAO":
            partes.append("RECUPERACAO")
        if not s.saudavel(agora):
            partes.append("controle " + s.estado.lower())
        elif self.p.exige_nova_selecao_manual:
            partes.append("aperte X para manual")
        cd = e.cooldown_restante(agora)
        if cd > 0:
            partes.append(f"cooldown {cd:.0f}s")
        if self.incerto:
            partes.append("resultado incerto")
        if self.aviso:
            partes.append(self.aviso)
        self.estado_texto = " | ".join(partes)
