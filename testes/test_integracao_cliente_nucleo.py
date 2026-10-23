"""Tarefas 5.x/7.1/7.2: cliente Python real (politica, despachante,
controlador) contra o NUCLEO C++ REAL do firmware, com relogio simulado.

O 'atuador simulado' e o proprio nucleo do sketch compilado para o host
(nucleo_cli). Falhas de transporte (ACK perdido, rede fora) sao injetadas na
ponte. Sem HID, COM, rede ou banco reais.
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import apoio_nucleo  # noqa: E402
from controle_dualsense.controlador import Controlador  # noqa: E402
from controle_dualsense.entrada import PoliticaEntrada  # noqa: E402
from controle_dualsense.protocolo import ClienteProtocolo, Resposta  # noqa: E402

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "dualsense_relatorios.json")
with open(FIX, encoding="utf-8") as f:
    R = {k: bytes.fromhex(v) for k, v in json.load(f)["relatorios"].items()}
NEUTRO, ESQ, QUAD, CIRC, CRUZ, TRI = R["repouso"], R["esquerda"], R["quadrado"], R["circulo"], R["cruz"], R["triangulo"]


class RegistroMem:
    def __init__(self):
        self.linhas = []

    def escrever(self, evento, **kw):
        self.linhas.append(dict(kw, evento=evento))


class Bancada:
    """Um cliente (politica+controlador) ligado ao nucleo real."""

    EXE = None

    def __init__(self, nucleo=None, relogio=None, t_inicial=0.0):
        if Bancada.EXE is None:
            Bancada.EXE = apoio_nucleo.executavel()
        self.relogio = relogio or apoio_nucleo.Relogio(t_inicial)
        self.nucleo = nucleo or apoio_nucleo.Nucleo(Bancada.EXE)
        self.tr = apoio_nucleo.TransporteNucleo(self.nucleo, self.relogio)
        self.novo_cliente()

    def novo_cliente(self):
        self.reg = RegistroMem()
        self.ia = []
        self.camera = []
        self.pol = PoliticaEntrada()
        self.cli = ClienteProtocolo(self.tr, self.relogio)
        self.ctl = Controlador(self.cli, self.pol, self.relogio, registro=self.reg,
                               ao_fronteira_camera=self.camera.append,
                               ao_resultado_ia=lambda ctx, res, mot: self.ia.append((ctx, res, mot)))

    def rodar(self, segundos, relatorio=NEUTRO, hid=True, controle=True):
        """Relatorio a cada 4 ms e passo do controle a cada 5 ms."""
        fim = self.relogio.ms() + int(segundos * 1000)
        while self.relogio.ms() < fim:
            self.relogio.t = (self.relogio.ms() + 1) / 1000.0
            ms = self.relogio.ms()
            if hid and ms % 4 == 0:
                self.pol.iteracao(self.relogio.t)
                self.pol.relatorio(relatorio, self.relogio.t)
            if controle and ms % 5 == 0:
                self.ctl.passo(self.relogio.t)

    def drenar_se_preciso(self):
        if self.pol.precisa_drenar:
            self.pol.fronteira_vazia(self.relogio.t)

    def rodar_hid(self, segundos, relatorio=NEUTRO):
        """Como rodar(), mas drena quando a politica pede (papel do adaptador)."""
        fim = self.relogio.ms() + int(segundos * 1000)
        while self.relogio.ms() < fim:
            self.drenar_se_preciso()
            self.rodar(0.004, relatorio)

    def status(self):
        return self.tr.status()

    def d(self):
        return self.tr.telemetria()

    def acoes_enviadas(self, acao):
        return [x for x in self.tr.log if x[2] == acao]

    def fechar(self):
        self.nucleo.fechar()


class Base(unittest.TestCase):
    def setUp(self):
        self.b = Bancada()

    def tearDown(self):
        self.b.fechar()

    def entrar_manual(self):
        b = self.b
        b.rodar_hid(1.0)                  # sessao + rearme
        self.assertTrue(b.pol.armada, b.pol.estado)
        b.rodar_hid(0.02, CRUZ)
        b.rodar_hid(0.3)
        self.assertEqual(b.status()["modo"], "MANUAL")


class TestFluxoNormal(Base):
    def test_manual_move_e_mantem_alem_de_8s_e_volta_auto(self):
        b = self.b
        self.entrar_manual()
        pan0 = b.status()["pan"]
        b.rodar_hid(1.0, ESQ)
        pan1 = b.status()["pan"]
        self.assertGreater(pan1, pan0 + 20, "esquerda aumenta o angulo PAN")
        self.assertLessEqual(pan1 - pan0, 31 + 1, "<= 30 graus/s")
        b.rodar_hid(9.0)
        st = b.status()
        self.assertEqual(st["modo"], "MANUAL")
        self.assertEqual(st["pan"], pan1, "neutro mantem o enquadramento")
        movs = b.acoes_enviadas("mover")
        b.rodar_hid(0.05, TRI)
        b.rodar_hid(0.3)
        self.assertEqual(b.status()["modo"], "AUTO")
        self.assertTrue(b.status()["vigiando"])
        self.assertLessEqual(len(movs), int(1.2 * 20) + 4, "movimento limitado a ~20 Hz")

    def test_quadrado_no_auto_nao_envia_disparo(self):
        b = self.b
        b.rodar_hid(13.0)
        b.rodar_hid(0.05, QUAD)
        b.rodar_hid(0.5)
        self.assertEqual(b.acoes_enviadas("disparar"), [])
        self.assertFalse(b.d()["rele"])
        self.assertTrue(any(l.get("evento") == "entrada" and l.get("botao") == "quadrado" and l.get("motivo") == "modo_auto" for l in b.reg.linhas))

    def test_quadrado_mantido_um_disparo_e_mover_durante_agua_descartado(self):
        b = self.b
        b.rodar_hid(12.5)
        self.entrar_manual()
        pan0 = b.status()["pan"]
        b.rodar_hid(2.0, QUAD)  # 500 relatorios com Quadrado
        self.assertEqual(len(b.acoes_enviadas("disparar")), 1)
        self.assertTrue(b.d()["rele"])
        b.rodar_hid(1.0, ESQ)   # analogico durante a agua
        self.assertEqual(b.status()["pan"], pan0)
        movs_aceitos = [x for x in b.acoes_enviadas("mover") if x[3] == "aceito" and x[0] > 12500]
        self.assertEqual(movs_aceitos, [], "nenhum movimento aceito durante o combate")
        b.rodar_hid(3.0, ESQ)   # agua termina com analogico ainda deslocado
        st = b.status()
        self.assertEqual(st["fase"], "OCIOSA")
        self.assertEqual(st["modo"], "MANUAL")
        self.assertEqual(st["pan"], pan0, "analogico mantido desde o combate nao move apos o fim")
        b.rodar_hid(0.4)        # novo fluxo neutro >= 300 ms
        b.rodar_hid(0.5, ESQ)
        self.assertGreater(b.status()["pan"], pan0, "novo movimento adquirido apos a fronteira")

    def test_circulo_cancela_sem_trocar_modo_e_inibe(self):
        b = self.b
        b.rodar_hid(12.5)
        self.entrar_manual()
        b.rodar_hid(0.02, QUAD)
        b.rodar_hid(0.5)
        self.assertTrue(b.d()["rele"])
        b.rodar_hid(0.02, CIRC)
        b.rodar_hid(0.05)
        d = b.d()
        self.assertFalse(d["rele"])
        st = b.status()
        self.assertEqual(st["modo"], "MANUAL")
        self.assertEqual(st["ultimo"]["resultado"], "cancelada")
        self.assertGreaterEqual(st["cooldown_restante_ms"], 11800)
        self.assertIn("cancelamento", b.camera, "barreira de camera aplicada")
        b.rodar_hid(0.4)
        b.rodar_hid(0.02, QUAD)
        b.rodar_hid(0.2)
        self.assertEqual(len([x for x in b.acoes_enviadas("disparar") if x[3] == "aceito"]), 1,
                         "Quadrado durante a inibicao nao gera novo disparo aceito")


class TestFalhas(Base):
    def test_pausa_800ms_com_backlog_de_quadrado(self):
        b = self.b
        b.rodar_hid(12.5)
        self.entrar_manual()
        # thread HID parada 800 ms (o controle continua rodando)
        b.rodar(0.8, hid=False)
        # backlog: relatorios antigos de Quadrado lidos de uma vez com t novo
        b.pol.iteracao(b.relogio.t)
        for _ in range(40):
            b.pol.relatorio(QUAD, b.relogio.t)
            b.pol.relatorio(NEUTRO, b.relogio.t)
        b.rodar_hid(0.5)
        self.assertEqual(b.acoes_enviadas("disparar"), [])
        self.assertFalse(b.d()["rele"])
        self.assertTrue(b.pol.exige_nova_selecao_manual)
        b.rodar_hid(1.5)
        self.assertEqual(b.status()["modo"], "AUTO", "sem renovacao, lease expira no S3")
        b.rodar_hid(0.02, QUAD)
        b.rodar_hid(0.2)
        self.assertEqual(b.acoes_enviadas("disparar"), [], "exige Cruz de novo")

    def test_hid_congelado_lease_expira(self):
        b = self.b
        self.entrar_manual()
        b.rodar(2.0, hid=False)
        self.assertEqual(b.status()["modo"], "AUTO")

    def test_ack_perdido_cancelamento_por_barreira_e_reconciliacao(self):
        b = self.b
        b.rodar_hid(12.5)
        self.entrar_manual()
        b.tr.perder_resposta.add("disparar")
        b.rodar_hid(0.02, QUAD)
        b.rodar_hid(0.1)
        self.assertTrue(b.d()["rele"], "o S3 aceitou")
        self.assertEqual(len(b.acoes_enviadas("disparar")), 1, "sem retry com ID novo")
        cmd = [l for l in b.reg.linhas if l.get("evento") == "comando" and l.get("acao") == "disparar"]
        self.assertEqual(cmd[0]["resultado"], "desconhecido", "cliente registrou que nao sabe o resultado")
        b.rodar_hid(0.02, CIRC)
        b.rodar_hid(0.1)
        self.assertFalse(b.d()["rele"], "barreira cancel_ate cortou a acao com ACK perdido")
        b.rodar_hid(0.5)
        self.assertFalse(b.ctl.incerto, "reconciliado por consulta de ID")
        self.assertTrue(any(l.get("evento") == "reconciliado" and l.get("resultado") == "aceito" for l in b.reg.linhas))

    def test_reinicio_do_cliente_durante_agua_recuperacao(self):
        b = self.b
        b.rodar_hid(12.5)
        self.entrar_manual()
        b.tr.perder_resposta.add("disparar")
        b.rodar_hid(0.02, QUAD)
        b.rodar_hid(0.2)
        self.assertTrue(b.d()["rele"])
        b.novo_cliente()            # processo reiniciado: S2
        b.rodar_hid(0.6)
        self.assertEqual(b.cli.sessao.estado_sessao, "RECUPERACAO")
        st = b.status()
        self.assertEqual(st["modo"], "AUTO", "manual de S1 nao e herdado")
        self.assertTrue(st["retorno_auto"])
        self.assertTrue(st["bomba"], "acao e prazo originais preservados")
        b.rodar_hid(0.4)
        b.rodar_hid(0.02, CRUZ)     # manual nao e restaurado
        b.rodar_hid(0.1)
        self.assertNotEqual(b.status()["modo"], "MANUAL")
        b.rodar_hid(0.02, CIRC)
        b.rodar_hid(0.1)
        self.assertFalse(b.d()["rele"])
        st = b.status()
        self.assertEqual(st["estado_sessao"], "NORMAL")
        self.assertEqual(st["modo"], "AUTO")
        self.assertEqual(st["ultimo"]["resultado"], "cancelada")

    def test_desconectar_durante_agua_e_reconectar_segurando_quadrado(self):
        b = self.b
        b.rodar_hid(12.5)
        self.entrar_manual()
        b.rodar_hid(0.02, QUAD)
        b.rodar_hid(0.3)
        t_on = b.d()["rele_ligado_em"]
        b.pol.perda("removido", b.relogio.t)
        b.rodar(2.0, hid=False)     # cabo fora
        st = b.status()
        self.assertTrue(st["bomba"], "agua segue ate o prazo local")
        self.assertTrue(st["retorno_auto"])
        b.rodar(3.0, hid=False)
        d = b.d()
        self.assertEqual(d["rele_desligado_em"] - t_on, 5000)
        self.assertEqual(b.status()["modo"], "AUTO")
        b.drenar_se_preciso()
        b.rodar_hid(2.0, QUAD)      # reconecta segurando Quadrado
        self.assertEqual(len(b.acoes_enviadas("disparar")), 1)

    def test_ia_e_quadrado_simultaneos(self):
        b = self.b
        b.rodar_hid(12.5)
        self.entrar_manual()
        b.ctl.pedir_disparo_ia({"geracao": b.ctl.geracao_atual(), "confianca": 0.9})
        b.pol.iteracao(b.relogio.t)
        b.pol.relatorio(QUAD, b.relogio.t)
        b.rodar_hid(0.3)
        aceitos = [x for x in b.acoes_enviadas("disparar") if x[3] == "aceito"]
        self.assertEqual(len(aceitos), 1)
        self.assertTrue(b.d()["rele"])

    def test_inferencia_iniciada_antes_do_circulo(self):
        b = self.b
        b.rodar_hid(13.0)
        g = b.ctl.geracao_atual()
        b.rodar_hid(0.02, CIRC)     # barreira local
        b.rodar_hid(0.05)
        b.ctl.pedir_disparo_ia({"geracao": g, "confianca": 0.9})  # inferencia terminou depois
        b.rodar_hid(0.2)
        self.assertEqual(b.acoes_enviadas("disparar"), [])
        self.assertEqual(b.ia[-1][1:], ("descartado", "geracao_antiga"))

    def test_ia_durante_cooldown_descartada_antes_do_envio(self):
        b = self.b
        b.rodar_hid(12.5)
        b.ctl.pedir_disparo_ia({"geracao": b.ctl.geracao_atual()})
        b.rodar_hid(6.0)
        n = len(b.acoes_enviadas("disparar"))
        b.ctl.pedir_disparo_ia({"geracao": b.ctl.geracao_atual()})
        b.rodar_hid(0.2)
        self.assertEqual(len(b.acoes_enviadas("disparar")), n)
        self.assertEqual(b.ia[-1][1:], ("descartado", "cooldown_local"))

    def test_rede_fora_sem_fallback_e_sem_retry(self):
        b = self.b
        b.rodar_hid(12.5)
        self.entrar_manual()
        b.tr.offline = True
        n_log = len(b.tr.log)
        b.ctl.pedir_disparo_ia({"geracao": b.ctl.geracao_atual()})
        b.rodar_hid(0.02, CIRC)
        b.rodar_hid(1.0)
        self.assertEqual(len(b.tr.log), n_log, "nada chegou ao S3")
        b.tr.offline = False
        b.rodar_hid(2.0)
        self.assertEqual(b.status()["modo"], "AUTO")
        letras = [x for x in b.tr.log if x[1] == "cmd"]
        self.assertEqual(letras, [], "nunca usa /cmd como fallback")


class TestRevisao(Base):
    """Achados da revisao independente (escritos antes das correcoes)."""

    def test_r1_pedido_ia_sem_sessao_nao_e_guardado(self):
        b = self.b
        b.tr.offline = True
        b.rodar(13.0, hid=False)                       # S3 fora: sem sessao
        b.ctl.pedir_disparo_ia({"geracao": b.ctl.geracao_atual(), "confianca": 0.9})
        b.rodar(0.1, hid=False)
        self.assertEqual(b.ia[-1][1], "descartado", "descartado na hora, nao retido")
        b.tr.offline = False
        b.rodar_hid(2.0)                               # sessao abre depois
        self.assertIsNotNone(b.cli.sessao)
        self.assertEqual(b.acoes_enviadas("disparar"), [], "pedido antigo nunca chega ao S3")
        self.assertFalse(b.d()["rele"])

    def test_r1_pedido_ia_velho_descartado(self):
        b = self.b
        b.rodar_hid(13.0)
        ctx = {"geracao": b.ctl.geracao_atual(), "publicado_em": b.relogio.t - 1.5}
        b.ctl.pedir_disparo_ia(ctx)
        b.rodar_hid(0.2)
        self.assertEqual(b.acoes_enviadas("disparar"), [])
        self.assertEqual(b.ia[-1][1:], ("descartado", "evidencia_antiga"))

    def test_r5_intencao_discreta_de_epoch_invalidado(self):
        b = self.b
        b.rodar_hid(1.0)
        enviar = b.ctl.d.passo
        b.ctl.d.passo = lambda agora: None             # despachante atrasado um ciclo
        b.rodar_hid(0.02, CRUZ)
        b.ctl.d.passo = enviar
        b.pol.perda("lacuna", b.relogio.t)            # epoch invalidado antes do envio
        b.drenar_se_preciso()
        b.rodar_hid(0.2)
        self.assertNotEqual(b.status()["modo"], "MANUAL")
        self.assertTrue(b.pol.exige_nova_selecao_manual)


class TestIncompativel(unittest.TestCase):
    def test_r2_incompativel_descarta_pedidos_ia_e_libera_memoria(self):
        class Legado:
            def enviar(self, rota, corpo):
                return Resposta(http=200, json={"pan": 90, "vigiando": True, "fogo": False, "bomba": False})

        r = apoio_nucleo.Relogio(0)
        res = []
        ctl = Controlador(ClienteProtocolo(Legado(), r), PoliticaEntrada(), r,
                          ao_resultado_ia=lambda ctx, re, m: res.append((re, m)))
        for i in range(50):
            r.t = i * 0.005
            ctl.passo(r.t)
            ctl.pedir_disparo_ia({"geracao": ctl.geracao_atual()})
        ctl.passo(r.t + 0.005)
        self.assertEqual(len(res), 50)
        self.assertTrue(all(x[0] == "descartado" and "incompativel" in x[1] for x in res), res[:2])
        self.assertEqual(len(ctl._externos), 0)

    def test_firmware_original_desabilita_controle(self):
        class Legado:
            enviados = []

            def enviar(self, rota, corpo):
                self.enviados.append(rota)
                return Resposta(http=200, json={"pan": 90, "vigiando": True, "fogo": False, "bomba": False})

        r = apoio_nucleo.Relogio(0)
        t = Legado()
        cli = ClienteProtocolo(t, r)
        ctl = Controlador(cli, PoliticaEntrada(), r)
        for i in range(400):
            r.t = i * 0.005
            ctl.passo(r.t)
        self.assertEqual(set(t.enviados), {"status"})
        self.assertIn("controle desabilitado: versao_incompativel", ctl.texto())


if __name__ == "__main__":
    unittest.main()
