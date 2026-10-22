"""
Coleta de imagens da ESP32-CAM para o dataset de fine tuning.

Puxa quadros do endpoint /capture e salva o JPEG exatamente como a placa
mandou, sem reprocessar nada. Isso e de proposito: o modelo vai ser
retreinado com a mesma camera, a mesma lente e a mesma qualidade de imagem
que ele vai encontrar rodando de verdade.

Uso tipico:

    .\\venv\\Scripts\\python.exe coletar_dataset.py 172.20.10.8 --classe fogo
    .\\venv\\Scripts\\python.exe coletar_dataset.py 172.20.10.8 --classe sem_fogo

As imagens vao para dataset/<classe>/.

Teclas na janela:
    ESPACO  liga e desliga a gravacao
    S       salva um quadro avulso, mesmo com a gravacao desligada
    Q       sai
"""

import argparse
import os
import time
import urllib.request
from datetime import datetime

import cv2
import numpy as np

ap = argparse.ArgumentParser()
ap.add_argument("ip", help="IP da ESP32-CAM, ex 172.20.10.8")
ap.add_argument("--classe", default="fogo",
                help="nome da pasta e prefixo dos arquivos, ex fogo ou sem_fogo")
ap.add_argument("--pasta", default="dataset", help="pasta raiz do dataset")
ap.add_argument("--intervalo", type=float, default=0.4,
                help="segundos entre um quadro salvo e o proximo")
ap.add_argument("--timeout", type=float, default=5.0, help="timeout HTTP em segundos")
args = ap.parse_args()

URL = f"http://{args.ip}/capture"
DESTINO = os.path.join(args.pasta, args.classe)
os.makedirs(DESTINO, exist_ok=True)

# quantos arquivos dessa classe ja existem, pra nao sobrescrever coleta anterior
salvos = len([n for n in os.listdir(DESTINO) if n.lower().endswith(".jpg")])

print(f"Camera:  {URL}")
print(f"Destino: {os.path.abspath(DESTINO)}")
print(f"Ja existem {salvos} imagens nessa pasta.")
print("ESPACO liga e desliga a gravacao, S salva um quadro, Q sai.")

gravando = False
proximo_salvamento = 0.0
falhas_seguidas = 0


def gravar_arquivo(dados):
    """Escreve os bytes do JPEG como vieram da placa."""
    global salvos
    carimbo = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
    caminho = os.path.join(DESTINO, f"{args.classe}_{carimbo}.jpg")
    with open(caminho, "wb") as arquivo:
        arquivo.write(dados)
    salvos += 1


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
            print("  2. o PC saiu do roteamento do celular e voltou pra outra rede")
            print("  3. a placa travou, aperte RST na base e espere 15 segundos")
            break
        time.sleep(1)
        continue

    quadro = cv2.imdecode(np.frombuffer(dados, dtype=np.uint8), cv2.IMREAD_COLOR)
    if quadro is None:
        print("imagem invalida, pulando quadro")
        continue

    # ------------------------------------------------------- gravacao
    agora = time.time()
    if gravando and agora >= proximo_salvamento:
        gravar_arquivo(dados)
        proximo_salvamento = agora + args.intervalo

    # ------------------------------------------------------- tela
    tela = quadro.copy()
    altura = tela.shape[0]

    if gravando:
        cv2.putText(tela, "GRAVANDO", (10, 24),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
        cv2.circle(tela, (tela.shape[1] - 20, 20), 7, (0, 0, 255), -1)
    else:
        cv2.putText(tela, "pausado", (10, 24),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 200, 0), 2)

    cv2.putText(tela, f"{args.classe}: {salvos} imagens", (10, altura - 12),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

    cv2.imshow("Coleta para o dataset - KGB", tela)

    tecla = cv2.waitKey(1) & 0xFF
    if tecla == ord("q"):
        break
    if tecla == ord(" "):
        gravando = not gravando
        proximo_salvamento = 0.0
        print("gravando" if gravando else "pausado")
    if tecla == ord("s"):
        gravar_arquivo(dados)
        print(f"quadro salvo ({salvos})")

cv2.destroyAllWindows()
print(f"\nFim. {salvos} imagens em {os.path.abspath(DESTINO)}")
