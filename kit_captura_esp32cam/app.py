import os
import sys
import time
import glob
import json
import zipfile
import threading
import subprocess
from datetime import datetime
import cv2
import numpy as np
import requests
from flask import Flask, Response, jsonify, request, render_template_string, send_file

# Importa serial caso esteja disponível
try:
    import serial
    import serial.tools.list_ports
    HAS_SERIAL = True
except ImportError:
    HAS_SERIAL = False

app = Flask(__name__)

# Diretórios locais da pasta do kit
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CAPTURAS_DIR = os.path.join(BASE_DIR, "capturas")
VIDEOS_DIR = os.path.join(CAPTURAS_DIR, "videos")
FOTOS_DIR = os.path.join(CAPTURAS_DIR, "fotos")

os.makedirs(VIDEOS_DIR, exist_ok=True)
os.makedirs(FOTOS_DIR, exist_ok=True)

# Frame placeholder quando desconectado
_placeholder = np.zeros((480, 640, 3), dtype=np.uint8)
cv2.putText(_placeholder, "Aguardando camera...", (150, 240), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (200, 200, 200), 2)
_, _p_buf = cv2.imencode(".jpg", _placeholder, [cv2.IMWRITE_JPEG_QUALITY, 80])
PLACEHOLDER_BYTES = _p_buf.tobytes()

def listar_portas_com():
    """Retorna lista de portas COM seriais disponíveis no Windows"""
    if not HAS_SERIAL:
        return []
    portas = []
    for p in serial.tools.list_ports.comports():
        desc = p.description or ""
        portas.append({"device": p.device, "description": f"{p.device} ({desc})"})
    return portas

class StreamCaptureManager:
    def __init__(self):
        self.mode = "usb"          # 'usb', 'wifi', 'webcam'
        self.serial_port = ""
        self.baudrate = 460800
        self.wifi_url = "http://192.168.4.1/stream"
        self.webcam_idx = 0
        
        self.ser = None
        self.cap = None
        self.running = True
        self.connected = False
        self.status_msg = "Desconectado"
        
        self.current_frame = None
        self.current_jpeg = None
        self.lock = threading.Lock()
        
        # Rotação da imagem (0, 90, 180, 270)
        self.rotation = 90
        
        # Gravação de Vídeo
        self.is_recording = False
        self.rec_frames = []         # buffer em memória para calcular FPS real exato
        self.rec_start_time = 0
        self.current_video_path = ""
        
        # Captura Automática
        self.auto_capture = False
        self.auto_interval = 1.0     # segundos
        self.last_auto_capture = 0
        
        # Métricas de desempenho
        self.fps = 0.0
        self.fps_counter = 0
        self.fps_timer = time.time()
        
        # Auto-detecta porta serial inicial se disponível
        portas = listar_portas_com()
        if portas:
            # Procura CH340 ou a primeira disponível
            pref = [p["device"] for p in portas if "ch340" in p["description"].lower() or "usb" in p["description"].lower()]
            self.serial_port = pref[0] if pref else portas[0]["device"]
            
        # Thread de leitura contínua
        self.worker_thread = threading.Thread(target=self._capture_worker, daemon=True)
        self.worker_thread.start()

    def set_source(self, mode, port=None, baud=None, url=None, webcam_idx=None):
        with self.lock:
            self.mode = mode
            if port:
                self.serial_port = port
            if baud:
                self.baudrate = int(baud)
            if url:
                self.wifi_url = url.strip()
            if webcam_idx is not None:
                self.webcam_idx = int(webcam_idx)
            self._disconnect_internal()

    def _disconnect_internal(self):
        self.connected = False
        if self.ser:
            try:
                self.ser.close()
            except Exception:
                pass
            self.ser = None
        if self.cap:
            try:
                self.cap.release()
            except Exception:
                pass
            self.cap = None

    def set_led(self, val):
        val = max(0, min(40, int(val)))
        if self.mode == "usb" and self.ser and self.ser.is_open:
            try:
                self.ser.write(f"L{val}\n".encode())
            except Exception:
                pass
        elif self.mode == "wifi" and self.wifi_url:
            try:
                base = self.wifi_url.split("/stream")[0].rstrip("/")
                threading.Thread(target=lambda: requests.get(f"{base}/flash?val={val}", timeout=1.5), daemon=True).start()
            except Exception:
                pass

    def _capture_worker(self):
        while self.running:
            try:
                if self.mode == "usb":
                    self._run_serial_capture()
                elif self.mode == "wifi":
                    self._run_wifi_capture()
                elif self.mode == "webcam":
                    self._run_webcam_capture()
                else:
                    time.sleep(0.5)
            except Exception as e:
                self.status_msg = f"Erro no leitor: {e}"
                time.sleep(1.0)

    def _process_decoded_frame(self, frame):
        # Rotação
        if self.rotation == 90:
            frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
        elif self.rotation == 180:
            frame = cv2.rotate(frame, cv2.ROTATE_180)
        elif self.rotation == 270:
            frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)

        ret, clean_jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        jpeg_bytes = clean_jpg.tobytes() if ret else None

        with self.lock:
            self.current_frame = frame
            self.current_jpeg = jpeg_bytes
            self.connected = True
            
            # Se gravando vídeo, armazena no buffer temporário
            if self.is_recording:
                self.rec_frames.append(frame.copy())
                
            # Se auto-captura ligada
            if self.auto_capture:
                now = time.time()
                if now - self.last_auto_capture >= self.auto_interval:
                    self.last_auto_capture = now
                    self.save_photo(frame)

        # Contador de FPS
        self.fps_counter += 1
        now = time.time()
        if now - self.fps_timer >= 1.0:
            self.fps = round(self.fps_counter / (now - self.fps_timer), 1)
            self.fps_counter = 0
            self.fps_timer = now

    def _run_serial_capture(self):
        if not HAS_SERIAL:
            self.status_msg = "Biblioteca pyserial não instalada"
            time.sleep(1.0)
            return

        if not self.serial_port:
            portas = listar_portas_com()
            if portas:
                self.serial_port = portas[0]["device"]
            else:
                self.status_msg = "Nenhuma porta USB COM encontrada. Conecte o ESP32-CAM."
                time.sleep(1.0)
                return

        try:
            self.status_msg = f"Conectando a {self.serial_port} @ {self.baudrate}..."
            self.ser = serial.Serial()
            self.ser.port = self.serial_port
            self.ser.baudrate = self.baudrate
            self.ser.timeout = 0.2
            self.ser.open()
            self.ser.dtr = False
            self.ser.rts = False
            time.sleep(0.3)
            self.status_msg = f"Conectado na {self.serial_port}"
        except Exception as e:
            self.status_msg = f"Falha ao abrir {self.serial_port}: {e}"
            self.connected = False
            time.sleep(1.0)
            return

        buf = bytearray()
        while self.running and self.mode == "usb" and self.ser and self.ser.is_open:
            try:
                waiting = self.ser.in_waiting
                chunk = self.ser.read(waiting if waiting > 0 else 1024)
                if not chunk:
                    time.sleep(0.01)
                    continue

                buf.extend(chunk)

                # Busca pelo protocolo 0xAA 0x55 0xAA 0x55
                while True:
                    idx = buf.find(b"\xaa\x55\xaa\x55")
                    if idx == -1:
                        # Fallback: se não encontrar cabeçalho especial, tenta achar JPEG direto FF D8 ... FF D9
                        if len(buf) > 65536:
                            start_jpg = buf.find(b"\xff\xd8")
                            if start_jpg != -1:
                                end_jpg = buf.find(b"\xff\xd9", start_jpg)
                                if end_jpg != -1:
                                    jpg_data = bytes(buf[start_jpg:end_jpg+2])
                                    del buf[:end_jpg+2]
                                    arr = np.frombuffer(jpg_data, dtype=np.uint8)
                                    f = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                                    if f is not None:
                                        self._process_decoded_frame(f)
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

                    jpeg_bytes = bytes(buf[8:8+length])
                    del buf[:8+length]

                    arr = np.frombuffer(jpeg_bytes, dtype=np.uint8)
                    frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                    if frame is not None:
                        self._process_decoded_frame(frame)

                time.sleep(0.01)

            except Exception as e:
                self.status_msg = f"Conexão serial instável ({e}). Reconectando..."
                self.connected = False
                break

        self._disconnect_internal()
        time.sleep(0.5)

    def _run_wifi_capture(self):
        self.status_msg = f"Acessando stream Wi-Fi: {self.wifi_url}..."
        try:
            # Tenta via requests stream contínuo (mais resiliente que cv2 para mjpeg do ESP32)
            res = requests.get(self.wifi_url, stream=True, timeout=5.0)
            if res.status_code != 200:
                self.status_msg = f"Erro HTTP {res.status_code} ao acessar câmera"
                time.sleep(1.5)
                return

            self.status_msg = f"Stream Wi-Fi Ativo ({self.wifi_url})"
            bytes_buffer = bytes()
            for chunk in res.iter_content(chunk_size=2048):
                if not self.running or self.mode != "wifi":
                    break
                bytes_buffer += chunk
                a = bytes_buffer.find(b'\xff\xd8')
                b = bytes_buffer.find(b'\xff\xd9')
                if a != -1 and b != -1 and b > a:
                    jpg = bytes_buffer[a:b+2]
                    bytes_buffer = bytes_buffer[b+2:]
                    arr = np.frombuffer(jpg, dtype=np.uint8)
                    frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                    if frame is not None:
                        self._process_decoded_frame(frame)
        except Exception as e:
            self.status_msg = f"Falha ao conectar na câmera Wi-Fi ({e}). Verifique o IP ou se o ESP32 está ligado."
            self.connected = False
            time.sleep(1.5)

    def _run_webcam_capture(self):
        self.status_msg = f"Abrindo Câmera USB índice {self.webcam_idx}..."
        cap = cv2.VideoCapture(self.webcam_idx, cv2.CAP_DSHOW)
        if not cap.isOpened():
            self.status_msg = f"Não foi possível abrir webcam índice {self.webcam_idx}"
            time.sleep(1.5)
            return

        self.cap = cap
        self.status_msg = f"Webcam {self.webcam_idx} Conectada"
        while self.running and self.mode == "webcam" and self.cap.isOpened():
            ret, frame = self.cap.read()
            if not ret:
                time.sleep(0.05)
                continue
            self._process_decoded_frame(frame)
            time.sleep(0.02)

        self._disconnect_internal()

    def get_preview_jpeg(self):
        with self.lock:
            if not self.connected or self.current_frame is None:
                return PLACEHOLDER_BYTES
            
            # Se gravando vídeo, adiciona marca d'água REC piscante na visualização
            if self.is_recording:
                f_view = self.current_frame.copy()
                elapsed = int(time.time() - self.rec_start_time)
                mins, secs = divmod(elapsed, 60)
                if int(time.time() * 2) % 2 == 0:
                    cv2.circle(f_view, (24, 24), 9, (0, 0, 255), -1)
                text = f"REC {mins:02d}:{secs:02d} ({len(self.rec_frames)} quadros)"
                cv2.putText(f_view, text, (44, 31), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 0, 255), 2)
                ret, buf = cv2.imencode(".jpg", f_view, [cv2.IMWRITE_JPEG_QUALITY, 85])
                return buf.tobytes() if ret else self.current_jpeg
                
            return self.current_jpeg

    def save_photo(self, frame=None):
        if frame is None:
            with self.lock:
                if self.current_frame is None:
                    return None
                frame = self.current_frame.copy()
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:19]
        fname = f"foto_{ts}.jpg"
        fpath = os.path.join(FOTOS_DIR, fname)
        cv2.imwrite(fpath, frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
        return fname

    def start_recording(self):
        with self.lock:
            if self.is_recording:
                return False
            self.rec_frames = []
            self.rec_start_time = time.time()
            self.is_recording = True
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.current_video_path = os.path.join(VIDEOS_DIR, f"video_chama_{ts}.mp4")
            return True

    def stop_recording(self):
        frames_to_save = []
        start_t = 0
        v_path = ""
        with self.lock:
            if not self.is_recording:
                return None
            self.is_recording = False
            frames_to_save = list(self.rec_frames)
            self.rec_frames.clear()
            start_t = self.rec_start_time
            v_path = self.current_video_path

        if not frames_to_save:
            return None

        # Salva vídeo com FPS calculado em tempo real para sincronismo perfeito
        duration = max(0.5, time.time() - start_t)
        fps_real = len(frames_to_save) / duration
        fps_final = max(4.0, min(30.0, fps_real))

        h, w = frames_to_save[0].shape[:2]
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(v_path, fourcc, fps_final, (w, h))
        for f in frames_to_save:
            writer.write(f)
        writer.release()

        return {
            "file": os.path.basename(v_path),
            "frames": len(frames_to_save),
            "duration": round(duration, 1),
            "fps": round(fps_final, 1)
        }

camera = StreamCaptureManager()

HTML_TEMPLATE = """<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>🔥 ESP32-CAM | Kit de Captura de Chamas</title>
  <style>
    :root {
      --bg: #0d1117;
      --panel: #161b22;
      --card: #21262d;
      --border: #30363d;
      --accent: #f97316;
      --accent-hover: #ea580c;
      --red: #ef4444;
      --green: #10b981;
      --blue: #3b82f6;
      --text: #f0f6fc;
      --muted: #8b949e;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      min-height: 100vh;
      display: flex;
      flex-direction: column;
    }
    header {
      background: var(--panel);
      border-bottom: 1px solid var(--border);
      padding: 14px 24px;
      display: flex;
      align-items: center;
      justify-content: space-between;
    }
    .brand {
      display: flex;
      align-items: center;
      gap: 12px;
    }
    .brand h1 {
      font-size: 1.15rem;
      font-weight: 700;
    }
    .badge {
      display: flex;
      align-items: center;
      gap: 6px;
      padding: 4px 10px;
      border-radius: 99px;
      font-size: 0.8rem;
      font-weight: 600;
    }
    .badge-online { background: rgba(16, 185, 129, 0.15); color: var(--green); }
    .badge-offline { background: rgba(239, 68, 68, 0.15); color: var(--red); }
    .dot { width: 8px; height: 8px; border-radius: 50%; background: currentColor; }

    main {
      flex: 1;
      display: grid;
      grid-template-columns: 1fr 390px;
      gap: 20px;
      padding: 20px;
      max-width: 1550px;
      margin: 0 auto;
      width: 100%;
    }
    @media (max-width: 1050px) {
      main { grid-template-columns: 1fr; }
    }

    .feed-container {
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 12px;
      overflow: hidden;
      display: flex;
      flex-direction: column;
    }
    .video-viewport {
      background: #000;
      flex: 1;
      min-height: 480px;
      display: flex;
      align-items: center;
      justify-content: center;
      position: relative;
    }
    .video-viewport img {
      max-width: 100%;
      max-height: 640px;
      object-fit: contain;
      display: block;
    }
    .hud {
      position: absolute;
      top: 12px;
      left: 12px;
      right: 12px;
      display: flex;
      justify-content: space-between;
      pointer-events: none;
    }
    .hud-tag {
      background: rgba(0,0,0,0.75);
      backdrop-filter: blur(4px);
      padding: 4px 10px;
      border-radius: 6px;
      font-size: 0.8rem;
      font-weight: 600;
      color: #fff;
    }

    .feed-toolbar {
      padding: 14px 18px;
      border-top: 1px solid var(--border);
      display: flex;
      align-items: center;
      justify-content: space-between;
      background: var(--card);
    }
    .btn-group { display: flex; gap: 8px; }

    /* Painel Lateral */
    .side-panel {
      display: flex;
      flex-direction: column;
      gap: 16px;
    }
    .panel-box {
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 16px;
    }
    .panel-box h3 {
      font-size: 0.95rem;
      margin-bottom: 12px;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.5px;
      display: flex;
      align-items: center;
      gap: 8px;
    }

    /* Botões */
    button, .btn {
      cursor: pointer;
      border: none;
      border-radius: 8px;
      font-size: 0.9rem;
      font-weight: 600;
      padding: 10px 16px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 8px;
      transition: all 0.15s ease;
      color: #fff;
    }
    .btn-record {
      background: var(--red);
      font-size: 1.05rem;
      padding: 14px 20px;
      width: 100%;
      border-radius: 10px;
    }
    .btn-record.recording {
      background: #dc2626;
      animation: pulse-red 1.2s infinite;
    }
    @keyframes pulse-red {
      0%, 100% { box-shadow: 0 0 0 0 rgba(239, 68, 68, 0.7); }
      50% { box-shadow: 0 0 0 10px rgba(239, 68, 68, 0); }
    }
    .btn-photo { background: var(--blue); width: 100%; }
    .btn-secondary { background: var(--card); border: 1px solid var(--border); color: var(--text); }
    .btn-secondary:hover { background: #2d333b; }
    .btn-accent { background: var(--accent); }
    .btn-accent:hover { background: var(--accent-hover); }

    /* Inputs e Selects */
    label { font-size: 0.8rem; color: var(--muted); display: block; margin-bottom: 4px; }
    input, select {
      width: 100%;
      background: var(--card);
      border: 1px solid var(--border);
      color: var(--text);
      padding: 9px 12px;
      border-radius: 6px;
      font-size: 0.9rem;
      outline: none;
    }
    input:focus, select:focus { border-color: var(--accent); }
    .form-row { margin-bottom: 12px; }

    /* Abas de Conexão */
    .tabs { display: flex; border-bottom: 1px solid var(--border); margin-bottom: 14px; }
    .tab {
      flex: 1;
      text-align: center;
      padding: 8px;
      cursor: pointer;
      font-size: 0.85rem;
      font-weight: 600;
      color: var(--muted);
      border-bottom: 2px solid transparent;
    }
    .tab.active { color: var(--accent); border-color: var(--accent); }

    /* Lista de arquivos */
    .file-list {
      max-height: 180px;
      overflow-y: auto;
      font-size: 0.85rem;
      border: 1px solid var(--border);
      border-radius: 6px;
      background: var(--card);
    }
    .file-item {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 8px 12px;
      border-bottom: 1px solid var(--border);
    }
    .file-item:last-child { border-bottom: none; }
  </style>
</head>
<body>

<header>
  <div class="brand">
    <span style="font-size:1.5rem">🔥</span>
    <div>
      <h1>ESP32-CAM | Kit de Captura</h1>
      <p style="font-size:0.8rem; color:var(--muted)">Gravação de Vídeos e Fotos para Treino de IA</p>
    </div>
  </div>
  <div id="statusBadge" class="badge badge-offline">
    <span class="dot"></span>
    <span id="statusText">Verificando...</span>
  </div>
</header>

<main>
  <!-- Feed de Vídeo -->
  <div class="feed-container">
    <div class="video-viewport">
      <img id="liveFeed" src="/stream" alt="Live Feed" />
      <div class="hud">
        <div id="fpsTag" class="hud-tag">0.0 FPS</div>
        <div id="recTag" class="hud-tag" style="display:none; background:#dc2626;">🔴 GRAVANDO: <span id="recTimer">00:00</span></div>
      </div>
    </div>
    <div class="feed-toolbar">
      <div style="font-size:0.85rem; color:var(--muted)">
        Atalhos: <kbd style="background:#333;padding:2px 6px;border-radius:4px">R</kbd> Gravar Vídeo | <kbd style="background:#333;padding:2px 6px;border-radius:4px">Espaço</kbd> Foto
      </div>
      <div class="btn-group">
        <button class="btn btn-secondary" onclick="rotateCamera()">🔄 Rotacionar (<span id="rotVal">90</span>°)</button>
      </div>
    </div>
  </div>

  <!-- Painel Lateral -->
  <div class="side-panel">
    <!-- Bloco de Ações Rápidas -->
    <div class="panel-box">
      <h3>🎬 Controles de Captura</h3>
      <div style="display:flex; flex-direction:column; gap:10px;">
        <button id="btnRec" class="btn btn-record" onclick="toggleRecord()">
          🔴 <span>Iniciar Gravação de Vídeo</span>
        </button>

        <div style="display:grid; grid-template-columns:1fr 1fr; gap:8px;">
          <button class="btn btn-photo" onclick="takePhoto()">📸 Tirar Foto</button>
          <button id="btnAuto" class="btn btn-secondary" onclick="toggleAutoCapture()">⏱️ Auto (1s)</button>
        </div>

        <div class="form-row" style="margin-top:4px;">
          <label>💡 LED Flash da Câmera (0 a 40)</label>
          <input type="range" min="0" max="40" value="0" id="flashSlider" oninput="setLed(this.value)">
        </div>
      </div>
    </div>

    <!-- Bloco de Conexão -->
    <div class="panel-box">
      <h3>📡 Conexão da Câmera</h3>
      
      <div class="tabs">
        <div id="tabUsb" class="tab active" onclick="switchTab('usb')">🔌 Cabo USB</div>
        <div id="tabWifi" class="tab" onclick="switchTab('wifi')">📶 Wi-Fi (Rede)</div>
        <div id="tabWebcam" class="tab" onclick="switchTab('webcam')">📷 Webcam</div>
      </div>

      <!-- Config USB -->
      <div id="configUsb">
        <div class="form-row">
          <label>Porta COM:</label>
          <div style="display:flex; gap:6px;">
            <select id="comSelect"></select>
            <button class="btn btn-secondary" onclick="refreshComPorts()">🔄</button>
          </div>
        </div>
        <div class="form-row">
          <label>Baudrate:</label>
          <select id="baudSelect">
            <option value="460800" selected>460800 (Padrão)</option>
            <option value="921600">921600 (Rápido)</option>
            <option value="115200">115200 (Lento)</option>
          </select>
        </div>
        <button class="btn btn-accent" style="width:100%" onclick="connectUsb()">Conectar via USB</button>
      </div>

      <!-- Config WiFi -->
      <div id="configWifi" style="display:none;">
        <div class="form-row">
          <label>URL do Stream do ESP32-CAM:</label>
          <input type="text" id="wifiUrl" value="http://192.168.4.1/stream" placeholder="http://192.168.4.1/stream">
          <small style="color:var(--muted);font-size:0.75rem;margin-top:3px;display:block">
            * Conecte o PC na rede <b>ESP32CAM-FOGO</b> (senha: 12345678) ou digite o IP local.
          </small>
        </div>
        <button class="btn btn-accent" style="width:100%" onclick="connectWifi()">Conectar via Wi-Fi</button>
      </div>

      <!-- Config Webcam -->
      <div id="configWebcam" style="display:none;">
        <div class="form-row">
          <label>Índice da Câmera:</label>
          <select id="webcamIdx">
            <option value="0">Câmera 0 (Integrada / USB padrão)</option>
            <option value="1">Câmera 1 (Segunda webcam)</option>
            <option value="2">Câmera 2</option>
          </select>
        </div>
        <button class="btn btn-accent" style="width:100%" onclick="connectWebcam()">Conectar Webcam</button>
      </div>
    </div>

    <!-- Bloco de Arquivos Gravados -->
    <div class="panel-box">
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
        <h3>📁 Arquivos (<span id="fileCount">0</span>)</h3>
        <button class="btn btn-secondary" style="padding:4px 8px;font-size:0.75rem" onclick="openFolder()">Abrir Pasta ↗</button>
      </div>
      
      <div id="fileList" class="file-list">
        <div style="padding:12px; text-align:center; color:var(--muted)">Nenhum arquivo gravado ainda.</div>
      </div>

      <button class="btn btn-accent" style="width:100%; margin-top:12px; background:#059669;" onclick="downloadZip()">
        📦 Baixar Pacote .ZIP para Enviar
      </button>
    </div>
  </div>
</main>

<script>
  let isRecording = false;
  let recStartTime = 0;
  let timerInterval = null;
  let autoCaptureActive = false;

  function switchTab(mode) {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.getElementById('configUsb').style.display = 'none';
    document.getElementById('configWifi').style.display = 'none';
    document.getElementById('configWebcam').style.display = 'none';

    if (mode === 'usb') {
      document.getElementById('tabUsb').classList.add('active');
      document.getElementById('configUsb').style.display = 'block';
    } else if (mode === 'wifi') {
      document.getElementById('tabWifi').classList.add('active');
      document.getElementById('configWifi').style.display = 'block';
    } else {
      document.getElementById('tabWebcam').classList.add('active');
      document.getElementById('configWebcam').style.display = 'block';
    }
  }

  async function updateStatus() {
    try {
      const res = await fetch('/api/status');
      const data = await res.json();
      
      const badge = document.getElementById('statusBadge');
      const stText = document.getElementById('statusText');
      const fpsTag = document.getElementById('fpsTag');
      
      fpsTag.innerText = `${data.fps} FPS`;
      document.getElementById('rotVal').innerText = data.rotation;
      document.getElementById('fileCount').innerText = data.total_files;

      if (data.connected) {
        badge.className = 'badge badge-online';
        stText.innerText = data.status_msg;
      } else {
        badge.className = 'badge badge-offline';
        stText.innerText = data.status_msg;
      }

      if (data.is_recording && !isRecording) {
        setRecordingState(true);
      } else if (!data.is_recording && isRecording) {
        setRecordingState(false);
      }

      renderFiles(data.recent_files);
    } catch (e) {
      console.error(e);
    }
  }

  function renderFiles(files) {
    const list = document.getElementById('fileList');
    if (!files || files.length === 0) {
      list.innerHTML = '<div style="padding:12px; text-align:center; color:var(--muted)">Nenhum arquivo gravado ainda.</div>';
      return;
    }
    list.innerHTML = files.map(f => `
      <div class="file-item">
        <div>
          <b>${f.name}</b>
          <div style="font-size:0.75rem; color:var(--muted)">${f.size} • ${f.date}</div>
        </div>
        <span style="font-size:0.8rem">${f.type === 'video' ? '🎬' : '📸'}</span>
      </div>
    `).join('');
  }

  async function refreshComPorts() {
    try {
      const res = await fetch('/api/ports');
      const ports = await res.json();
      const select = document.getElementById('comSelect');
      select.innerHTML = '';
      if (ports.length === 0) {
        select.innerHTML = '<option value="">Nenhuma porta detectada</option>';
        return;
      }
      ports.forEach(p => {
        const opt = document.createElement('option');
        opt.value = p.device;
        opt.text = p.description;
        select.appendChild(opt);
      });
    } catch (e) {
      console.error(e);
    }
  }

  async function connectUsb() {
    const port = document.getElementById('comSelect').value;
    const baud = document.getElementById('baudSelect').value;
    if (!port) { alert('Selecione uma porta COM!'); return; }
    await fetch('/api/set_source', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ mode: 'usb', port: port, baud: baud })
    });
    updateStatus();
  }

  async function connectWifi() {
    const url = document.getElementById('wifiUrl').value;
    if (!url) { alert('Digite a URL do ESP32!'); return; }
    await fetch('/api/set_source', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ mode: 'wifi', url: url })
    });
    updateStatus();
  }

  async function connectWebcam() {
    const idx = document.getElementById('webcamIdx').value;
    await fetch('/api/set_source', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ mode: 'webcam', webcam_idx: idx })
    });
    updateStatus();
  }

  async function toggleRecord() {
    if (!isRecording) {
      const res = await fetch('/api/record/start', { method: 'POST' });
      const data = await res.json();
      if (data.ok) {
        setRecordingState(true);
      }
    } else {
      const res = await fetch('/api/record/stop', { method: 'POST' });
      const data = await res.json();
      setRecordingState(false);
      if (data.ok && data.summary) {
        alert(`✅ Vídeo salvo com sucesso: ${data.summary.file}\nQuadros: ${data.summary.frames} | Duração: ${data.summary.duration}s | FPS: ${data.summary.fps}`);
      }
      updateStatus();
    }
  }

  function setRecordingState(rec) {
    isRecording = rec;
    const btn = document.getElementById('btnRec');
    const recTag = document.getElementById('recTag');
    if (rec) {
      btn.className = 'btn btn-record recording';
      btn.innerHTML = '⏹️ <span>Parar e Salvar Vídeo</span>';
      recTag.style.display = 'block';
      recStartTime = Date.now();
      timerInterval = setInterval(() => {
        const sec = Math.floor((Date.now() - recStartTime) / 1000);
        const m = String(Math.floor(sec / 60)).padStart(2, '0');
        const s = String(sec % 60).padStart(2, '0');
        document.getElementById('recTimer').innerText = `${m}:${s}`;
      }, 500);
    } else {
      btn.className = 'btn btn-record';
      btn.innerHTML = '🔴 <span>Iniciar Gravação de Vídeo</span>';
      recTag.style.display = 'none';
      if (timerInterval) clearInterval(timerInterval);
    }
  }

  async function takePhoto() {
    const res = await fetch('/api/photo', { method: 'POST' });
    const data = await res.json();
    if (data.ok) {
      updateStatus();
    }
  }

  async function toggleAutoCapture() {
    autoCaptureActive = !autoCaptureActive;
    const btn = document.getElementById('btnAuto');
    await fetch('/api/auto_capture', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ active: autoCaptureActive })
    });
    if (autoCaptureActive) {
      btn.className = 'btn btn-accent';
      btn.innerText = '⏱️ Auto Ativo';
    } else {
      btn.className = 'btn btn-secondary';
      btn.innerText = '⏱️ Auto (1s)';
    }
  }

  async function rotateCamera() {
    const res = await fetch('/api/rotate', { method: 'POST' });
    const data = await res.json();
    document.getElementById('rotVal').innerText = data.rotation;
  }

  async function setLed(val) {
    await fetch('/api/led', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ val: val })
    });
  }

  async function openFolder() {
    await fetch('/api/open_folder', { method: 'POST' });
  }

  function downloadZip() {
    window.location.href = '/api/download_zip';
  }

  // Atalhos de Teclado
  window.addEventListener('keydown', (e) => {
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT') return;
    if (e.code === 'Space') {
      e.preventDefault();
      takePhoto();
    } else if (e.code === 'KeyR') {
      e.preventDefault();
      toggleRecord();
    }
  });

  // Inicialização
  refreshComPorts();
  setInterval(updateStatus, 1000);
  updateStatus();
</script>
</body>
</html>
"""

@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route("/stream")
def stream():
    def generate():
        while True:
            jpg = camera.get_preview_jpeg()
            if jpg is not None:
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + jpg + b'\r\n')
            time.sleep(0.04) # ~25 FPS máx na interface
    return Response(generate(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route("/api/status")
def get_status():
    vids = sorted(glob.glob(os.path.join(VIDEOS_DIR, "*.mp4")), key=os.path.getmtime, reverse=True)
    fotos = sorted(glob.glob(os.path.join(FOTOS_DIR, "*.jpg")), key=os.path.getmtime, reverse=True)
    
    recent = []
    for f in (vids[:5] + fotos[:5]):
        stat = os.stat(f)
        sz_mb = stat.st_size / (1024 * 1024)
        sz_str = f"{sz_mb:.1f} MB" if sz_mb >= 1.0 else f"{int(stat.st_size / 1024)} KB"
        recent.append({
            "name": os.path.basename(f),
            "type": "video" if f.endswith(".mp4") else "photo",
            "size": sz_str,
            "date": datetime.fromtimestamp(stat.st_mtime).strftime("%H:%M:%S")
        })
    recent.sort(key=lambda x: x["date"], reverse=True)

    return jsonify({
        "connected": camera.connected,
        "status_msg": camera.status_msg,
        "mode": camera.mode,
        "fps": camera.fps,
        "rotation": camera.rotation,
        "is_recording": camera.is_recording,
        "total_files": len(vids) + len(fotos),
        "recent_files": recent[:8]
    })

@app.route("/api/ports")
def get_ports():
    return jsonify(listar_portas_com())

@app.route("/api/set_source", methods=["POST"])
def set_source():
    data = request.json or {}
    camera.set_source(
        mode=data.get("mode", "usb"),
        port=data.get("port"),
        baud=data.get("baud"),
        url=data.get("url"),
        webcam_idx=data.get("webcam_idx")
    )
    return jsonify({"ok": True})

@app.route("/api/record/start", methods=["POST"])
def record_start():
    ok = camera.start_recording()
    return jsonify({"ok": ok})

@app.route("/api/record/stop", methods=["POST"])
def record_stop():
    summary = camera.stop_recording()
    return jsonify({"ok": True, "summary": summary})

@app.route("/api/photo", methods=["POST"])
def photo():
    fname = camera.save_photo()
    return jsonify({"ok": bool(fname), "file": fname})

@app.route("/api/auto_capture", methods=["POST"])
def auto_capture():
    data = request.json or {}
    camera.auto_capture = bool(data.get("active", False))
    return jsonify({"ok": True, "active": camera.auto_capture})

@app.route("/api/rotate", methods=["POST"])
def rotate():
    camera.rotation = (camera.rotation + 90) % 360
    return jsonify({"rotation": camera.rotation})

@app.route("/api/led", methods=["POST"])
def led():
    data = request.json or {}
    camera.set_led(data.get("val", 0))
    return jsonify({"ok": True})

@app.route("/api/open_folder", methods=["POST"])
def open_folder():
    try:
        os.startfile(CAPTURAS_DIR)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

@app.route("/api/download_zip")
def download_zip():
    zip_path = os.path.join(BASE_DIR, "pacote_capturas.zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(CAPTURAS_DIR):
            for file in files:
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, CAPTURAS_DIR)
                zf.write(full_path, arcname=os.path.join("capturas", rel_path))
    return send_file(zip_path, as_attachment=True, download_name="pacote_capturas.zip")

if __name__ == "__main__":
    port = 5005
    print("\n" + "="*60)
    print("🔥 KIT DE CAPTURA ESP32-CAM INICIADO!")
    print(f"👉 Abra no seu navegador: http://localhost:{port}")
    print("="*60 + "\n")
    
    # Abre o navegador automaticamente
    threading.Thread(target=lambda: (time.sleep(1.2), os.system(f"start http://localhost:{port}")), daemon=True).start()
    
    app.run(host="0.0.0.0", port=port, threaded=True)
