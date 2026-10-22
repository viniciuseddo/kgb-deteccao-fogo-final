"""
Sistema completo KGB - deteccao de fogo com disparo sem fio
===========================================================

Junta as tres pecas do projeto:

  ESP32-CAM  ->  manda video pela USB (cabo, 460800 baud)
  Notebook   ->  roda o YOLO11 do Lucas em cima de cada quadro
  ESP32-S3   ->  recebe o disparo por WI-FI e liga LED e bomba

O S3 entra por Wi-Fi de proposito. A bomba gera ruido eletrico que
derrubava a porta USB dele no meio do disparo, e sem cabo nao existe
porta pra cair.

COMO USAR
    py sistema_vigia.py --ip 192.168.0.42

    O IP e o que o S3 imprime na serial ao ligar. Para descobrir, liga
    ele no USB uma vez, le a serial a 115200 e anota. Depois disso o
    cabo pode sair.

ATALHOS NA JANELA
    q ou ESC  sai
    f         forca um disparo manual, para testar sem fogo
    r         rotaciona a imagem
    + / -     sobe ou desce o limiar de confianca
"""

import argparse
import json
import os
import sys
import threading
import time
import urllib.request

import cv2
import numpy as np

from banco import Banco

try:
    import serial
    import serial.tools.list_ports
except ImportError:
    print("Falta o pyserial. Rode: pip install pyserial")
    sys.exit(1)

try:
    from ultralytics import YOLO
except ImportError:
    print("Falta o ultralytics. Rode: pip install ultralytics")
    sys.exit(1)


BASE = os.path.dirname(os.path.abspath(__file__))
MODELO_PADRAO = os.path.join(BASE, "kit_teste_esp32cam", "chama_yolo11n_best.pt")


# ----------------------------------------------------------- camera
def achar_porta_camera():
    """A ESP32-CAM costuma aparecer como CH340 ou CP210x."""
    portas = list(serial.tools.list_ports.comports())
    if not portas:
        return None
    for p in portas:
        desc = (p.description or "").lower()
        if any(k in desc for k in ("ch340", "cp210", "ch910", "usb-serial", "silicon labs")):
            return p.device
    return portas[0].device


class CameraSerial:
    """Le os quadros JPEG que o firmware do Lucas manda pela USB."""

    def __init__(self, porta, baud=460800, rotacao=90):
        self.porta = porta
        self.baud = baud
        self.rotacao = rotacao
        self.ser = None
        self.quadro = None
        self.lock = threading.Lock()
        self.rodando = True
        self._conectar()
        threading.Thread(target=self._loop, daemon=True).start()

    def _conectar(self):
        try:
            if self.ser:
                try: self.ser.close()
                except Exception: pass
            self.ser = serial.Serial()
            self.ser.port = self.porta
            self.ser.baudrate = self.baud
            self.ser.timeout = 0.2
            self.ser.open()
            self.ser.dtr = False
            self.ser.rts = False
            time.sleep(0.3)
            print(f"[camera] conectada na {self.porta} a {self.baud}")
            return True
        except Exception as e:
            print(f"[camera] falha ao abrir {self.porta}: {e}")
            self.ser = None
            return False

    def girar(self):
        with self.lock:
            self.rotacao = (self.rotacao + 90) % 360
        return self.rotacao

    def pegar(self):
        with self.lock:
            return None if self.quadro is None else self.quadro.copy()

    def _guardar(self, frame):
        with self.lock:
            r = self.rotacao
            if r == 90:
                frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
            elif r == 180:
                frame = cv2.rotate(frame, cv2.ROTATE_180)
            elif r == 270:
                frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
            self.quadro = frame

    def _loop(self):
        buf = bytearray()
        while self.rodando:
            if not self.ser or not self.ser.is_open:
                time.sleep(0.5)
                self._conectar()
                buf.clear()
                continue
            try:
                esperando = self.ser.in_waiting
                pedaco = self.ser.read(esperando if esperando > 0 else 1024)
                if not pedaco:
                    time.sleep(0.01)
                    continue
                buf.extend(pedaco)

                while True:
                    i = buf.find(b"\xaa\x55\xaa\x55")
                    if i == -1:
                        if len(buf) > 65536:
                            del buf[:-4]
                        break
                    if i > 0:
                        del buf[:i]
                    if len(buf) < 8:
                        break
                    tam = int.from_bytes(buf[4:8], "little")
                    if tam > 120000 or tam < 100:
                        del buf[:4]
                        continue
                    if len(buf) < 8 + tam:
                        break
                    jpg = bytes(buf[8:8 + tam])
                    del buf[:8 + tam]
                    arr = np.frombuffer(jpg, dtype=np.uint8)
                    f = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                    if f is not None:
                        self._guardar(f)
                time.sleep(0.005)
            except Exception:
                try: self.ser.close()
                except Exception: pass
                self.ser = None
                time.sleep(0.5)


# -------------------------------------------------------------- S3
class ControleS3:
    """Manda comandos pro ESP32-S3 por HTTP. Nunca trava o video."""

    def __init__(self, ip, timeout=2.0):
        self.ip = ip
        self.timeout = timeout
        self.ultimo_erro = ""
        self.online = False

    def _chamar(self, rota):
        url = f"http://{self.ip}{rota}"
        try:
            with urllib.request.urlopen(url, timeout=self.timeout) as r:
                r.read()
            self.online = True
            self.ultimo_erro = ""
            return True
        except Exception as e:
            self.online = False
            self.ultimo_erro = str(e)
            return False

    def comando(self, letra):
        """Dispara em uma thread para nao segurar o loop de video."""
        threading.Thread(
            target=self._chamar, args=(f"/cmd?c={letra}",), daemon=True
        ).start()

    def testar(self):
        return self._chamar("/status")

    def status(self):
        """Le o /status do S3 e devolve o dicionario, ou None."""
        try:
            with urllib.request.urlopen(
                    f"http://{self.ip}/status", timeout=self.timeout) as r:
                self.online = True
                return json.loads(r.read().decode("utf-8", "ignore"))
        except Exception:
            self.online = False
            return None


# ------------------------------------------------- registro no banco
def registrar_ocorrencia(bd, s3, confianca, imagem, duracao):
    """Pergunta o angulo ao S3 e grava a linha no SQLite, sem travar o video."""

    def trabalho():
        st = s3.status()
        angulo = st.get("pan") if isinstance(st, dict) else None
        try:
            bd.registrar(confianca=confianca, angulo_pan=angulo,
                         acao="bomba acionada", duracao_bomba=duracao,
                         imagem=imagem, origem="ESP32-CAM")
            print(f"    registrado no banco: {confianca:.0%} a {angulo} graus")
        except Exception as e:
            print(f"    falha ao gravar no banco: {e}")

    threading.Thread(target=trabalho, daemon=True).start()


# ------------------------------------------------------------ main
def main():
    p = argparse.ArgumentParser()
    p.add_argument("--ip", required=True, help="IP do ESP32-S3 na rede")
    p.add_argument("--porta", default=None, help="COM da ESP32-CAM (auto se omitir)")
    p.add_argument("--modelo", default=MODELO_PADRAO)
    p.add_argument("--conf", type=float, default=0.45)
    p.add_argument("--imgsz", type=int, default=640)
    p.add_argument("--frames", type=int, default=3, help="quadros seguidos para confirmar")
    p.add_argument("--cooldown", type=float, default=12.0, help="segundos entre disparos")
    p.add_argument("--rotacao", type=int, default=180)
    p.add_argument("--tempo-bomba", type=float, default=5.0,
                   help="segundos que a bomba fica ligada, so para registro")
    p.add_argument("--salvar", action="store_true",
                   help="mantido por compatibilidade, a evidencia ja e sempre salva")
    args = p.parse_args()

    print("=" * 64)
    print(" SISTEMA VIGIA KGB - camera por USB, disparo por Wi-Fi")
    print("=" * 64)

    if not os.path.exists(args.modelo):
        print(f"Modelo nao encontrado: {args.modelo}")
        sys.exit(1)

    print(f"[modelo] carregando {os.path.basename(args.modelo)}")
    modelo = YOLO(args.modelo)
    nomes = modelo.names
    print(f"[modelo] classes: {nomes}")

    bd = Banco()
    bd.abrir_sessao(os.path.basename(args.modelo), args.conf, args.ip)
    print(f"[banco] {bd.caminho}")

    s3 = ControleS3(args.ip)
    print(f"[s3] testando http://{args.ip}/status ...")
    if s3.testar():
        print("[s3] respondeu, disparo por Wi-Fi pronto")
    else:
        print(f"[s3] NAO respondeu: {s3.ultimo_erro}")
        print("[s3] confira se o S3 esta ligado, no mesmo Wi-Fi, e se o IP esta certo")
        print("[s3] o video vai rodar mesmo assim, mas o disparo nao vai sair")

    porta = args.porta or achar_porta_camera()
    if not porta:
        print("Nenhuma porta COM encontrada para a camera")
        sys.exit(1)
    cam = CameraSerial(porta, rotacao=args.rotacao)

    os.makedirs(os.path.join(BASE, "disparos"), exist_ok=True)

    seguidos = 0
    ultimo_disparo = 0.0
    n_quadros = 0
    t0 = time.time()
    conf = args.conf
    janela = "Vigia KGB - deteccao de chama"
    cv2.namedWindow(janela, cv2.WINDOW_NORMAL | cv2.WINDOW_KEEPRATIO)

    print("\nq sai | f dispara manual | r gira | + e - mudam o limiar\n")

    while True:
        frame = cam.pegar()
        if frame is None:
            time.sleep(0.05)
            tela = np.zeros((360, 640, 3), dtype=np.uint8)
            cv2.putText(tela, "aguardando a camera...", (150, 180),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (180, 180, 180), 2)
            cv2.imshow(janela, tela)
            if cv2.waitKey(30) & 0xFF in (ord("q"), 27):
                break
            continue

        n_quadros += 1
        r = modelo.predict(frame, conf=conf, imgsz=args.imgsz, verbose=False)[0]
        achou = len(r.boxes) > 0
        melhor = float(r.boxes.conf.max()) if achou else 0.0

        seguidos = seguidos + 1 if achou else 0
        confirmado = seguidos >= args.frames
        agora = time.time()

        anotado = r.plot()

        if confirmado and (agora - ultimo_disparo) > args.cooldown:
            ultimo_disparo = agora
            print(f">>> FOGO CONFIRMADO ({melhor:.0%}) - mandando F para o S3")
            s3.comando("F")

            # evidencia em disco
            nome = time.strftime("disparos/fogo_%Y%m%d_%H%M%S.jpg")
            cv2.imwrite(os.path.join(BASE, nome), anotado)

            # registra a ocorrencia no banco, em segundo plano
            registrar_ocorrencia(bd, s3, float(melhor), nome, args.tempo_bomba)

        # barra de estado
        fps = n_quadros / max(agora - t0, 0.001)
        if confirmado:
            texto, cor = f"FOGO {melhor:.0%}", (0, 0, 255)
        elif achou:
            texto, cor = f"possivel {melhor:.0%} ({seguidos}/{args.frames})", (0, 165, 255)
        else:
            texto, cor = "vigiando", (0, 200, 0)

        larg = anotado.shape[1]
        cv2.rectangle(anotado, (0, 0), (larg, 52), (25, 25, 25), -1)
        cv2.putText(anotado, texto, (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, cor, 2)

        estado_s3 = "S3 ok" if s3.online else "S3 SEM RESPOSTA"
        info = f"rot {cam.rotacao}  |  {fps:.1f} fps  |  conf {conf:.2f}  |  {estado_s3}"
        escala = 0.45
        while escala > 0.28:
            (tw, _), _ = cv2.getTextSize(info, cv2.FONT_HERSHEY_SIMPLEX, escala, 1)
            if tw <= larg - 16:
                break
            escala -= 0.03
        cv2.putText(anotado, info, (8, 43), cv2.FONT_HERSHEY_SIMPLEX, escala,
                    (200, 200, 200) if s3.online else (80, 80, 255), 1)

        cv2.imshow(janela, anotado)
        k = cv2.waitKey(1) & 0xFF
        if k in (ord("q"), 27):
            break
        elif k == ord("f"):
            print(">>> disparo MANUAL")
            s3.comando("F")
            ultimo_disparo = time.time()
        elif k == ord("r"):
            print(f"rotacao: {cam.girar()} graus")
        elif k in (ord("+"), ord("=")):
            conf = min(0.95, conf + 0.05)
        elif k in (ord("-"), ord("_")):
            conf = max(0.05, conf - 0.05)

    cam.rodando = False
    cv2.destroyAllWindows()
    print(f"\nfim. {n_quadros} quadros processados")


if __name__ == "__main__":
    main()
