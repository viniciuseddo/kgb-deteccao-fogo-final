"""
Monta o pacote completo pro Guilherme, na Area de Trabalho.

Junta dois conjuntos que vieram de cameras diferentes, e os mantem
SEPARADOS dentro do zip de proposito, porque tem resolucao e otica
diferentes e o Guilherme precisa saber disso antes de misturar:

    amostras_640x480/          capturas de 19/08, 640x480
    espcam_320x240/tomada_NN/  capturas novas da ESP32-CAM, 320x240
    LEIAME.txt                 ficha tecnica dos dois conjuntos

Uso:
    .\\venv\\Scripts\\python.exe pacote_gui.py

Ou escolhendo outra faixa de tomadas:
    .\\venv\\Scripts\\python.exe pacote_gui.py --de 1 --ate 49
"""

import argparse
import os
import zipfile
from datetime import datetime

ap = argparse.ArgumentParser()
ap.add_argument("--de", type=int, default=6, help="primeira tomada da ESP32-CAM")
ap.add_argument("--ate", type=int, default=9999, help="ultima tomada da ESP32-CAM")
ap.add_argument("--amostras", default="amostras", help="pasta das capturas antigas")
ap.add_argument("--tomadas", default="tomadas", help="pasta das tomadas novas")
ap.add_argument("--destino", default=None,
                help="onde salvar o zip. Sem isso, vai pra Area de Trabalho")
ap.add_argument("--com-video", action="store_true",
                help="inclui tambem os mp4 das tomadas")
args = ap.parse_args()


def area_de_trabalho():
    """Pergunta ao WINDOWS onde fica a Area de Trabalho, em vez de adivinhar.

    Adivinhar o nome da pasta nao funciona: com OneDrive e Windows em
    portugues ela vira "Area de Trabalho", com acento, e o caminho muda de
    maquina pra maquina. O registro do Windows sempre tem o caminho certo.
    """
    try:
        import winreg
        chave = r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, chave) as k:
            caminho = winreg.QueryValueEx(k, "Desktop")[0]
        caminho = os.path.expandvars(caminho)
        if os.path.isdir(caminho):
            return caminho
    except Exception:
        pass

    # fora do Windows, ou se o registro falhar
    casa = os.path.expanduser("~")
    for nome in ("Desktop", "\u00c1rea de Trabalho", "Area de Trabalho"):
        for base in (casa, os.path.join(casa, "OneDrive")):
            c = os.path.join(base, nome)
            if os.path.isdir(c):
                return c
    return casa


destino = args.destino or area_de_trabalho()
carimbo = datetime.now().strftime("%Y%m%d")
saida = os.path.join(destino, f"kgb_dataset_fogo_{carimbo}.zip")

# ------------------------------------------------- conjunto 1, as amostras
amostras = []
if os.path.isdir(args.amostras):
    amostras = sorted(n for n in os.listdir(args.amostras)
                      if n.lower().endswith((".jpg", ".jpeg")))

# ------------------------------------------------- conjunto 2, as tomadas
tomadas = []
if os.path.isdir(args.tomadas):
    for nome in sorted(os.listdir(args.tomadas)):
        caminho = os.path.join(args.tomadas, nome)
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

if not amostras and not tomadas:
    raise SystemExit("Nao achei imagem nenhuma nas duas pastas.")

quadros_tomadas = sum(len(j) for _, _, _, j in tomadas)
faixa = (f"{tomadas[0][0]:02d} a {tomadas[-1][0]:02d}") if tomadas else "nenhuma"

print(f"amostras 640x480 : {len(amostras)} imagens")
print(f"ESP32-CAM 320x240: {len(tomadas)} tomadas, {quadros_tomadas} imagens "
      f"(tomadas {faixa})")
print(f"Destino          : {saida}\n")

# ------------------------------------------------------------------ leiame
leiame = f"""DATASET DE FOGO - PROJETO DE DETECCAO (KGB / Sompo)
Gerado em {datetime.now().strftime('%d/%m/%Y %H:%M')}

SAO DOIS CONJUNTOS, DE CAMERAS DIFERENTES.
Deixei separados de proposito. Nao misture sem saber disso.


1) amostras_640x480/          {len(amostras)} imagens
---------------------------------------------------------------
  Capturas de 19/08, em 640x480, com lente grande angular.

  O conteudo NAO e so fogo, e isso e intencional. Tem tres tipos:

    a) fogo de verdade: chama de isqueiro de perto, papel queimando
    b) fumaca
    c) NEGATIVOS DIFICEIS: luz forte de painel, tela de monitor,
       lanterna de celular, e uma estampa de fogo desenhada em um pano

  Os negativos do item (c) sao os mais valiosos do lote. Sao
  exatamente os casos que fazem o modelo confundir luz com chama.
  Nao descarte achando que e lixo de captura.


2) espcam_320x240/            {len(tomadas)} tomadas, {quadros_tomadas} imagens
---------------------------------------------------------------
  Capturas novas, feitas com a camera que vai rodar na demo.

  Placa      ESP32-CAM (AI Thinker)
  Sensor     GC2145, modulo de flat preto (RHYX M21-45)
  Resolucao  320x240 (QVGA)
  Taxa real  cerca de 2 quadros por segundo

  Uma pasta por tomada, cada tomada com ate 10 segundos de captura.

  SOBRE A QUALIDADE, PRA NAO PARECER DESCUIDO:
  O GC2145 nao tem compressor JPEG por hardware. O sensor entrega
  RGB565 e o proprio ESP32 converte pra JPEG por software. Dai vem a
  taxa baixa de quadros e a imagem mais crua, com ruido e cor pouco
  saturada. O sensor certo seria o OV2640, que comprime sozinho, e a
  troca ficou pra depois da entrega de proposito: trocar agora faria o
  modelo treinar com uma imagem diferente da que ele vai ver na demo.


O QUE NAO FOI FEITO, NOS DOIS CONJUNTOS
---------------------------------------------------------------
  Nenhum tratamento. Sem redimensionar, sem ajustar brilho, contraste,
  saturacao ou nitidez. Os bytes sao os que sairam da camera.

  Nenhuma rotulagem automatica. Nao rodei o best_dfire.pt em cima de
  nada disso. A rotulagem fica inteira com voce e com o Lucas, como
  combinado.


SUGESTAO
---------------------------------------------------------------
  Quadros vizinhos da mesma tomada sao parecidos. Se quiser aliviar a
  rotulagem, pega 1 a cada 2 ou 3 de cada pasta. Preferi mandar tudo e
  deixar essa escolha com voce.
"""

# --------------------------------------------------------------------- zip
os.makedirs(destino, exist_ok=True)
with zipfile.ZipFile(saida, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
    z.writestr("LEIAME.txt", leiame)

    for i, arquivo in enumerate(amostras, start=1):
        z.write(os.path.join(args.amostras, arquivo), f"amostras_640x480/{arquivo}")
        if i % 200 == 0:
            print(f"  amostras: {i}/{len(amostras)}")
    if amostras:
        print(f"  amostras: {len(amostras)}/{len(amostras)}")

    for numero, nome, caminho, jpgs in tomadas:
        for arquivo in jpgs:
            z.write(os.path.join(caminho, arquivo),
                    f"espcam_320x240/{nome}/{arquivo}")
        if args.com_video:
            video = os.path.join(args.tomadas, f"{nome}.mp4")
            if os.path.isfile(video):
                z.write(video, f"espcam_320x240/{nome}.mp4")
    if tomadas:
        print(f"  tomadas: {len(tomadas)} pastas, {quadros_tomadas} imagens")

tamanho = os.path.getsize(saida) / (1024 * 1024)

print()
print("-" * 60)
print(f"PRONTO: {saida}")
print(f"{len(amostras) + quadros_tomadas} imagens no total, {tamanho:.1f} MB")
print("-" * 60)
if tamanho > 60:
    print("\nPassa de 60MB. Manda por Google Drive ou WeTransfer, nao por WhatsApp.")
