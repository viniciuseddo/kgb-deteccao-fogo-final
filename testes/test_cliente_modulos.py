"""Testes dos modulos do cliente sem hardware: camera/publicacao, confirmacao,
adaptador HID (mock), despachante (saturacao), transporte (loopback) e JSONL.
"""

import http.server
import json
import os
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import apoio_vigia  # noqa: E402
from controle_dualsense import camera, confirmacao, despachante, entrada, registro, transporte  # noqa: E402
from controle_dualsense.adaptador_hid import AdaptadorHID  # noqa: E402
from controle_dualsense.protocolo import Resposta  # noqa: E402

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "dualsense_relatorios.json")
with open(FIX, encoding="utf-8") as f:
    R = {k: bytes.fromhex(v) for k, v in json.load(f)["relatorios"].items()}


def jpg(n):
    corpo = bytes([0xFF, 0xD8]) + bytes([n % 256]) * 200 + bytes([0xFF, 0xD9])
    return b"\xaa\x55\xaa\x55" + len(corpo).to_bytes(4, "little") + corpo


class Relogio:
    def __init__(self, t=10.0):
        self.t = t

    def __call__(self):
        return self.t


class TestPublicador(unittest.TestCase):
    def novo(self):
        self.r = Relogio()
        self.descartes = 0
        return camera.PublicadorQuadros(lambda b: ("frame", b[2]), relogio=self.r)

    def descartar(self):
        self.descartes += 1

    def test_primeiro_jpeg_apos_partida_e_ignorado_e_ids_crescem(self):
        p = self.novo()
        self.assertIsNone(p.lote(b"", 0, self.descartar), "fronteira de partida")
        self.assertIsNone(p.lote(jpg(1), 0, self.descartar), "primeiro JPEG ignorado")
        a = p.lote(jpg(2), 0, self.descartar)
        self.r.t += 0.05
        b = p.lote(jpg(3), 0, self.descartar)
        self.assertEqual((a.frame_id_local, b.frame_id_local), (1, 2))
        self.assertEqual(a.camera_epoch, b.camera_epoch)
        self.assertLess(a.published_at_monotonic, b.published_at_monotonic)

    def test_lote_publica_somente_o_mais_recente(self):
        p = self.novo()
        p.lote(b"", 0, self.descartar)
        p.lote(jpg(1), 0, self.descartar)
        pub = p.lote(jpg(5) + jpg(6) + jpg(7), 0, self.descartar)
        self.assertEqual(pub.frame, ("frame", 7))
        self.assertEqual(pub.frame_id_local, 1)

    def test_pausa_com_tres_jpegs_antigos_acumulados(self):
        p = self.novo()
        p.lote(b"", 0, self.descartar)
        p.lote(jpg(1), 0, self.descartar)
        p.lote(jpg(2), 0, self.descartar)
        ep = p.camera_epoch
        self.r.t += 0.8  # pausa de leitura > 500 ms
        self.assertIsNone(p.lote(jpg(10) + jpg(11) + jpg(12), 300000, self.descartar))
        self.assertEqual(self.descartes, 2, "partida + pausa descartam a entrada pendente da COM")
        self.assertEqual(p.camera_epoch, ep + 1)
        self.assertIsNone(p.pegar(), "publicacao anterior invalidada")
        self.assertIsNone(p.lote(jpg(13), 0, self.descartar), "primeiro JPEG apos a fronteira ignorado")
        novos = [p.lote(jpg(20 + i), 0, self.descartar) for i in range(3)]
        self.assertTrue(all(n is not None and n.camera_epoch == ep + 1 for n in novos))

    def test_backlog_acima_do_orcamento_e_barreira_externa(self):
        p = self.novo()
        p.lote(b"", 0, self.descartar)
        p.lote(jpg(1), 0, self.descartar)
        p.lote(jpg(2), 0, self.descartar)
        ep = p.camera_epoch
        self.assertIsNone(p.lote(jpg(3), camera.BACKLOG_MAX_BYTES + 1, self.descartar))
        self.assertEqual(p.camera_epoch, ep + 1)
        p.lote(jpg(4), 0, self.descartar)
        self.assertIsNotNone(p.lote(jpg(5), 0, self.descartar))
        p.fronteira("cancelamento")
        self.assertIsNone(p.pegar())
        self.assertIsNone(p.lote(jpg(6), 0, self.descartar))
        self.assertEqual(p.camera_epoch, ep + 2)


class Pub:
    def __init__(self, i, t, ep=1):
        self.frame_id_local, self.published_at_monotonic, self.camera_epoch = i, t, ep


class TestConfirmacao(unittest.TestCase):
    def test_tres_ids_distintos_frescos(self):
        c = confirmacao.ConfirmacaoAutomatica()
        self.assertFalse(c.registrar(Pub(1, 0.0), True, 1, 1, 0.1))
        self.assertFalse(c.registrar(Pub(1, 0.0), True, 1, 1, 0.2), "mesmo quadro de novo nao conta")
        self.assertFalse(c.registrar(Pub(2, 0.2), True, 1, 1, 0.3))
        self.assertTrue(c.registrar(Pub(3, 0.3), True, 1, 1, 0.4))
        self.assertEqual(c.contagem, 0, "zera apos confirmar")

    def test_quadro_congelado_ou_velho_nao_confirma(self):
        c = confirmacao.ConfirmacaoAutomatica()
        c.registrar(Pub(1, 0.0), True, 1, 1, 0.1)
        c.registrar(Pub(2, 0.1), True, 1, 1, 0.2)
        self.assertFalse(c.registrar(Pub(3, 0.2), True, 1, 1, 1.5), "idade local > 1 s")
        self.assertEqual(c.contagem, 0)

    def test_geracao_antiga_nao_conta_e_epoch_novo_recomeca(self):
        c = confirmacao.ConfirmacaoAutomatica()
        c.registrar(Pub(1, 0.0), True, 1, 1, 0.1)
        c.registrar(Pub(2, 0.1), True, 1, 1, 0.2)
        self.assertFalse(c.registrar(Pub(3, 0.2), True, 1, 2, 0.3), "inferencia de antes da barreira")
        self.assertFalse(c.registrar(Pub(4, 0.3, ep=2), True, 2, 2, 0.4))
        self.assertEqual(c.contagem, 1, "epoch/geracao novos recomecam a contagem")

    def test_sem_fogo_zera(self):
        c = confirmacao.ConfirmacaoAutomatica()
        c.registrar(Pub(1, 0.0), True, 1, 1, 0.1)
        c.registrar(Pub(2, 0.1), False, 1, 1, 0.2)
        self.assertEqual(c.contagem, 0)


class HidFalso:
    """Modulo hid falso: registra QUALQUER chamada de saida."""

    def __init__(self, candidatos, relatorios):
        self.candidatos = candidatos
        self.relatorios = list(relatorios)
        self.saidas = []
        self.aberturas = 0
        self.fechamentos = 0
        dono = self

        class Dev:
            def open_path(self, p):
                dono.aberturas += 1

            def read(self, n, timeout_ms=None):
                if not dono.relatorios:
                    return []
                r = dono.relatorios.pop(0)
                if isinstance(r, Exception):
                    raise r
                return list(r)

            def close(self):
                dono.fechamentos += 1

            def __getattr__(self, nome):  # write, send_feature_report, set_nonblocking...
                def f(*a, **k):
                    dono.saidas.append(nome)
                return f

        self.Dev = Dev

    def enumerate(self, vid, pid):
        return self.candidatos

    def device(self):
        return self.Dev()


CAND = {"vendor_id": 0x054C, "product_id": 0x0CE6, "usage_page": 1, "usage": 5, "interface_number": 3,
        "path": b"x", "serial_number": "SN-PRIVADO"}


class TestAdaptadorHID(unittest.TestCase):
    def test_ciclo_completo_sem_escrita(self):
        h = HidFalso([CAND], [R["repouso"]] * 5 + [OSError("removido")] + [R["repouso"]] * 3)
        logs = []
        pol = entrada.PoliticaEntrada()
        r = Relogio(0.0)
        a = AdaptadorHID(pol, threading.RLock(), modulo_hid=h, relogio=r,
                         ao_log=lambda ev, **kw: logs.append((ev, kw)))
        for _ in range(20):
            r.t += 0.004
            a.iteracao()
        self.assertGreaterEqual(h.aberturas, 2, "reabriu apos o erro")
        self.assertGreaterEqual(h.fechamentos, 1)
        PERMITIDAS = {"set_nonblocking"}  # configuracao local do handle, nada vai ao controle
        self.assertEqual([s for s in h.saidas if s not in PERMITIDAS], [],
                         "nenhuma escrita/feature report/output report")
        self.assertIn("set_nonblocking", h.saidas)
        self.assertNotIn("SN-PRIVADO", repr(logs))
        a.parar()
        self.assertEqual([s for s in h.saidas if s not in PERMITIDAS], [])

    def test_ausente_ou_ambiguo_nao_abre(self):
        for cands, motivo in (([], "dualsense_ausente"), ([CAND, dict(CAND, path=b"y")], "dualsense_ambiguo")):
            h = HidFalso(cands, [])
            a = AdaptadorHID(entrada.PoliticaEntrada(), threading.RLock(), modulo_hid=h)
            self.assertFalse(a.abrir())
            self.assertEqual(a.motivo, motivo)
            self.assertEqual(h.aberturas, 0)


class ClienteFalso:
    def __init__(self, atraso=0.0):
        self.sessao = object()
        self.enviados = []
        self.atraso = atraso
        self.seq = 0

    def montar(self, acao, **c):
        self.seq += 1
        return dict(c, acao=acao, id=f"i{self.seq}"), None

    def enviar(self, corpo):
        if self.atraso:
            time.sleep(self.atraso)
        self.enviados.append(corpo["acao"])
        return Resposta(http=200, json={"resultado": "aceito"})


class TestDespachante(unittest.TestCase):
    def test_r4_cancelamento_sem_janela_pede_janela_e_tenta_de_novo(self):
        class SemJanela(ClienteFalso):
            def __init__(self):
                super().__init__()
                self.tem_jx = False

            def montar(self, acao, **c):
                if acao == "cancelar" and not self.tem_jx:
                    return None, "sem_janela"
                return super().montar(acao, **c)

            def enviar(self, corpo):
                if corpo["acao"] == "janela":
                    self.tem_jx = True
                return super().enviar(corpo)

        c = SemJanela()
        d = despachante.Despachante(c, lambda: 0)
        res = []
        d.pedir_cancelamento(despachante.Intencao("cancelar", {"cancel_ate": 0}, valido_ate=0.5,
                                                  ao_resultado=lambda i, r, cp, m: res.append((r, m))))
        d.passo(0.0)
        d.passo(0.01)
        self.assertEqual(c.enviados, ["janela", "cancelar"])
        self.assertTrue(res and res[-1][0] is not None and res[-1][0].aceito)

    def test_saturacao_movimento_20hz_e_fila_limitada(self):
        c = ClienteFalso()
        d = despachante.Despachante(c, lambda: 0)
        t = 0.0
        descartados = []
        for k in range(500):  # 2 s a 250 relatorios/s
            t = k * 0.004
            d.definir_movimento(((k % 7) - 3) / 3.0, 1, 1)
            if k % 10 == 0:
                d.pedir(despachante.Intencao("auto", valido_ate=t + 0.5,
                                             ao_resultado=lambda i, r, cp, m: descartados.append(m)))
            d.passo(t)
        movs = c.enviados.count("mover")
        self.assertLessEqual(movs, 2 * 20 + 1)
        self.assertLessEqual(len(d.fila), despachante.CAPACIDADE)

    def test_cancelamento_tem_prioridade_e_limpa_pendentes(self):
        c = ClienteFalso()
        d = despachante.Despachante(c, lambda: 0)
        motivos = []
        cb = lambda i, r, cp, m: motivos.append((i.acao, m))  # noqa: E731
        for _ in range(3):
            d.pedir(despachante.Intencao("disparar", {"origem": "ia"}, valido_ate=1.0, ao_resultado=cb))
        d.definir_movimento(1.0, 1, 1)
        d.pedir_cancelamento(despachante.Intencao("cancelar", {"cancel_ate": 0}, valido_ate=1.0, ao_resultado=cb))
        d.passo(0.0)
        self.assertEqual(c.enviados, ["cancelar"])
        self.assertEqual([m for a, m in motivos if a == "disparar"], ["cancelamento"] * 3, "descartados, nao adiados")
        d.passo(0.1)
        self.assertNotIn("disparar", c.enviados)

    def test_intencao_expirada_e_descartada(self):
        c = ClienteFalso()
        d = despachante.Despachante(c, lambda: 0)
        m = []
        d.pedir(despachante.Intencao("disparar", valido_ate=0.5, ao_resultado=lambda i, r, cp, mo: m.append(mo)))
        d.passo(0.6)
        self.assertEqual(m, ["expirada"])
        self.assertNotIn("disparar", c.enviados)


class Lento(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        time.sleep(0.5)
        try:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"{}")
        except OSError:
            pass  # o cliente ja desistiu (timeout), que e o esperado

    def log_message(self, *a):
        pass


class TestTransporte(unittest.TestCase):
    def test_somente_ip_local(self):
        for ruim in ("8.8.8.8", "exemplo.com", "192.168.0.17:80", ""):
            with self.assertRaises(ValueError):
                transporte.validar_host(ruim)
        self.assertEqual(transporte.validar_host("192.168.0.17"), "192.168.0.17")

    def test_timeout_vira_desconhecido_sem_retry(self):
        srv = http.server.HTTPServer(("127.0.0.1", 0), Lento)
        th = threading.Thread(target=srv.handle_request, daemon=True)
        th.start()
        try:
            t = transporte.TransporteHTTP("127.0.0.1", timeout=0.1, porta=srv.server_address[1])
            t0 = time.monotonic()
            r = t.enviar("status", None)
            self.assertTrue(r.desconhecido)
            self.assertLess(time.monotonic() - t0, 0.45)
        finally:
            th.join(2)
            srv.server_close()


class TestLockSemHTTP(unittest.TestCase):
    def test_r3_http_lento_nao_retem_lock_da_entrada_nem_bloqueia_yolo(self):
        from controle_dualsense.controlador import Controlador
        from controle_dualsense.protocolo import ClienteProtocolo

        class Lento:
            def enviar(self, rota, corpo):
                time.sleep(0.3)
                return Resposta(desconhecido=True, erro="timeout")

        ctl = Controlador(ClienteProtocolo(Lento(), time.monotonic), entrada.PoliticaEntrada(), time.monotonic)
        th = threading.Thread(target=ctl.passo, args=(time.monotonic(),))
        th.start()
        time.sleep(0.05)
        t0 = time.monotonic()
        with ctl.lock:          # o que a thread HID faz a cada relatorio
            pass
        ctl.pedir_disparo_ia({"geracao": ctl.geracao_atual()})
        ctl.texto()
        espera = time.monotonic() - t0
        th.join(2)
        self.assertLess(espera, 0.05, f"lock retido durante HTTP ({espera:.3f} s)")


class TestRegistro(unittest.TestCase):
    def test_jsonl_separado_sem_identificador(self):
        with apoio_vigia.DiretorioTemporario() as d:
            caminho = os.path.join(d, "comandos_controle.jsonl")
            r = registro.RegistroJSONL(caminho)
            r.escrever("comando", acao="disparar", resultado="aceito", serial_number="X", path=b"p")
            r.escrever("comando", acao="cancelar", resultado="desconhecido")
            linhas = [json.loads(l) for l in open(caminho, encoding="utf-8")]
            self.assertEqual(len(linhas), 2)
            self.assertNotIn("serial_number", linhas[0])
            self.assertNotIn("path", linhas[0])

    def test_texto_acao_nao_afirma_agua(self):
        self.assertIn("logico", registro.acao_deteccao("aceito", None))
        self.assertIn("cooldown", registro.acao_deteccao("recusado", "cooldown"))
        self.assertIn("desconhecido", registro.acao_deteccao("desconhecido", "timeout"))
        for r in ("aceito", "recusado", "desconhecido", "descartado"):
            self.assertNotEqual(registro.acao_deteccao(r, None), "bomba acionada")


if __name__ == "__main__":
    unittest.main()
