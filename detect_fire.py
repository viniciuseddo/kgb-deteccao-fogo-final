import argparse
import json
import os
import threading
import time

import cv2
from ultralytics import YOLO

ap = argparse.ArgumentParser()
ap.add_argument("fonte", nargs="?", default="0",
                help="indice da webcam, URL do celular ou do stream da ESP32-CAM")
ap.add_argument("--modelo", default="modelos/best_dfire.pt",
                help="caminho do .pt; use modelos/best.pt para o modelo antigo")
ap.add_argument("--conf", type=float, default=0.45, help="confianca minima")
ap.add_argument("--frames", type=int, default=4, help="frames seguidos para confirmar")
ap.add_argument("--porta", default=None, help="porta serial, ex COM8")
ap.add_argument("--tempo-morto", type=float, default=5.0,
                help="segundos ignorando deteccao apos disparar; 0 desliga")
ap.add_argument("--imgsz", type=int, default=416, help="resolucao de entrada da inferencia")
ap.add_argument("--sem-tilt", action="store_true",
                help="ignora o eixo vertical, so pan (comportamento antigo)")
args = ap.parse_args()

TEMPO_MORTO = args.tempo_morto
os.makedirs("amostras", exist_ok=True)

fonte = int(args.fonte) if args.fonte.isdigit() else args.fonte


class Camera:
    """Le a camera em uma thread separada e guarda so o quadro mais recente.
    Sem isso o OpenCV vai empilhando os quadros nao lidos e o atraso cresce."""

    def __init__(self, fonte):
        self.cap = cv2.VideoCapture(fonte)
        self.frame = None
        self.rodando = True
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while self.rodando:
            ok, quadro = self.cap.read()
            if ok:
                self.frame = quadro

    def parar(self):
        self.rodando = False
        self.cap.release()


arduino = None
if args.porta:
    import serial
    arduino = serial.Serial(args.porta, 9600, timeout=1)
    time.sleep(2)  # o Uno reinicia ao abrir a serial


def enviar(letra):
    print("serial ->", letra)
    if arduino:
        arduino.write(letra.encode())


modelo = YOLO(args.modelo)
print(f"Modelo: {args.modelo}")
print(f"Classes: {modelo.names}")

cam = Camera(fonte)

# Fonte de rede (ESP32-CAM, celular) demora mais que webcam USB pra dar o
# primeiro quadro. Espera ate 15s antes de desistir.
espera = time.time() + 15
while cam.frame is None and time.time() < espera:
    time.sleep(0.2)
if cam.frame is None:
    raise SystemExit(f"Nao abriu a fonte: {fonte}")

contador = 0
ultima_regiao_h = None   # esquerda / centro / direita
ultima_regiao_v = None   # cima / meio / baixo
fim_tempo_morto = 0.0

# estatisticas, uteis pra comparar dois modelos no mesmo cenario
total_quadros = 0
quadros_com_fogo = 0
maior_conf = 0.0
inicio = time.time()

print("Rodando. Q sai, S salva o quadro atual em amostras/")
while True:
    frame = cam.frame
    if frame is None:
        continue

    total_quadros += 1
    altura, largura = frame.shape[:2]
    em_tempo_morto = time.time() < fim_tempo_morto

    resultado = modelo(frame, conf=args.conf, imgsz=args.imgsz, verbose=False)[0]

    melhor = None
    if not em_tempo_morto:
        for caixa in resultado.boxes:
            # filtra pelo NOME da classe, nunca pelo numero: os dois modelos
            # usam ordens diferentes (antigo 0=Fire, novo 0=Smoke)
            if modelo.names[int(caixa.cls[0])] != "Fire":
                continue
            confianca = float(caixa.conf[0])
            if melhor is None or confianca > melhor[0]:
                melhor = (confianca, caixa.xyxy[0].tolist())

    if melhor:
        quadros_com_fogo += 1
        maior_conf = max(maior_conf, melhor[0])

    contador = contador + 1 if melhor else 0

    if contador >= args.frames:
        confianca, (x1, y1, x2, y2) = melhor
        x_centro = ((x1 + x2) / 2) / largura
        y_centro = ((y1 + y2) / 2) / altura

        # eixo horizontal -> servo de pan
        if x_centro < 0.4:
            regiao_h, letra_h = "esquerda", "L"
        elif x_centro > 0.6:
            regiao_h, letra_h = "direita", "R"
        else:
            regiao_h, letra_h = "centro", "C"

        # eixo vertical -> servo de tilt
        if y_centro < 0.4:
            regiao_v, letra_v = "cima", "U"
        elif y_centro > 0.6:
            regiao_v, letra_v = "baixo", "D"
        else:
            regiao_v, letra_v = "meio", "M"

        print(json.dumps({
            "fire": True,
            "x_center": round(x_centro, 3),
            "y_center": round(y_centro, 3),
            "conf": round(confianca, 3),
            "region": regiao_h,
            "region_v": regiao_v,
        }))

        # Sequencia: primeiro alinha na horizontal, depois na vertical,
        # e so quando os dois eixos ja estao no lugar e que dispara.
        # Um comando por ciclo, pra nao inundar a serial nem tremer o servo.
        if regiao_h != ultima_regiao_h:
            enviar(letra_h)
            ultima_regiao_h = regiao_h
        elif not args.sem_tilt and regiao_v != ultima_regiao_v:
            enviar(letra_v)
            ultima_regiao_v = regiao_v
        else:
            enviar("F")
            fim_tempo_morto = time.time() + TEMPO_MORTO

        contador = 0

    anotado = resultado.plot()
    if em_tempo_morto:
        cv2.putText(anotado, "TEMPO MORTO (CO2)", (20, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 255), 2)

    cv2.imshow("deteccao", anotado)

    tecla = cv2.waitKey(1) & 0xFF
    if tecla == ord("q"):
        break
    if tecla == ord("s"):
        nome = f"amostras/{int(time.time() * 1000)}.jpg"
        cv2.imwrite(nome, frame)
        print("salvou", nome)

cam.parar()
cv2.destroyAllWindows()
if arduino:
    arduino.close()

# resumo do teste, pra comparar modelos no mesmo cenario
duracao = time.time() - inicio
pct = (quadros_com_fogo / total_quadros * 100) if total_quadros else 0
print("\n===== RESUMO =====")
print(f"modelo            : {args.modelo}")
print(f"duracao           : {duracao:.1f}s")
print(f"quadros analisados: {total_quadros}")
print(f"quadros com Fire  : {quadros_com_fogo} ({pct:.1f}%)")
print(f"maior confianca   : {maior_conf:.3f}")