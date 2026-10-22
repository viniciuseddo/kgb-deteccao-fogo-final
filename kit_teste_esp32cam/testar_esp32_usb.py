import os
import sys
import time
import threading
import cv2
import numpy as np

# Som no Windows
try:
    import winsound
    HAS_SOUND = True
except ImportError:
    HAS_SOUND = False

# Serial para ESP32
try:
    import serial
    import serial.tools.list_ports
    HAS_SERIAL = True
except ImportError:
    print("[ERRO] Biblioteca 'pyserial' não encontrada!")
    print("Execute '1_INSTALAR_DEPENDENCIAS.bat' primeiro.")
    sys.exit(1)

# YOLO Ultralytics
try:
    import torch
    from ultralytics import YOLO
except ImportError:
    print("[ERRO] Biblioteca 'ultralytics' ou 'torch' não encontrada!")
    print("Execute '1_INSTALAR_DEPENDENCIAS.bat' primeiro.")
    sys.exit(1)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_PT = os.path.join(BASE_DIR, "chama_yolo11n_best.pt")
MODEL_ONNX = os.path.join(BASE_DIR, "chama_yolo11n_best.onnx")

def encontrar_porta_esp32():
    """Detecta automaticamente a porta COM da ESP32-CAM conectada no USB"""
    portas = list(serial.tools.list_ports.comports())
    if not portas:
        return None
        
    print("\n--- Portas USB COM detectadas ---")
    candidato = None
    for p in portas:
        desc = (p.description or "").lower()
        hwid = (p.hwid or "").lower()
        print(f"  [{p.device}] {p.description}")
        # Detecta chips comuns de gravadores ESP32 (CH340, CP2102, FTDI)
        if "ch340" in desc or "cp210" in desc or "usb-serial" in desc or "1a86:7523" in hwid or "10c4:ea60" in hwid:
            candidato = p.device
            
    if candidato:
        print(f"-> ESP32-CAM identificada automaticamente na: {candidato}")
        return candidato
    # Caso não identifique pelo nome, pega a primeira porta disponível
    return portas[0].device

class ESP32CamStreamer:
    def __init__(self, port, baud=460800):
        self.port = port
        self.baud = baud
        self.ser = None
        self.running = True
        self.current_frame = None
        self.lock = threading.Lock()
        self.connected = False
        self.rotation = 90  # 90 graus padrão da câmera na vertical
        
        self.connect()
        self.thread = threading.Thread(target=self._read_loop, daemon=True)
        self.thread.start()

    def connect(self):
        try:
            if self.ser:
                try: self.ser.close()
                except Exception: pass
            self.ser = serial.Serial()
            self.ser.port = self.port
            self.ser.baudrate = self.baud
            self.ser.timeout = 0.2
            self.ser.open()
            self.ser.dtr = False
            self.ser.rts = False
            time.sleep(0.3)
            self.connected = True
            print(f"[Conexao] Conectado na {self.port} a {self.baud} baud!")
            return True
        except Exception as e:
            self.connected = False
            self.ser = None
            return False

    def toggle_rotation(self):
        with self.lock:
            self.rotation = (self.rotation + 90) % 360
        return self.rotation

    def set_led(self, val):
        if self.ser and self.ser.is_open:
            try:
                self.ser.write(f"L{val}\n".encode())
            except Exception:
                pass

    def get_frame(self):
        with self.lock:
            if self.current_frame is None:
                return None
            return self.current_frame.copy()

    def _read_loop(self):
        buf = bytearray()
        while self.running:
            if not self.ser or not self.ser.is_open:
                time.sleep(0.5)
                self.connect()
                buf.clear()
                continue

            try:
                waiting = self.ser.in_waiting
                chunk = self.ser.read(waiting if waiting > 0 else 1024)
                if not chunk:
                    time.sleep(0.01)
                    continue

                buf.extend(chunk)

                # Protocolo 0xAA 0x55 0xAA 0x55
                while True:
                    idx = buf.find(b"\xaa\x55\xaa\x55")
                    if idx == -1:
                        # Fallback direto em marcadores JPEG FF D8 .. FF D9
                        if len(buf) > 65536:
                            s = buf.find(b"\xff\xd8")
                            if s != -1:
                                e = buf.find(b"\xff\xd9", s)
                                if e != -1:
                                    jpg = bytes(buf[s:e+2])
                                    del buf[:e+2]
                                    arr = np.frombuffer(jpg, dtype=np.uint8)
                                    f = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                                    if f is not None:
                                        self._update_frame(f)
                                    continue
                            del buf[:-4]
                        break

                    if idx > 0:
                        del buf[:idx]
                        idx = 0

                    if len(buf) < 8:
                        break

                    length = int.from_bytes(buf[4:8], "little")
                    if length > 120000 or length < 100:
                        del buf[:4]
                        continue

                    if len(buf) < 8 + length:
                        break

                    jpg_bytes = bytes(buf[8:8+length])
                    del buf[:8+length]

                    arr = np.frombuffer(jpg_bytes, dtype=np.uint8)
                    frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                    if frame is not None:
                        self._update_frame(frame)

                time.sleep(0.005)

            except Exception:
                self.connected = False
                try: self.ser.close()
                except Exception: pass
                self.ser = None
                time.sleep(0.5)

    def _update_frame(self, frame):
        with self.lock:
            rot = self.rotation
            if rot == 90:
                frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
            elif rot == 180:
                frame = cv2.rotate(frame, cv2.ROTATE_180)
            elif rot == 270:
                frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
            self.current_frame = frame

def emit_beep():
    if HAS_SOUND:
        try:
            winsound.Beep(1400, 80)
        except Exception:
            pass

def main():
    print("="*65)
    print("🔥 DETECTOR DE CHAMAS EM TEMPO REAL - YOLO11 (ESP32-CAM USB) 🔥")
    print("="*65)

    # 1. Escolhe modelo
    model_to_use = MODEL_PT if os.path.exists(MODEL_PT) else MODEL_ONNX
    if not os.path.exists(model_to_use):
        print(f"[ERRO] Modelo não encontrado em: {model_to_use}")
        input("\nPressione ENTER para sair...")
        return

    device = "cuda:0" if torch.cuda.is_available() else "cpu"
    print(f"\n[Modelo] Carregando: {os.path.basename(model_to_use)}")
    print(f"[Hardware] Processamento na: {device.upper()}")
    model = YOLO(model_to_use)

    # 2. Localiza porta COM
    port = encontrar_porta_esp32()
    if not port:
        print("\n[ERRO] Nenhuma porta COM detectada!")
        print("Conecte a ESP32-CAM via cabo USB e tente novamente.")
        input("\nPressione ENTER para sair...")
        return

    print(f"\n[ESP32-CAM] Conectando na porta: {port}...")
    streamer = ESP32CamStreamer(port, baud=460800)

    # 3. Janela OpenCV
    win_name = "Detector de Chamas ESP32-CAM | YOLO11"
    cv2.namedWindow(win_name, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(win_name, 720, 540)

    conf_thresh = 0.40  # Sensibilidade inicial (40%)
    fps = 0.0
    fps_counter = 0
    fps_timer = time.time()
    last_beep_time = 0
    led_state = False

    print("\n--- CONTROLES DO TECLADO NA JANELA DE VÍDEO ---")
    print("  [R]       Rotacionar imagem (0°, 90°, 180°, 270°)")
    print("  [+] / [↑] Aumentar limiar de confiança (menos sensível)")
    print("  [-] / [↓] Diminuir limiar de confiança (mais sensível)")
    print("  [L]       Ligar/Desligar Flash LED")
    print("  [S]       Salvar foto/screenshot da detecção")
    print("  [Q] / ESC Sair")
    print("-------------------------------------------------\n")

    while True:
        frame = streamer.get_frame()
        if frame is None:
            # Tela de espera
            blank = np.zeros((480, 640, 3), dtype=np.uint8)
            cv2.putText(blank, f"Aguardando camera na {port}...", (90, 240), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.75, (200, 200, 200), 2)
            cv2.imshow(win_name, blank)
            key = cv2.waitKey(30) & 0xFF
            if key in (ord('q'), ord('Q'), 27):
                break
            continue

        h, w = frame.shape[:2]
        t0 = time.perf_counter()

        # Inferência YOLO
        results = model.predict(frame, conf=conf_thresh, device=device, verbose=False)
        latency_ms = (time.perf_counter() - t0) * 1000

        boxes = results[0].boxes if len(results) > 0 else []
        flame_detected = len(boxes) > 0
        max_box_conf = 0.0

        # Desenha caixas de chamas
        if flame_detected:
            for b in boxes:
                c = float(b.conf[0])
                coords = b.xyxy[0].cpu().numpy().astype(int)
                x1, y1, x2, y2 = coords
                max_box_conf = max(max_box_conf, c)

                # Caixa com borda dupla estilizada
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 69, 255), 2)     # Laranja/Fogo
                cv2.rectangle(frame, (x1-1, y1-1), (x2+1, y2+1), (0, 0, 255), 1)

                # Etiqueta com fundo sólido
                label = f"CHAMA: {int(c*100)}%"
                (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 2)
                ty1 = max(0, y1 - th - 8)
                cv2.rectangle(frame, (x1, ty1), (x1 + tw + 6, ty1 + th + 6), (0, 0, 220), -1)
                cv2.putText(frame, label, (x1 + 3, ty1 + th + 2), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2)

            # Beep de alerta sonoro (com cooldown de 0.6s)
            now = time.time()
            if now - last_beep_time > 0.6:
                last_beep_time = now
                threading.Thread(target=emit_beep, daemon=True).start()

        # Faixa de Status Superior
        banner_h = 42
        if flame_detected:
            # Banner Vermelho de Alerta
            cv2.rectangle(frame, (0, 0), (w, banner_h), (0, 0, 200), -1)
            status_txt = f"ALERTA: CHAMA DETECTADA! (Certeza: {int(max_box_conf*100)}%)"
            cv2.putText(frame, status_txt, (15, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        else:
            # Banner Verde Seguro
            cv2.rectangle(frame, (0, 0), (w, banner_h), (25, 130, 35), -1)
            cv2.putText(frame, "STATUS: SEGURO (Nenhuma chama identificada)", (15, 28), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2)

        # Barra HUD Inferior
        fps_counter += 1
        if time.time() - fps_timer >= 0.5:
            fps = fps_counter / (time.time() - fps_timer)
            fps_counter = 0
            fps_timer = time.time()

        hud_y = h - 10
        cv2.rectangle(frame, (0, h - 30), (w, h), (15, 15, 20), -1)
        hud_info = f"FPS: {fps:.1f} | Latencia: {latency_ms:.1f}ms | Conf Minima: {int(conf_thresh*100)}% | Rot: {streamer.rotation}deg"
        cv2.putText(frame, hud_info, (12, hud_y), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (200, 200, 200), 1)

        cv2.imshow(win_name, frame)
        key = cv2.waitKey(1) & 0xFF

        # Tratamento de teclas
        if key in (ord('q'), ord('Q'), 27):
            break
        elif key in (ord('r'), ord('R')):
            rot = streamer.toggle_rotation()
            print(f"[Ajuste] Rotacao alterada para: {rot}°")
        elif key in (ord('+'), ord('='), 0): # Tecla + ou Seta Cima
            conf_thresh = min(0.95, round(conf_thresh + 0.05, 2))
            print(f"[Ajuste] Limiar de confianca: {int(conf_thresh*100)}%")
        elif key in (ord('-'), ord('_'), 1): # Tecla - ou Seta Baixo
            conf_thresh = max(0.10, round(conf_thresh - 0.05, 2))
            print(f"[Ajuste] Limiar de confianca: {int(conf_thresh*100)}%")
        elif key in (ord('l'), ord('L')):
            led_state = not led_state
            val = 25 if led_state else 0
            streamer.set_led(val)
            print(f"[Ajuste] LED Flash: {'LIGADO' if led_state else 'DESLIGADO'}")
        elif key in (ord('s'), ord('S')):
            ts = time.strftime("%Y%m%d_%H%M%S")
            f_out = os.path.join(BASE_DIR, f"deteccao_{ts}.jpg")
            cv2.imwrite(f_out, frame)
            print(f"📸 Print salvo em: {f_out}")

    streamer.running = False
    cv2.destroyAllWindows()
    print("\n[Finalizado] Programa encerrado.")

if __name__ == "__main__":
    main()
