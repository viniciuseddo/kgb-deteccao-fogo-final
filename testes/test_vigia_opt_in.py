"""Tarefas 6.1-6.8 e 7.4/7.5: integracao opt-in no sistema_vigia e regressao opt-out.

O caminho novo roda com threads reais (HID falso, controle, despachante),
camera e modelo falsos, banco temporario e o NUCLEO C++ REAL como S3. Nada
abre COM, rede externa, janela ou banco real.
"""

import functools
import json
import os
import subprocess
import sys
import threading
import time
import unittest
from unittest import mock

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import apoio_nucleo  # noqa: E402
import apoio_vigia  # noqa: E402

sv = apoio_vigia.importar_sistema_vigia()
import banco as banco_mod  # noqa: E402
from controle_dualsense import vigia_integracao  # noqa: E402
from controle_dualsense.camera import Publicacao  # noqa: E402
from controle_dualsense.executor import ControleDualSense  # noqa: E402

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "dualsense_relatorios.json")
with open(FIX, encoding="utf-8") as f:
    R = {k: bytes.fromhex(v) for k, v in json.load(f)["relatorios"].items()}
RAIZ = apoio_vigia.RAIZ


class HidModulo:
    """Modulo `hid` falso: relatorios a ~250/s; registra qualquer saida."""

    def __init__(self):
        self.atual = R["repouso"]
        self.saidas = []
        self.fechado = threading.Event()
        dono = self

        class Dev:
            ultimo = 0.0

            def open_path(self, p):
                pass

            def read(self, n, timeout_ms=None):
                # Como um dispositivo real a ~250 relatorios/s: leitura sem
                # espera devolve vazio se ainda nao chegou relatorio novo.
                agora = time.monotonic()
                if agora - self.ultimo < 0.004:
                    if timeout_ms is None:
                        return []
                    time.sleep(0.004 - (agora - self.ultimo))
                self.ultimo = time.monotonic()
                return list(dono.atual)

            def close(self):
                dono.fechado.set()

            def __getattr__(self, nome):
                def f(*a, **k):
                    dono.saidas.append(nome)
                return f

        self.Dev = Dev

    def enumerate(self, vid, pid):
        return [{"vendor_id": vid, "product_id": pid, "usage_page": 1, "usage": 5, "interface_number": 3,
                 "path": b"falso", "serial_number": "SN-PRIVADO"}]

    def device(self):
        return self.Dev()


class CameraFalsa:
    def __init__(self, porta, rotacao=90):
        self.n = 0
        self.ep = 1
        self.parada = False
        self.fronteiras = []
        self.fechada = False
        CameraFalsa.ultima = self

    def publicacao(self):
        if self.parada:
            return None
        self.n += 1
        time.sleep(0.02)
        return Publicacao(np.zeros((48, 64, 3), dtype=np.uint8), self.n, time.monotonic(), self.ep)

    def fronteira(self, motivo):
        self.fronteiras.append(motivo)
        self.ep += 1

    def girar(self):
        return 0

    def fechar(self):
        self.fechada = True


class Caixas:
    def __init__(self, confs):
        self.conf = np.array(confs, dtype=float)

    def __len__(self):
        return len(self.conf)


class ModeloFalso:
    def __init__(self):
        self.fogo = False

    def predict(self, frame, conf, imgsz, verbose):
        confs = [0.9] if self.fogo else []

        class Res:
            boxes = Caixas(confs)

            def plot(self_inner):
                return frame.copy()

        return [Res()]


class TestOptOut(unittest.TestCase):
    def test_sem_opcao_nao_importa_controle_nem_hid(self):
        codigo = (
            "import sys, types; sys.path.insert(0, r'%s');"
            "m = types.ModuleType('ultralytics'); m.YOLO = object; sys.modules['ultralytics'] = m;"
            "import sistema_vigia;"
            "print(sorted(k for k in sys.modules if k == 'hid' or k.startswith('controle_dualsense')))"
        ) % RAIZ
        r = subprocess.run([sys.executable, "-c", codigo], capture_output=True, text=True, cwd=RAIZ)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "[]")

    def test_legado_continua_caracterizado(self):
        r = subprocess.run([sys.executable, "-m", "unittest", "testes.test_legado_vigia"],
                           capture_output=True, text=True, cwd=RAIZ)
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])

    def test_sketch_original_intacto(self):
        import hashlib
        caminho = os.path.join(RAIZ, "arduino", "esp32s3_vigia_bomba", "esp32s3_vigia_bomba.ino")
        with open(caminho, "rb") as f:
            h = hashlib.sha256(f.read()).hexdigest().upper()
        self.assertEqual(h, "F962CC2C8EB23AD5EAE05D0E564FC205286DC4DAD64B63B86C583BD9E732C173")

    def test_opcao_sem_hidapi_falha_com_instrucao(self):
        self.assertNotIn("hid", sys.modules)
        with mock.patch.dict(sys.modules, {"hid": None}), mock.patch("builtins.print") as p:
            with self.assertRaises(SystemExit) as e:
                vigia_integracao.carregar_hid()
        self.assertEqual(e.exception.code, 2)
        self.assertTrue(any("requirements-dualsense.txt" in str(c) for c in p.call_args_list))


class TestOptIn(unittest.TestCase):
    def setUp(self):
        self.tmp = apoio_vigia.DiretorioTemporario()
        self.nucleo = apoio_nucleo.Nucleo()
        self.rel = apoio_nucleo.RelogioReal(adiantar_ms=13000)
        self.tr = apoio_nucleo.TransporteNucleo(self.nucleo, self.rel)
        self.bd = banco_mod.Banco(os.path.join(self.tmp.name, "dados", "teste.db"))
        self.hid = HidModulo()
        self.modelo = ModeloFalso()

    def tearDown(self):
        self.nucleo.fechar()
        self.tmp.cleanup()

    def rodar(self, roteiro):
        """roteiro(teclas) roda em thread e devolve teclas via fila; 'q' encerra."""
        teclas = []
        fim = threading.Event()
        args = mock.Mock(porta="COM_FALSA", rotacao=180, frames=3, conf=0.45, imgsz=640, ip="192.168.4.1",
                         log_controle=os.path.join(self.tmp.name, "comandos.jsonl"))
        self.args = args
        janela = {"aberta": True}

        limite = time.monotonic() + 20.0
        erros = []

        def wait_key(ms):
            time.sleep(0.005)
            if teclas:
                return teclas.pop(0)
            if time.monotonic() > limite:
                erros.append("limite de 20 s do cenario")
                return ord("q")
            return ord("q") if fim.is_set() else 255

        def alvo():
            try:
                roteiro(teclas, fim)
            except BaseException as e:  # falha do roteiro encerra o laco, nao trava
                erros.append(e)
            finally:
                fim.set()

        executor = functools.partial(ControleDualSense, transporte=self.tr)
        th = threading.Thread(target=alvo, daemon=True)
        with mock.patch.object(vigia_integracao, "CameraSerialProtegida", CameraFalsa), \
                mock.patch.object(vigia_integracao.cv2, "namedWindow", lambda *a, **k: None), \
                mock.patch.object(vigia_integracao.cv2, "imshow", lambda *a, **k: None), \
                mock.patch.object(vigia_integracao.cv2, "waitKey", wait_key), \
                mock.patch.object(vigia_integracao.cv2, "destroyAllWindows", lambda: janela.update(aberta=False)), \
                mock.patch("builtins.print"):
            th.start()
            vigia_integracao.executar(args, self.modelo, self.bd, self.tmp.name, lambda: "COM_FALSA",
                                      modulo_hid=self.hid, executor_cls=executor)
        th.join(5)
        if erros:
            if isinstance(erros[0], BaseException):
                raise erros[0]
            self.fail(erros[0])
        self.assertFalse(janela["aberta"])
        return [json.loads(l) for l in open(args.log_controle, encoding="utf-8")]

    def esperar(self, cond, s=5.0):
        fim = time.monotonic() + s
        while time.monotonic() < fim:
            if cond():
                return True
            time.sleep(0.02)
        return False

    def test_fogo_confirmado_vai_pelo_protocolo_protegido_e_registra_decisao(self):
        def roteiro(teclas, fim):
            self.assertTrue(self.esperar(lambda: self.tr.status().get("sessao") is not None))
            time.sleep(0.5)
            teclas.append(ord("f"))      # 'f' no AUTO: recusado localmente, sem registro
            time.sleep(0.3)
            self.modelo.fogo = True      # 3 publicacoes distintas -> pedido IA
            self.assertTrue(self.esperar(lambda: self.tr.telemetria()["rele"]))
            self.modelo.fogo = False
            self.assertTrue(self.esperar(lambda: len(self.bd.ultimas(5)) == 1))
            fim.set()

        linhas = self.run_e_checar(roteiro)
        disparos = [l for l in linhas if l.get("evento") == "comando" and l.get("acao") == "disparar"]
        self.assertEqual([d["resultado"] for d in disparos], ["aceito"])
        self.assertEqual(disparos[0]["origem"], "ia")
        tecla = [l for l in linhas if l.get("botao") == "tecla_f"]
        self.assertEqual(tecla[0]["motivo"], "modo_auto")
        row = self.bd.ultimas(5)[0]
        self.assertEqual(row["acao"], "agua aceita pelo firmware (logico)")
        self.assertIsNone(row["duracao_bomba"])
        self.assertAlmostEqual(row["confianca"], 0.9)
        self.assertEqual(self.bd.resumo()["total"], 1, "manual nao entra nas deteccoes")
        self.assertEqual([x for x in self.tr.log if x[1] == "cmd"], [], "nenhuma letra legada")
        self.assertNotIn("SN-PRIVADO", open(self.args.log_controle, encoding="utf-8").read())

    def test_camera_perdida_controle_e_cancelamento_respondem(self):
        def roteiro(teclas, fim):
            self.assertTrue(self.esperar(lambda: self.tr.status().get("sessao") is not None))
            self.modelo.fogo = True
            self.assertTrue(self.esperar(lambda: self.tr.telemetria()["rele"]))
            CameraFalsa.ultima.parada = True   # camera cai durante a agua
            time.sleep(0.4)
            self.hid.atual = R["circulo"]      # Circulo continua funcionando
            self.assertTrue(self.esperar(lambda: not self.tr.telemetria()["rele"], 2.0))
            self.hid.atual = R["repouso"]
            fim.set()

        linhas = self.run_e_checar(roteiro)
        canc = [l for l in linhas if l.get("acao") == "cancelar"]
        self.assertTrue(canc and canc[0]["resultado"] == "aceito")
        self.assertIn("cancelamento", CameraFalsa.ultima.fronteiras)
        self.assertEqual(self.tr.status()["ultimo"]["resultado"], "cancelada")

    def test_recusa_por_cooldown_mantem_evidencia(self):
        def roteiro(teclas, fim):
            self.assertTrue(self.esperar(lambda: self.tr.status().get("sessao") is not None))
            self.tr.letra  # noqa: B018 (ponte disponivel)
            self.modelo.fogo = True
            self.assertTrue(self.esperar(lambda: self.tr.telemetria()["rele"]))
            # continua vendo fogo durante a agua/cooldown
            self.assertTrue(self.esperar(lambda: len(self.bd.ultimas(5)) >= 2, 4.0))
            self.modelo.fogo = False
            fim.set()

        self.run_e_checar(roteiro)
        acoes = sorted(r["acao"] for r in self.bd.ultimas(10))
        self.assertIn("agua aceita pelo firmware (logico)", acoes)
        self.assertTrue(any(a.startswith("agua nao solicitada") for a in acoes), acoes)
        self.assertLessEqual(len(acoes), 2, "recusas locais limitadas a um registro por 12 s")

    def run_e_checar(self, roteiro):
        linhas = self.rodar(roteiro)
        self.assertTrue(self.hid.fechado.wait(2), "HID liberado no encerramento")
        self.assertTrue(CameraFalsa.ultima.fechada)
        vivas = [t.name for t in threading.enumerate() if t.name.startswith("dualsense")]
        self.assertEqual(vivas, [], "threads do controle encerradas")
        self.assertEqual([s for s in self.hid.saidas if s != "set_nonblocking"], [])
        return linhas


if __name__ == "__main__":
    unittest.main()
