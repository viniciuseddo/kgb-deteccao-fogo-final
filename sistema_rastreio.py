"""
Rastreamento continuo: a torre persegue o alvo em vez de pular entre posicoes.

Diferenca para o sistema_completo.py, que continua intacto e funcionando:

    sistema_completo.py   ->  decide "esquerda, centro ou direita" e manda L, C ou R.
                              Tres posicoes fixas, o servo pula entre elas.

    este arquivo          ->  calcula o quanto o alvo esta fora do centro e corrige
                              o angulo proporcionalmente a esse erro. Controlador
                              proporcional, o P do PID. O servo persegue o alvo.

O modelo e um parametro, de proposito. Para calibrar o ganho sem acender fogo
nenhuma vez, use o yolov8n.pt, que reconhece garrafa, celular, pessoa e mais 77
coisas do dia a dia:

    .\\venv\\Scripts\\python.exe sistema_rastreio.py 172.20.10.8 --porta COM8 ^
        --modelo yolov8n.pt --classe bottle

Depois de calibrado, o mesmo comando com o modelo do projeto:

    .\\venv\\Scripts\\python.exe sistema_rastreio.py 172.20.10.8 --porta COM8

SINAL DOS GANHOS, deduzido do comportamento ja validado na bancada:
  alvo a ESQUERDA da imagem -> o pan precisa SUBIR   (L leva o pan para 150)
  alvo a DIREITA  da imagem -> o pan precisa DESCER  (R leva o pan para 30)
  alvo ACIMA      na imagem -> o tilt precisa DESCER (U leva o tilt para 50,
                               porque o servo esta montado espelhado no suporte)
Se na pratica a torre FUGIR do alvo em vez de segui-lo, inverta com --inverter-pan
ou --inverter-tilt, sem mexer no codigo.

Teclas na janela: Q sai, S salva o quadro, X apaga o LED, C centraliza a torre.
"""

import argparse
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
ap.add_argument("--webcam", type=int, default=None,
                help="usa webcam USB em vez da ESP, ex --webcam 0. Da mais quadros por segundo")
ap.add_argument("--modelo", default="modelos/best_dfire.pt", help="caminho do .pt")
ap.add_argument("--classe", default="Fire",
                help="nome da classe a perseguir, ex Fire, bottle, person")
ap.add_argument("--conf", type=float, default=0.45, help="confianca minima")
ap.add_argument("--imgsz", type=int, default=416, help="resolucao da inferencia")

ap.add_argument("--ganho-pan", type=float, default=45.0,
                help="graus de correcao por unidade de erro no eixo horizontal")
ap.add_argument("--ganho-tilt", type=float, default=35.0,
                help="graus de correcao por unidade de erro no eixo vertical")
ap.add_argument("--zona-morta", type=float, default=0.06,
                help="fracao do quadro em volta do centro onde nao corrige nada")
ap.add_argument("--passo-max", type=float, default=8.0,
                help="limite de graus por correcao, evita solavanco")
ap.add_argument("--inverter-pan", action="store_true", help="inverte o sentido do pan")
ap.add_argument("--inverter-tilt", action="store_true", help="inverte o sentido do tilt")

ap.add_argument("--frames", type=int, default=3, help="quadros seguidos para confirmar o disparo")
ap.add_argument("--tempo-morto", type=float, default=8.0, help="segundos ignorando apos disparar")
ap.add_argument("--timeout", type=float, default=5.0, help="timeout HTTP em segundos")
args = ap.parse_args()

# limites fisicos do suporte, iguais aos do sketch do Uno
PAN_MIN, PAN_MAX = 10, 170
TILT_MIN, TILT_MAX = 40, 140
PAN_CENTRO, TILT_MEIO = 90, 90

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
    print("Sem --porta: rodando so na tela, sem mover a torre.")

ang_pan = float(PAN_CENTRO)
ang_tilt = float(TILT_MEIO)
ultimo_enviado = (None, None)


def enviar_angulos(pan, tilt):
    """Manda o comando de angulo absoluto. So envia se mudou pelo menos 1 grau."""
    global ultimo_enviado
    p, t = int(round(pan)), int(round(tilt))
    if (p, t) == ultimo_enviado:
        return
    ultimo_enviado = (p, t)
    if arduino:
        arduino.write(f"A{p} {t}\n".encode())


def enviar_letra(letra):
    if arduino:
        arduino.write(letra.encode())


# ---------------------------------------------------------------- captura
webcam = None
if args.webcam is not None:
    webcam = cv2.VideoCapture(args.webcam, cv2.CAP_DSHOW)
    if not webcam.isOpened():
        raise SystemExit(f"Nao consegui abrir a webcam {args.webcam}")


def proximo_quadro():
    """Devolve (quadro, bytes_originais) ou (None, None) em caso de falha."""
    if webcam is not None:
        ok, quadro = webcam.read()
        return (quadro, None) if ok else (None, None)
    with urllib.request.urlopen(URL, timeout=args.timeout) as resp:
        dados = resp.read()
    quadro = cv2.imdecode(np.frombuffer(dados, dtype=np.uint8), cv2.IMREAD_COLOR)
    return quadro, dados


# ---------------------------------------------------------------- modelo
modelo = YOLO(args.modelo)
print(f"Modelo:  {args.modelo}")
print(f"Classes: {modelo.names}")
print(f"Perseguindo a classe: {args.classe}")
print(f"Fonte:   {'webcam ' + str(args.webcam) if webcam is not None else URL}")
print(f"Ganhos:  pan {args.ganho_pan}  tilt {args.ganho_tilt}  "
      f"zona morta {args.zona_morta}")
print("Q sai, S salva o quadro, X apaga o LED, C centraliza.\n")

sinal_pan = -1.0 if not args.inverter_pan else 1.0
sinal_tilt = 1.0 if not args.inverter_tilt else -1.0

contador = 0
fim_tempo_morto = 0.0
falhas_seguidas = 0
enviar_angulos(ang_pan, ang_tilt)

while True:
    # ------------------------------------------------------- captura
    try:
        quadro, dados = proximo_quadro()
        falhas_seguidas = 0
    except Exception as erro:
        falhas_seguidas += 1
        print(f"falha ao capturar ({falhas_seguidas}x): {erro}")
        if falhas_seguidas >= 5:
            print("\nA camera nao respondeu 5 vezes seguidas.")
            print("Causas comuns, nesta ordem:")
            print("  1. tem uma aba do navegador aberta no IP da camera, feche ela")
            print("  2. o PC saiu da rede da ESP e voltou pra outra")
            print("  3. a placa travou, aperte RST na base e espere 15 segundos")
            break
        time.sleep(1)
        continue

    if quadro is None:
        continue

    altura, largura = quadro.shape[:2]
    em_tempo_morto = time.time() < fim_tempo_morto

    # ------------------------------------------------------- deteccao
    resultado = modelo(quadro, conf=args.conf, imgsz=args.imgsz, verbose=False)[0]

    melhor = None
    for caixa in resultado.boxes:
        # filtra pelo NOME da classe, nunca pelo indice: os modelos do projeto
        # tem a ordem trocada (antigo 0=Fire, novo 0=Smoke)
        if modelo.names[int(caixa.cls[0])] != args.classe:
            continue
        confianca = float(caixa.conf[0])
        if melhor is None or confianca > melhor[0]:
            melhor = (confianca, caixa.xyxy[0].tolist())

    erro_x = erro_y = 0.0

    # ------------------------------------------------------- controle
    if melhor and not em_tempo_morto:
        confianca, (x1, y1, x2, y2) = melhor
        x_centro = ((x1 + x2) / 2) / largura
        y_centro = ((y1 + y2) / 2) / altura

        erro_x = x_centro - 0.5   # negativo = alvo a esquerda da imagem
        erro_y = y_centro - 0.5   # negativo = alvo acima do centro

        # zona morta: se ja esta mirado, nao corrige. Evita o servo tremendo.
        if abs(erro_x) > args.zona_morta:
            passo = sinal_pan * erro_x * args.ganho_pan
            passo = max(-args.passo_max, min(args.passo_max, passo))
            ang_pan = max(PAN_MIN, min(PAN_MAX, ang_pan + passo))

        if abs(erro_y) > args.zona_morta:
            passo = sinal_tilt * erro_y * args.ganho_tilt
            passo = max(-args.passo_max, min(args.passo_max, passo))
            ang_tilt = max(TILT_MIN, min(TILT_MAX, ang_tilt + passo))

        enviar_angulos(ang_pan, ang_tilt)

        # ---------------------------------------------------- disparo
        mirado = abs(erro_x) <= args.zona_morta and abs(erro_y) <= args.zona_morta
        contador = contador + 1 if mirado else 0

        if contador >= args.frames:
            enviar_letra("F")
            fim_tempo_morto = time.time() + args.tempo_morto
            contador = 0
            print(f"DISPARO com o alvo centrado, conf {confianca:.2f}, "
                  f"pan {ang_pan:.0f} tilt {ang_tilt:.0f}")
    else:
        contador = 0

    # ------------------------------------------------------- tela
    anotado = resultado.plot()

    # mira no centro do quadro, ajuda muito a enxergar o erro durante a calibragem
    cx, cy = largura // 2, altura // 2
    cv2.line(anotado, (cx - 12, cy), (cx + 12, cy), (255, 255, 255), 1)
    cv2.line(anotado, (cx, cy - 12), (cx, cy + 12), (255, 255, 255), 1)
    raio = int(min(largura, altura) * args.zona_morta)
    cv2.circle(anotado, (cx, cy), raio, (180, 180, 180), 1)

    if em_tempo_morto:
        restante = fim_tempo_morto - time.time()
        cv2.putText(anotado, f"EJETANDO ({restante:.0f}s)", (10, 24),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
    elif melhor:
        cv2.putText(anotado, "RASTREANDO", (10, 24),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
    else:
        cv2.putText(anotado, "procurando", (10, 24),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 200, 0), 2)

    rodape = (f"pan {ang_pan:5.1f}  tilt {ang_tilt:5.1f}   "
              f"erro x {erro_x:+.2f} y {erro_y:+.2f}")
    cv2.putText(anotado, rodape, (10, altura - 12),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)

    cv2.imshow("Rastreamento continuo - KGB", anotado)

    tecla = cv2.waitKey(1) & 0xFF
    if tecla == ord("q"):
        break
    if tecla == ord("s") and dados is not None:
        nome = time.strftime("amostras/rastreio_%Y%m%d_%H%M%S.jpg")
        with open(nome, "wb") as arquivo:
            arquivo.write(dados)
        print("quadro salvo em", nome)
    if tecla == ord("x"):
        enviar_letra("X")
        fim_tempo_morto = 0.0
    if tecla == ord("c"):
        ang_pan, ang_tilt = float(PAN_CENTRO), float(TILT_MEIO)
        enviar_angulos(ang_pan, ang_tilt)
        print("torre centralizada")

if webcam is not None:
    webcam.release()
cv2.destroyAllWindows()
print("Fim.")
