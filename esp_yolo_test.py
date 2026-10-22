import argparse
import os
import time
import urllib.request

import cv2
import numpy as np
from ultralytics import YOLO

ap = argparse.ArgumentParser(
    description="Puxa fotos do endpoint /capture da ESP32-CAM e roda o YOLO em cima. "
                 "Nao usa cv2.VideoCapture no stream porque o CameraWebServer serve "
                 "multipart MJPEG, que o OpenCV nao le direto; /capture devolve um "
                 "JPEG unico por requisicao, mais simples e mais confiavel pro GC2145."
)
ap.add_argument("ip", help="IP da ESP32-CAM mostrado no Serial Monitor, ex 192.168.15.7")
ap.add_argument("--modelo", default="modelos/best_dfire.pt",
                 help="caminho do .pt; use modelos/best.pt para o modelo antigo")
ap.add_argument("--conf", type=float, default=0.45, help="confianca minima")
ap.add_argument("--imgsz", type=int, default=416, help="resolucao de entrada da inferencia")
ap.add_argument("--intervalo", type=float, default=0.0,
                 help="segundos de espera entre capturas; 0 = o mais rapido possivel")
ap.add_argument("--timeout", type=float, default=5.0, help="timeout da requisicao HTTP em segundos")
args = ap.parse_args()

url = f"http://{args.ip}/capture"
os.makedirs("amostras", exist_ok=True)

modelo = YOLO(args.modelo)
print(f"Modelo: {args.modelo}")
print(f"Classes: {modelo.names}")
print(f"Puxando de {url}")
print("Rodando. Q sai, S salva o quadro atual em amostras/")

falhas_seguidas = 0

while True:
    inicio_ciclo = time.time()
    try:
        with urllib.request.urlopen(url, timeout=args.timeout) as resp:
            dados = resp.read()
        falhas_seguidas = 0
    except Exception as erro:
        falhas_seguidas += 1
        print(f"falha ao capturar ({falhas_seguidas}x): {erro}")
        if falhas_seguidas >= 5:
            raise SystemExit(
                "ESP32-CAM nao respondeu 5 vezes seguidas. Confira o IP (Serial "
                "Monitor mostra 'Camera Ready! Use http://IP') e se esta na mesma "
                "rede Wi-Fi de 2.4GHz."
            )
        time.sleep(1)
        continue

    quadro = cv2.imdecode(np.frombuffer(dados, dtype=np.uint8), cv2.IMREAD_COLOR)
    if quadro is None:
        print("imagem invalida, pulando quadro")
        continue

    resultado = modelo(quadro, conf=args.conf, imgsz=args.imgsz, verbose=False)[0]

    # filtra pelo NOME da classe, nunca pelo indice: best.pt e best_dfire.pt tem
    # a ordem das classes trocada (ver deteccao-fogo-modelo)
    caixas_fogo = [c for c in resultado.boxes if modelo.names[int(c.cls[0])] == "Fire"]
    if caixas_fogo:
        maior = max(float(c.conf[0]) for c in caixas_fogo)
        print(f"FOGO detectado no quadro da ESP32-CAM (conf {maior:.2f})")

    anotado = resultado.plot()
    cv2.imshow("ESP32-CAM + YOLO", anotado)

    tecla = cv2.waitKey(1) & 0xFF
    if tecla == ord("q"):
        break
    if tecla == ord("s"):
        nome = f"amostras/esp_{int(time.time() * 1000)}.jpg"
        cv2.imwrite(nome, quadro)
        print("salvou", nome)

    if args.intervalo:
        restante = args.intervalo - (time.time() - inicio_ciclo)
        if restante > 0:
            time.sleep(restante)

cv2.destroyAllWindows()
