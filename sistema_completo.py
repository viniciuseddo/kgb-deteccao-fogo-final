"""
Sistema completo de deteccao de incendio, grupo KGB / Sompo Seguros.

O caminho inteiro em um script so:

    ESP32-CAM  ->  Wi-Fi  ->  YOLO  ->  serial  ->  Arduino Uno
     captura                  decide              Pan-Tilt, LCD e LED

Uso tipico na apresentacao:

    .\\venv\\Scripts\\python.exe sistema_completo.py 172.20.10.8 --porta COM8

Teclas na janela: Q sai, S salva o quadro atual em amostras/,
                  X manda o comando de apagar o LED.
"""

import argparse
import json
import os
import time
import urllib.request

import cv2
import numpy as np
from ultralytics import YOLO

ap = argparse.ArgumentParser()
ap.add_argument("ip", help="IP da ESP32-CAM, ex 172.20.10.8")
ap.add_argument("--porta", default=None,
                help="porta serial do Arduino Uno, ex COM8. Sem ela roda so na tela")
ap.add_argument("--modelo", default="modelos/best_dfire.pt", help="caminho do .pt")
ap.add_argument("--conf", type=float, default=0.45, help="confianca minima")
ap.add_argument("--frames", type=int, default=3,
                help="quadros seguidos com fogo pra confirmar")
ap.add_argument("--tempo-morto", type=float, default=8.0,
                help="segundos ignorando deteccao apos disparar; 0 desliga")
ap.add_argument("--imgsz", type=int, default=416, help="resolucao da inferencia")
ap.add_argument("--timeout", type=float, default=5.0, help="timeout HTTP em segundos")
args = ap.parse_args()

URL = f"http://{args.ip}/capture"
os.makedirs("amostras", exist_ok=True)

# ---------------------------------------------------------------- serial
arduino = None
if args.porta:
    import serial
    print(f"Abrindo {args.porta}...")
    arduino = serial.Serial(args.porta, 9600, timeout=1)
    time.sleep(2)  # o Uno reinicia sozinho quando a serial abre
    print("Arduino pronto.")
else:
    print("Sem --porta: rodando so na tela, sem falar com o Arduino.")

ultimo_comando = "-"


def enviar(letra):
    """Manda UMA letra maiuscula pro Uno. E o protocolo combinado com o Rafael."""
    global ultimo_comando
    ultimo_comando = letra
    print("serial ->", letra)
    if arduino:
        arduino.write(letra.encode())


# ---------------------------------------------------------------- modelo
modelo = YOLO(args.modelo)
print(f"Modelo: {args.modelo}")
print(f"Classes: {modelo.names}")
print(f"Camera: {URL}")
print("Rodando. Q sai, S salva o quadro, X apaga o LED.")

contador = 0
ultima_regiao_h = None
ultima_regiao_v = None
fim_tempo_morto = 0.0
falhas_seguidas = 0

total_quadros = 0
quadros_com_fogo = 0
maior_conf = 0.0
inicio = time.time()

while True:
    # ------------------------------------------------------- captura
    try:
        with urllib.request.urlopen(URL, timeout=args.timeout) as resp:
            dados = resp.read()
        falhas_seguidas = 0
    except Exception as erro:
        falhas_seguidas += 1
        print(f"falha ao capturar ({falhas_seguidas}x): {erro}")
        if falhas_seguidas >= 5:
            print("\nESP32-CAM nao respondeu 5 vezes seguidas.")
            print("Causas comuns, nesta ordem:")
            print("  1. tem uma aba do navegador aberta no IP da camera, feche ela")
            print("  2. o PC saiu do roteamento do celular e voltou pra outra rede")
            print("  3. a placa travou, aperte RST na base e espere 15 segundos")
            break
        time.sleep(1)
        continue

    quadro = cv2.imdecode(np.frombuffer(dados, dtype=np.uint8), cv2.IMREAD_COLOR)
    if quadro is None:
        print("imagem invalida, pulando quadro")
        continue

    total_quadros += 1
    altura, largura = quadro.shape[:2]
    em_tempo_morto = time.time() < fim_tempo_morto

    # ------------------------------------------------------- deteccao
    resultado = modelo(quadro, conf=args.conf, imgsz=args.imgsz, verbose=False)[0]

    melhor = None
    if not em_tempo_morto:
        for caixa in resultado.boxes:
            # filtra pelo NOME da classe, nunca pelo indice: os dois modelos do
            # projeto tem a ordem trocada (antigo 0=Fire, novo 0=Smoke)
            if modelo.names[int(caixa.cls[0])] != "Fire":
                continue
            confianca = float(caixa.conf[0])
            if melhor is None or confianca > melhor[0]:
                melhor = (confianca, caixa.xyxy[0].tolist())

    if melhor:
        quadros_com_fogo += 1
        maior_conf = max(maior_conf, melhor[0])

    contador = contador + 1 if melhor else 0

    regiao_h = regiao_v = None

    # ------------------------------------------------------- decisao
    if contador >= args.frames:
        confianca, (x1, y1, x2, y2) = melhor
        x_centro = ((x1 + x2) / 2) / largura
        y_centro = ((y1 + y2) / 2) / altura

        if x_centro < 0.4:
            regiao_h, letra_h = "esquerda", "L"
        elif x_centro > 0.6:
            regiao_h, letra_h = "direita", "R"
        else:
            regiao_h, letra_h = "centro", "C"

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

        # Um comando por ciclo, pra nao inundar a serial nem tremer o servo.
        # Primeiro alinha a horizontal, depois a vertical, e so entao dispara.
        if regiao_h != ultima_regiao_h:
            enviar(letra_h)
            ultima_regiao_h = regiao_h
        elif regiao_v != ultima_regiao_v:
            enviar(letra_v)
            ultima_regiao_v = regiao_v
        else:
            enviar("F")
            fim_tempo_morto = time.time() + args.tempo_morto

        contador = 0

    # ------------------------------------------------------- tela
    anotado = resultado.plot()

    if em_tempo_morto:
        restante = fim_tempo_morto - time.time()
        cv2.putText(anotado, f"EJETANDO CO2 ({restante:.0f}s)", (10, 28),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
    elif melhor:
        cv2.putText(anotado, "FOGO", (10, 28),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
    else:
        cv2.putText(anotado, "vigiando", (10, 28),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 200, 0), 2)

    rodape = f"serial: {ultimo_comando}"
    if regiao_h:
        rodape += f"   {regiao_h}/{regiao_v}"
    cv2.putText(anotado, rodape, (10, altura - 12),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

    cv2.imshow("Sistema de deteccao de incendio - KGB", anotado)

    tecla = cv2.waitKey(1) & 0xFF
    if tecla == ord("q"):
        break
    if tecla == ord("s"):
        nome = f"amostras/esp_{int(time.time() * 1000)}.jpg"
        cv2.imwrite(nome, quadro)
        print("salvou", nome)
    if tecla == ord("x"):
        enviar("X")
        fim_tempo_morto = 0.0
        ultima_regiao_h = ultima_regiao_v = None

cv2.destroyAllWindows()
if arduino:
    arduino.close()

duracao = time.time() - inicio
pct = (quadros_com_fogo / total_quadros * 100) if total_quadros else 0
print("\n===== RESUMO =====")
print(f"modelo            : {args.modelo}")
print(f"duracao           : {duracao:.1f}s")
print(f"quadros analisados: {total_quadros}")
print(f"quadros com Fire  : {quadros_com_fogo} ({pct:.1f}%)")
print(f"maior confianca   : {maior_conf:.3f}")
