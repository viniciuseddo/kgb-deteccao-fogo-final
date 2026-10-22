"""
Monta um video a partir das imagens coletadas pela ESP32-CAM.

Serve so pra mostrar o resultado pra alguem. O material que vale pro treino
sao os JPEGs originais, nao este video, que passa por compressao de novo.

Uso:
    .\\venv\\Scripts\\python.exe montar_video.py dataset\\fogo --fps 8
"""

import argparse
import os

import cv2

ap = argparse.ArgumentParser()
ap.add_argument("pasta", help="pasta com os .jpg, ex dataset\\fogo")
ap.add_argument("--saida", default=None, help="nome do arquivo .mp4 de saida")
ap.add_argument("--fps", type=int, default=8, help="quadros por segundo do video")
args = ap.parse_args()

arquivos = sorted(n for n in os.listdir(args.pasta) if n.lower().endswith(".jpg"))
if not arquivos:
    raise SystemExit(f"Nenhum .jpg encontrado em {args.pasta}")

primeiro = cv2.imread(os.path.join(args.pasta, arquivos[0]))
altura, largura = primeiro.shape[:2]

saida = args.saida or os.path.basename(os.path.normpath(args.pasta)) + ".mp4"
escritor = cv2.VideoWriter(saida, cv2.VideoWriter_fourcc(*"mp4v"),
                           args.fps, (largura, altura))

for nome in arquivos:
    quadro = cv2.imread(os.path.join(args.pasta, nome))
    if quadro is None:
        continue
    if quadro.shape[:2] != (altura, largura):
        quadro = cv2.resize(quadro, (largura, altura))
    escritor.write(quadro)

escritor.release()
print(f"{len(arquivos)} imagens em {saida}, {largura}x{altura} a {args.fps} fps")
