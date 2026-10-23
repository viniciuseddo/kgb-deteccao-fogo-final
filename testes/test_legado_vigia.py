"""Caracterizacao do caminho ATUAL do sistema_vigia (recurso DualSense desligado).

Tarefa 1.4. Estes testes registram o comportamento existente para servir de
regressao opt-out (tarefa 7.5). Nao corrigem nada: o que esta marcado como
"preexistente" e comportamento atual documentado, inclusive imprecisoes.

Somente recursos falsos: sem COM, sem rede, sem janela, sem banco real, sem YOLO.
"""

import os
import sys
import threading
import time as time_real
import types
import unittest
from unittest import mock

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import apoio_vigia  # noqa: E402

sv = apoio_vigia.importar_sistema_vigia()
import banco as banco_mod  # noqa: E402


# ------------------------------------------------------------ falsos
def jpeg(cor, larg=16, alt=8):
    img = np.zeros((alt, larg, 3), dtype=np.uint8)
    img[:, :] = cor
    img[0, 0] = (255, 255, 255)  # marca o canto superior esquerdo
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 95])
    assert ok
    return buf.tobytes()


def quadro_serial(dados):
    return b"\xaa\x55\xaa\x55" + len(dados).to_bytes(4, "little") + dados


class SerialFalsa:
    def __init__(self, pedacos, dono):
        self.pedacos = list(pedacos)
        self.dono = dono
        self.is_open = True

    @property
    def in_waiting(self):
        return len(self.pedacos[0]) if self.pedacos else 0

    def read(self, n):
        if not self.pedacos:
            self.dono.rodando = False
            return b""
        p = self.pedacos.pop(0)
        return p[:n] if n < len(p) else p

    def close(self):
        self.is_open = False


class Relogio:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def time(self):
        return self.t

    def sleep(self, s):
        pass

    strftime = staticmethod(time_real.strftime)
    localtime = staticmethod(time_real.localtime)


class Caixas:
    def __init__(self, confs):
        self.conf = np.array(confs, dtype=float)

    def __len__(self):
        return len(self.conf)


class Resultado:
    def __init__(self, frame, confs):
        self.boxes = Caixas(confs)
        self.frame = frame

    def plot(self):
        return self.frame.copy()


class ModeloFalso:
    names = {0: "chama"}

    def __init__(self, roteiro):
        self.roteiro = list(roteiro)  # lista de listas de confianca por quadro
        self.confs_pedidas = []

    def predict(self, frame, conf, imgsz, verbose):
        self.confs_pedidas.append((round(conf, 2), imgsz))
        confs = self.roteiro.pop(0) if self.roteiro else []
        return [Resultado(frame, confs)]


class CameraFalsa:
    def __init__(self, porta, rotacao=90):
        self.porta = porta
        self.rotacao = rotacao
        self.rodando = True
        CameraFalsa.ultima = self

    def pegar(self):
        return np.zeros((48, 64, 3), dtype=np.uint8)

    def girar(self):
        self.rotacao = (self.rotacao + 90) % 360
        return self.rotacao


class Cenario:
    """Executa main() com tudo falso. passos: lista de (avanco_s, confs, tecla)."""

    def __init__(self, passos, argv_extra=(), s3_online=True):
        self.passos = passos
        self.argv_extra = list(argv_extra)
        self.s3_online = s3_online
        self.rotas = []
        self.lock = threading.Lock()
        self.registros = []
        self.imagens = []

    def rodar(self):
        relogio = Relogio()
        roteiro_conf = [p[1] for p in self.passos]
        teclas = [p[2] for p in self.passos]
        avancos = [p[0] for p in self.passos]
        modelo = ModeloFalso(roteiro_conf)
        self.modelo = modelo
        cen = self

        def chamar(s3, rota):
            with cen.lock:
                cen.rotas.append(rota)
            s3.online = cen.s3_online
            return cen.s3_online

        def status(s3):
            return {"pan": 77, "vigiando": False, "fogo": True, "bomba": True} if cen.s3_online else None

        def wait_key(ms):
            i = len(cen.teclas_usadas)
            cen.teclas_usadas.append(ms)
            if i < len(avancos):
                relogio.t += avancos[i]
                return teclas[i] if teclas[i] is not None else 255
            return ord("q")

        self.teclas_usadas = []
        tmp = apoio_vigia.DiretorioTemporario()
        self.tmp = tmp
        bd = banco_mod.Banco(os.path.join(tmp.name, "dados", "teste.db"))
        self.bd = bd
        orig_registrar = bd.registrar

        def registrar(**kw):
            with cen.lock:
                cen.registros.append(kw)
            return orig_registrar(**kw)

        bd.registrar = registrar

        def imwrite(caminho, img):
            cen.imagens.append(caminho)
            return True

        argv = ["sistema_vigia.py", "--ip", "192.0.2.1", "--porta", "COM_FALSA",
                "--modelo", __file__, *self.argv_extra]
        with mock.patch.object(sys, "argv", argv), \
                mock.patch.object(sv, "YOLO", lambda caminho: modelo), \
                mock.patch.object(sv, "Banco", lambda: bd), \
                mock.patch.object(sv, "CameraSerial", CameraFalsa), \
                mock.patch.object(sv.ControleS3, "_chamar", chamar), \
                mock.patch.object(sv.ControleS3, "status", status), \
                mock.patch.object(sv, "BASE", tmp.name), \
                mock.patch.object(sv, "time", relogio), \
                mock.patch.object(sv.cv2, "namedWindow", lambda *a, **k: None), \
                mock.patch.object(sv.cv2, "imshow", lambda *a, **k: None), \
                mock.patch.object(sv.cv2, "waitKey", wait_key), \
                mock.patch.object(sv.cv2, "destroyAllWindows", lambda: None), \
                mock.patch.object(sv.cv2, "imwrite", imwrite), \
                mock.patch("builtins.print"):
            sv.main()
            # threads daemon de HTTP/registro
            limite = time_real.monotonic() + 3
            while time_real.monotonic() < limite:
                with self.lock:
                    pronto = len(self.registros) >= self.esperados_registro
                if pronto:
                    break
                time_real.sleep(0.01)
        return self

    esperados_registro = 0

    def letras(self):
        with self.lock:
            return [r.split("=")[1] for r in self.rotas if r.startswith("/cmd")]

    def fechar(self):
        self.tmp.cleanup()


FOGO = [0.8]
NADA = []
Q = ord("q")


class TestCameraSerialLegado(unittest.TestCase):
    def nova_camera(self, pedacos, rotacao):
        cam = object.__new__(sv.CameraSerial)
        cam.porta = "COM_FALSA"
        cam.baud = 460800
        cam.rotacao = rotacao
        cam.quadro = None
        cam.lock = threading.Lock()
        cam.rodando = True
        cam.ser = SerialFalsa(pedacos, cam)
        cam.publicados = []
        orig = cam._guardar

        def guardar(f):
            cam.publicados.append(f.shape)
            orig(f)

        cam._guardar = guardar
        return cam

    def test_parser_marcador_tamanho_e_lixo(self):
        a, b = jpeg((0, 0, 255)), jpeg((0, 255, 0))
        fluxo = b"lixo" + quadro_serial(a) + b"\xaa\x55\xaa\x55" + (10).to_bytes(4, "little") + quadro_serial(b)
        pedacos = [fluxo[i:i + 7] for i in range(0, len(fluxo), 7)]
        cam = self.nova_camera(pedacos, rotacao=0)
        with mock.patch.object(sv, "time", types.SimpleNamespace(sleep=lambda s: None, time=time_real.time)):
            cam._loop()
        self.assertEqual(len(cam.publicados), 2, "dois JPEGs validos; o de tamanho < 100 e descartado")
        self.assertEqual(cam.pegar().shape, (8, 16, 3))

    def test_rotacao_aplicada_ao_publicar(self):
        cam = self.nova_camera([quadro_serial(jpeg((10, 20, 30)))], rotacao=90)
        with mock.patch.object(sv, "time", types.SimpleNamespace(sleep=lambda s: None, time=time_real.time)):
            cam._loop()
        self.assertEqual(cam.pegar().shape, (16, 8, 3))
        self.assertEqual(cam.girar(), 180)

    def test_backlog_preexistente_publica_todos_os_quadros_acumulados(self):
        # PREEXISTENTE: varios JPEGs acumulados na COM sao todos publicados em
        # sequencia; o ultimo fica como 'quadro atual'. Sem ID nem horario.
        fluxo = b"".join(quadro_serial(jpeg((i * 40, 0, 0))) for i in range(3))
        cam = self.nova_camera([fluxo], rotacao=0)
        with mock.patch.object(sv, "time", types.SimpleNamespace(sleep=lambda s: None, time=time_real.time)):
            cam._loop()
        self.assertEqual(len(cam.publicados), 3)
        self.assertFalse(hasattr(cam, "frame_id_local"))


class TestMainLegado(unittest.TestCase):
    def test_parametros_padrao(self):
        p = Cenario([(0.1, NADA, Q)]).rodar()
        self.assertEqual(p.modelo.confs_pedidas[0], (0.45, 640))
        self.assertEqual(CameraFalsa.ultima.rotacao, 180)
        p.fechar()

    def test_debounce_tres_quadros_e_cooldown_nominal(self):
        passos = [(0.1, FOGO, None)] * 3          # 3o quadro (t=0,2 s) confirma -> F
        passos += [(1.0, FOGO, None)] * 5         # ate t=5,3 s: dentro dos 12 s, nada
        passos += [(7.0, FOGO, None)]             # t=5,3 s: ainda nada
        passos += [(0.1, FOGO, None)]             # t=12,3 s: 12,1 s apos o 1o -> F
        passos += [(0.1, NADA, Q)]
        c = Cenario(passos)
        c.esperados_registro = 2
        c.rodar()
        self.assertEqual(c.letras(), ["F", "F"])
        self.assertIn("/status", c.rotas, "testar() no inicio")
        self.assertEqual(len(c.imagens), 2)
        self.assertTrue(all(os.path.basename(i).startswith("fogo_") for i in c.imagens))
        self.assertTrue(all(os.path.basename(os.path.dirname(os.path.normpath(i))) == "disparos" for i in c.imagens))
        c.fechar()

    def test_quadro_sem_fogo_zera_sequencia(self):
        passos = [(0.1, FOGO, None), (0.1, FOGO, None), (0.1, NADA, None), (0.1, FOGO, None), (0.1, FOGO, None),
                  (0.1, NADA, Q)]
        c = Cenario(passos).rodar()
        self.assertEqual(c.letras(), [])
        c.fechar()

    def test_registro_da_ocorrencia_no_contrato_do_painel(self):
        passos = [(0.1, [0.6, 0.9], None)] * 3 + [(0.1, NADA, Q)]
        c = Cenario(passos)
        c.esperados_registro = 1
        c.rodar()
        self.assertEqual(len(c.registros), 1)
        r = c.registros[0]
        self.assertEqual(r["acao"], "bomba acionada")
        self.assertEqual(r["duracao_bomba"], 5.0, "--tempo-bomba e so metadado")
        self.assertEqual(r["origem"], "ESP32-CAM")
        self.assertEqual(r["angulo_pan"], 77)
        self.assertAlmostEqual(r["confianca"], 0.9)
        linhas = c.bd.ultimas(5)
        self.assertEqual(len(linhas), 1)
        self.assertEqual(set(linhas[0]), {"id", "ts", "data_hora", "confianca", "angulo_pan", "acao",
                                          "duracao_bomba", "imagem", "origem"})
        self.assertEqual(c.bd.resumo()["total"], 1)
        c.fechar()

    def test_preexistente_registra_bomba_acionada_com_atuador_ausente(self):
        # PREEXISTENTE (nao corrigido nesta mudanca): sem resposta do S3 o
        # caminho atual grava 'bomba acionada' com angulo None.
        passos = [(0.1, FOGO, None)] * 3 + [(0.1, NADA, Q)]
        c = Cenario(passos, s3_online=False)
        c.esperados_registro = 1
        c.rodar()
        self.assertEqual(len(c.registros), 1)
        self.assertEqual(c.registros[0]["acao"], "bomba acionada")
        self.assertIsNone(c.registros[0]["angulo_pan"])
        c.fechar()

    def test_teclas_f_r_mais_menos(self):
        passos = [(0.1, NADA, ord("f")), (0.1, NADA, ord("r")), (0.1, NADA, ord("+")), (0.1, NADA, ord("+")),
                  (0.1, NADA, ord("-")), (0.1, NADA, None), (0.1, NADA, Q)]
        c = Cenario(passos).rodar()
        self.assertEqual(c.letras(), ["F"], "f manda F sem consultar modo/cooldown")
        self.assertEqual(c.registros, [], "disparo manual nao vira deteccao")
        self.assertEqual(CameraFalsa.ultima.rotacao, 270)
        self.assertEqual([x[0] for x in c.modelo.confs_pedidas], [0.45, 0.45, 0.45, 0.5, 0.55, 0.5, 0.5])
        c.fechar()

    def test_f_manual_reinicia_o_cooldown_automatico(self):
        passos = [(0.1, NADA, ord("f"))] + [(0.1, FOGO, None)] * 3 + [(0.1, NADA, Q)]
        c = Cenario(passos).rodar()
        self.assertEqual(c.letras(), ["F"], "fogo confirmado logo apos f fica no cooldown de 12 s")
        c.fechar()

    def test_abreviacao_con_continua_valendo(self):
        # Antes da mudanca, '--con' resolvia para '--conf' por prefixo do argparse.
        c = Cenario([(0.1, NADA, Q)], argv_extra=["--con", "0.5"]).rodar()
        self.assertEqual(c.modelo.confs_pedidas[0][0], 0.5)
        c.fechar()

    def test_sem_opcao_nao_importa_hid(self):
        self.assertNotIn("hid", sys.modules)


if __name__ == "__main__":
    unittest.main()
