"""
Grava tomadas curtas com a ESP32-CAM, para o fine tuning do modelo.

Cada tomada dura um tempo fixo (10 segundos por padrao) e gera duas coisas:

    tomadas/tomada_01/*.jpg   os quadros originais, do jeito que a placa mandou
    tomadas/tomada_01.mp4     o video da tomada, so para assistir

Os JPEGs sao o que vale para o treino. O mp4 e para o Guilherme ver.

DOIS MODOS
----------

Manual, o padrao. Uma tomada por vez, voce aperta ESPACO a cada uma:

    .\\venv\\Scripts\\python.exe gravar_tomadas.py 172.20.10.8

Continuo, para gravar muito material sem tocar no teclado. Voce aperta ESPACO
uma vez, ele grava sem parar e vai fatiando em tomadas de 10 segundos sozinho,
ate voce apertar ESPACO de novo:

    .\\venv\\Scripts\\python.exe gravar_tomadas.py 172.20.10.8 --continuo

No modo continuo, aponte a camera e va MOVENDO devagar em volta da chama,
mudando distancia, altura e angulo. O que vale para o treino e variedade, nao
contagem: cem tomadas do mesmo angulo valem o mesmo que uma.

Teclas na janela:
    ESPACO  comeca e para a gravacao
    Q       sai
"""

import argparse
import os
import time
import urllib.request

import cv2
import numpy as np

ap = argparse.ArgumentParser()
ap.add_argument("ip", help="IP da ESP32-CAM, ex 172.20.10.8")
ap.add_argument("--segundos", type=float, default=10.0, help="duracao de cada tomada")
ap.add_argument("--tomadas", type=int, default=8,
                help="meta de tomadas, so para a contagem na tela. Nao impede gravar mais")
ap.add_argument("--continuo", action="store_true",
                help="grava sem parar, fatiando em tomadas sozinho, ate apertar ESPACO de novo")
ap.add_argument("--pular", type=int, default=1,
                help="guarda 1 a cada N quadros. 1 guarda todos. Use 2 ou 3 para "
                     "reduzir quadros quase identicos e aliviar a rotulagem")
ap.add_argument("--pasta", default="tomadas", help="pasta de saida")
ap.add_argument("--timeout", type=float, default=5.0, help="timeout HTTP em segundos")
args = ap.parse_args()

URL = f"http://{args.ip}/capture"
os.makedirs(args.pasta, exist_ok=True)

# continua a numeracao se ja existirem tomadas na pasta
existentes = [n for n in os.listdir(args.pasta)
              if n.startswith("tomada_") and n.endswith(".mp4")]
numero = len(existentes) + 1

print(f"Camera:  {URL}")
print(f"Destino: {os.path.abspath(args.pasta)}")
print(f"Modo:    {'CONTINUO' if args.continuo else 'manual'}, "
      f"tomadas de {args.segundos:.0f}s")
if args.pular > 1:
    print(f"Guardando 1 a cada {args.pular} quadros.")
if numero > 1:
    print(f"Ja existem {numero - 1} tomadas aqui, a proxima sera a {numero}.")
print("\nESPACO comeca e para, Q sai.\n")

gravando = False
inicio_tomada = 0.0
buffer_jpg = []
falhas_seguidas = 0
contador_quadros = 0
total_salvos = 0


def salvar_tomada(indice, quadros, duracao):
    """Escreve os JPEGs originais e monta o mp4 da tomada."""
    if not quadros:
        return False

    destino = os.path.join(args.pasta, f"tomada_{indice:02d}")
    os.makedirs(destino, exist_ok=True)

    for posicao, dados in enumerate(quadros, start=1):
        with open(os.path.join(destino, f"{posicao:04d}.jpg"), "wb") as arquivo:
            arquivo.write(dados)

    primeiro = cv2.imdecode(np.frombuffer(quadros[0], dtype=np.uint8), cv2.IMREAD_COLOR)
    if primeiro is None:
        print(f"Tomada {indice:02d}: quadros invalidos, video nao gerado")
        return True

    altura, largura = primeiro.shape[:2]
    fps = max(1.0, len(quadros) / max(duracao, 0.001))

    caminho_video = os.path.join(args.pasta, f"tomada_{indice:02d}.mp4")
    escritor = cv2.VideoWriter(caminho_video, cv2.VideoWriter_fourcc(*"mp4v"),
                               fps, (largura, altura))
    for dados in quadros:
        quadro = cv2.imdecode(np.frombuffer(dados, dtype=np.uint8), cv2.IMREAD_COLOR)
        if quadro is not None:
            escritor.write(quadro)
    escritor.release()

    print(f"Tomada {indice:02d}: {len(quadros)} quadros em {duracao:.1f}s "
          f"({fps:.1f} fps), {largura}x{altura}")
    return True


while True:
    # ------------------------------------------------------- captura
    try:
        with urllib.request.urlopen(URL, timeout=args.timeout) as resposta:
            dados = resposta.read()
        falhas_seguidas = 0
    except Exception as erro:
        falhas_seguidas += 1
        print(f"falha ao capturar ({falhas_seguidas}x): {erro}")
        if falhas_seguidas >= 5:
            print("\nESP32-CAM nao respondeu 5 vezes seguidas.")
            print("Causas comuns, nesta ordem:")
            print("  1. tem uma aba do navegador aberta no IP da camera, feche ela")
            print("  2. o PC saiu da rede da ESP e voltou pra outra")
            print("  3. a placa travou, aperte RST na base e espere 15 segundos")
            break
        time.sleep(1)
        continue

    quadro = cv2.imdecode(np.frombuffer(dados, dtype=np.uint8), cv2.IMREAD_COLOR)
    if quadro is None:
        continue

    # ------------------------------------------------------- gravacao
    if gravando:
        contador_quadros += 1
        if contador_quadros % args.pular == 0:
            buffer_jpg.append(dados)

        decorrido = time.time() - inicio_tomada
        if decorrido >= args.segundos:
            if salvar_tomada(numero, buffer_jpg, decorrido):
                total_salvos += len(buffer_jpg)
                numero += 1
            buffer_jpg = []

            if args.continuo:
                # emenda direto na proxima tomada, sem parar
                inicio_tomada = time.time()
            else:
                gravando = False
                if numero > args.tomadas:
                    print("Meta atingida. ESPACO grava mais, Q sai.")

    # ------------------------------------------------------- tela
    tela = quadro.copy()
    altura_tela, largura_tela = tela.shape[:2]

    if gravando:
        restante = args.segundos - (time.time() - inicio_tomada)
        rotulo = f"{'CONT ' if args.continuo else ''}TOMADA {numero}  {restante:4.1f}s"
        cv2.putText(tela, rotulo, (10, 24),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
        cv2.circle(tela, (largura_tela - 20, 20), 7, (0, 0, 255), -1)
        proporcao = 1.0 - (restante / args.segundos)
        cv2.rectangle(tela, (0, altura_tela - 5),
                      (int(largura_tela * proporcao), altura_tela), (0, 0, 255), -1)
    else:
        cv2.putText(tela, f"ESPACO = tomada {numero}", (10, 24),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 200, 0), 2)

    rodape = f"{numero - 1} tomadas   {total_salvos} quadros"
    cv2.putText(tela, rodape, (10, altura_tela - 12),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

    cv2.imshow("Gravacao de tomadas - KGB", tela)

    tecla = cv2.waitKey(1) & 0xFF
    if tecla == ord("q"):
        break

    if tecla == ord(" "):
        if not gravando:
            gravando = True
            inicio_tomada = time.time()
            buffer_jpg = []
            contador_quadros = 0
            print(f"Gravando a partir da tomada {numero}"
                  f"{' em modo continuo' if args.continuo else ''}...")
        else:
            # parada manual: salva o pedaco que estiver no buffer
            decorrido = time.time() - inicio_tomada
            if salvar_tomada(numero, buffer_jpg, decorrido):
                total_salvos += len(buffer_jpg)
                numero += 1
            buffer_jpg = []
            gravando = False
            print("Parado.")

# se sair com Q no meio de uma tomada, nao perde o que ja capturou
if gravando and buffer_jpg:
    decorrido = time.time() - inicio_tomada
    if salvar_tomada(numero, buffer_jpg, decorrido):
        total_salvos += len(buffer_jpg)
        numero += 1

cv2.destroyAllWindows()
print(f"\nFim. {numero - 1} tomadas e {total_salvos} quadros "
      f"em {os.path.abspath(args.pasta)}")
