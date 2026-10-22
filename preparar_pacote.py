"""
Monta o pacote de imagens pra mandar pro Guilherme.

Escolhe uma faixa de tomadas, junta os JPEGs originais e os mp4s em um zip,
e escreve dentro dele um LEIAME com a ficha tecnica da captura.

Uso tipico, mandando so as tomadas novas:

    .\\venv\\Scripts\\python.exe preparar_pacote.py --de 6 --ate 49

Sem --de e --ate ele pega tudo que existir.

O zip sai na propria pasta do projeto, com a data no nome.
"""

import argparse
import os
import zipfile
from datetime import datetime

ap = argparse.ArgumentParser()
ap.add_argument("--de", type=int, default=1, help="primeira tomada a incluir")
ap.add_argument("--ate", type=int, default=9999, help="ultima tomada a incluir")
ap.add_argument("--pasta", default="tomadas", help="pasta das tomadas")
ap.add_argument("--saida", default=None, help="nome do zip. Sem isso ele inventa um")
ap.add_argument("--sem-video", action="store_true",
                help="nao inclui os mp4, so os JPEGs. Deixa o zip bem menor")
args = ap.parse_args()

if not os.path.isdir(args.pasta):
    raise SystemExit(f"Nao achei a pasta {args.pasta}")

# ------------------------------------------------------------ levantamento
tomadas = []
for nome in sorted(os.listdir(args.pasta)):
    caminho = os.path.join(args.pasta, nome)
    if not os.path.isdir(caminho) or not nome.startswith("tomada_"):
        continue
    try:
        numero = int(nome.split("_")[1])
    except (IndexError, ValueError):
        continue
    if not (args.de <= numero <= args.ate):
        continue
    jpgs = sorted(n for n in os.listdir(caminho) if n.lower().endswith(".jpg"))
    if jpgs:
        tomadas.append((numero, nome, caminho, jpgs))

if not tomadas:
    raise SystemExit(f"Nenhuma tomada entre {args.de} e {args.ate} com imagens dentro.")

total_quadros = sum(len(j) for _, _, _, j in tomadas)
primeira, ultima = tomadas[0][0], tomadas[-1][0]

carimbo = datetime.now().strftime("%Y%m%d")
saida = args.saida or f"kgb_fogo_tomadas_{primeira:02d}a{ultima:02d}_{carimbo}.zip"

# ------------------------------------------------------------ leiame
leiame = f"""MATERIAL DE CAPTURA - PROJETO DETECCAO DE FOGO (KGB / Sompo)
Gerado em {datetime.now().strftime('%d/%m/%Y %H:%M')}

CONTEUDO
  Tomadas {primeira:02d} a {ultima:02d}
  {len(tomadas)} tomadas, {total_quadros} imagens

  tomada_NN/*.jpg   os quadros, do jeito que a placa mandou
  tomada_NN.mp4     o video da tomada, so pra assistir

  O QUE VALE PRO TREINO SAO OS JPEGs. O mp4 passa por compressao de novo
  e serve so pra voce ver rapidamente o que tem em cada tomada.

FICHA TECNICA DA CAPTURA
  Placa      ESP32-CAM (AI Thinker)
  Sensor     GC2145, modulo de flat preto (RHYX M21-45)
  Resolucao  320x240 (QVGA)
  Formato    JPEG, gerado por software
  Taxa real  cerca de 2 quadros por segundo
  Transporte HTTP pelo endpoint /capture, por Wi-Fi

SOBRE A QUALIDADE, PRA NAO PARECER DESCUIDO
  O GC2145 nao tem compressor JPEG por hardware. O sensor entrega RGB565
  e o proprio ESP32 converte pra JPEG por software. Isso explica as duas
  coisas que voce vai notar:

    1. a taxa baixa de quadros, cerca de 2 por segundo
    2. a imagem mais crua, com ruido e cor pouco saturada

  O sensor certo pra isso seria o OV2640, que comprime sozinho. A placa
  chegou com o GC2145 e a troca ficou pra depois da entrega, de proposito:
  trocar o sensor agora faria o modelo ser treinado com uma imagem
  diferente da que ele vai encontrar na demo.

O QUE NAO FOI FEITO, DE PROPOSITO
  Nenhum tratamento: sem redimensionar, sem ajustar brilho, contraste,
  saturacao ou nitidez. Os bytes sao exatamente os que sairam da placa.
  A ideia e que o modelo aprenda com a mesma imagem ruim que ele vai ver
  rodando de verdade.

  Nenhuma rotulagem automatica. Nao rodei o best_dfire.pt em cima desse
  material. A rotulagem fica inteira com voce e com o Lucas, como
  combinado.

SUGESTAO DE USO
  Quadros vizinhos da mesma tomada sao parecidos. Se quiser aliviar a
  rotulagem, pega 1 a cada 2 ou 3 de cada pasta. Preferi mandar tudo e
  deixar essa escolha com voce.
"""

# ------------------------------------------------------------ zip
print(f"Montando {saida} ...")
with zipfile.ZipFile(saida, "w", zipfile.ZIP_DEFLATED) as z:
    z.writestr("LEIAME.txt", leiame)
    for numero, nome, caminho, jpgs in tomadas:
        for arquivo in jpgs:
            z.write(os.path.join(caminho, arquivo), f"{nome}/{arquivo}")
        video = os.path.join(args.pasta, f"{nome}.mp4")
        if not args.sem_video and os.path.isfile(video):
            z.write(video, f"{nome}.mp4")
        print(f"  {nome}: {len(jpgs)} imagens")

tamanho = os.path.getsize(saida) / (1024 * 1024)

print()
print("-" * 52)
print(f"Pacote pronto: {os.path.abspath(saida)}")
print(f"Tomadas {primeira:02d} a {ultima:02d}   "
      f"{len(tomadas)} tomadas   {total_quadros} imagens   {tamanho:.1f} MB")
print("-" * 52)
