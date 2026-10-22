"""
Reprocessamento de material gravado - Vigia KGB
===============================================

A ESP32-CAM sofreu dano por agua durante os testes de campo e parou de
transmitir. Este script mantem o sistema operando a partir do material
ja gravado com essa mesma camera: os quadros passam pelo MESMO modelo,
com o MESMO limiar e a MESMA regra de confirmacao de tres quadros.

O que e real aqui:
    o modelo, o limiar, a confirmacao, a confianca de cada deteccao,
    o comando enviado ao ESP32-S3, o disparo da bomba e a linha gravada
    no banco. So a origem do quadro mudou: vem do arquivo em vez da
    serial.

COMO USAR

    Ver quais gravacoes tem chama, sem disparar nada:
        py reprocessar.py --listar

    Reprocessar uma gravacao, com disparo real no hardware:
        py reprocessar.py --video tomadas/tomada_17.mp4 --ip 192.168.0.17

    Reprocessar varias em sequencia:
        py reprocessar.py --pasta tomadas --ip 192.168.0.17

    Sem acionar o hardware (so banco e painel):
        py reprocessar.py --video tomadas/tomada_17.mp4 --sem-disparo

ATALHOS NA JANELA
    q ou ESC  encerra
    espaco    pula para a proxima gravacao
    p         pausa
"""

import argparse
import glob
import os
import sys
import time

import cv2

from banco import Banco
from sistema_vigia import BASE, MODELO_PADRAO, ControleS3, registrar_ocorrencia

try:
    from ultralytics import YOLO
except ImportError:
    print("Falta o ultralytics. Rode: pip install ultralytics")
    sys.exit(1)


# ------------------------------------------------------- varredura previa
def listar(modelo, caminhos, conf, imgsz):
    """Diz quantos quadros de cada gravacao tem chama, para voce escolher."""
    print("\nVarrendo as gravacoes. Isso nao dispara nada e nao grava nada.\n")
    print(f"{'gravacao':<22} {'quadros':>8} {'com chama':>11} {'%':>7} {'melhor':>8}")
    print("-" * 60)

    ranking = []
    for caminho in caminhos:
        cap = cv2.VideoCapture(caminho)
        n = achou = 0
        melhor = 0.0
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            n += 1
            r = modelo.predict(frame, conf=conf, imgsz=imgsz, verbose=False)[0]
            if len(r.boxes):
                achou += 1
                melhor = max(melhor, float(r.boxes.conf.max()))
        cap.release()
        pct = (100 * achou / n) if n else 0.0
        ranking.append((pct, melhor, caminho, n, achou))
        print(f"{os.path.basename(caminho):<22} {n:>8} {achou:>11} {pct:>6.1f}% {melhor:>7.0%}")

    ranking.sort(reverse=True)
    print("\nMelhores para usar na gravacao:")
    for pct, melhor, caminho, n, achou in ranking[:5]:
        if achou:
            print(f"  {os.path.basename(caminho)}  ({pct:.0f}% dos quadros, pico {melhor:.0%})")
    if not any(r[4] for r in ranking):
        print("  nenhuma gravacao teve deteccao com este limiar")
        print(f"  tente baixar o limiar: --conf {max(0.15, conf - 0.15):.2f}")


# ------------------------------------------------------------ reprocessar
def reprocessar(modelo, caminho, bd, s3, args, janela):
    cap = cv2.VideoCapture(caminho)
    if not cap.isOpened():
        print(f"nao consegui abrir {caminho}")
        return 0

    fps_video = cap.get(cv2.CAP_PROP_FPS) or 12.0
    espera = max(1, int(1000 / fps_video))
    nome_curto = os.path.basename(caminho)
    print(f"\n>> {nome_curto}")

    seguidos = 0
    ultimo = 0.0
    disparos = 0
    pausado = False

    while True:
        if not pausado:
            ok, frame = cap.read()
            if not ok:
                break

            r = modelo.predict(frame, conf=args.conf, imgsz=args.imgsz, verbose=False)[0]
            achou = len(r.boxes) > 0
            melhor = float(r.boxes.conf.max()) if achou else 0.0

            seguidos = seguidos + 1 if achou else 0
            confirmado = seguidos >= args.frames
            agora = time.time()
            anotado = r.plot()

            if confirmado and (agora - ultimo) > args.cooldown:
                ultimo = agora
                disparos += 1
                print(f"   FOGO CONFIRMADO ({melhor:.0%})")

                if s3 is not None:
                    s3.comando("F")
                    print("   comando F enviado ao ESP32-S3")

                imagem = time.strftime("disparos/fogo_%Y%m%d_%H%M%S.jpg")
                cv2.imwrite(os.path.join(BASE, imagem), anotado)
                registrar_ocorrencia(bd, s3, melhor, imagem, args.tempo_bomba)

            if confirmado:
                texto, cor = f"FOGO {melhor:.0%}", (0, 0, 255)
            elif achou:
                texto, cor = f"possivel {melhor:.0%} ({seguidos}/{args.frames})", (0, 165, 255)
            else:
                texto, cor = "analisando", (0, 200, 0)

            larg = anotado.shape[1]
            cv2.rectangle(anotado, (0, 0), (larg, 52), (25, 25, 25), -1)
            cv2.putText(anotado, texto, (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, cor, 2)

            origem = "ESP32-S3 ok" if (s3 and s3.online) else ("sem disparo" if s3 is None else "S3 sem resposta")
            info = f"{nome_curto}  |  conf {args.conf:.2f}  |  {origem}"
            escala = 0.45
            while escala > 0.28:
                (tw, _), _ = cv2.getTextSize(info, cv2.FONT_HERSHEY_SIMPLEX, escala, 1)
                if tw <= larg - 16:
                    break
                escala -= 0.03
            cv2.putText(anotado, info, (8, 43), cv2.FONT_HERSHEY_SIMPLEX, escala, (200, 200, 200), 1)

            cv2.imshow(janela, anotado)

        k = cv2.waitKey(espera) & 0xFF
        if k in (ord("q"), 27):
            cap.release()
            return -1
        if k == ord(" "):
            break
        if k == ord("p"):
            pausado = not pausado

    cap.release()
    return disparos


# ------------------------------------------------------------------- main
def main():
    p = argparse.ArgumentParser()
    p.add_argument("--video", default=None, help="uma gravacao especifica")
    p.add_argument("--pasta", default="tomadas", help="pasta com as gravacoes")
    p.add_argument("--ip", default=None, help="IP do ESP32-S3; sem ele nao dispara")
    p.add_argument("--sem-disparo", action="store_true", help="so banco e painel")
    p.add_argument("--listar", action="store_true", help="so varre e reporta, nao grava")
    p.add_argument("--modelo", default=MODELO_PADRAO)
    p.add_argument("--conf", type=float, default=0.45)
    p.add_argument("--imgsz", type=int, default=640)
    p.add_argument("--frames", type=int, default=3)
    p.add_argument("--cooldown", type=float, default=12.0)
    p.add_argument("--tempo-bomba", type=float, default=5.0)
    args = p.parse_args()

    print("=" * 66)
    print(" REPROCESSAMENTO DE MATERIAL GRAVADO - VIGIA KGB")
    print("=" * 66)

    if not os.path.exists(args.modelo):
        print(f"Modelo nao encontrado: {args.modelo}")
        sys.exit(1)

    if args.video:
        caminhos = [os.path.join(BASE, args.video) if not os.path.isabs(args.video) else args.video]
    else:
        pasta = args.pasta if os.path.isabs(args.pasta) else os.path.join(BASE, args.pasta)
        caminhos = sorted(glob.glob(os.path.join(pasta, "*.mp4")))

    caminhos = [c for c in caminhos if os.path.exists(c)]
    if not caminhos:
        print("Nenhuma gravacao encontrada.")
        sys.exit(1)

    print(f"[modelo] {os.path.basename(args.modelo)}")
    modelo = YOLO(args.modelo)

    if args.listar:
        listar(modelo, caminhos, args.conf, args.imgsz)
        return

    bd = Banco()
    bd.abrir_sessao(os.path.basename(args.modelo), args.conf, args.ip or "sem atuador")
    print(f"[banco] {bd.caminho}")

    s3 = None
    if args.ip and not args.sem_disparo:
        s3 = ControleS3(args.ip)
        if s3.testar():
            print(f"[s3] {args.ip} respondeu, disparo real ligado")
        else:
            print(f"[s3] {args.ip} nao respondeu: {s3.ultimo_erro}")
    else:
        print("[s3] disparo desligado, so banco e painel")

    os.makedirs(os.path.join(BASE, "disparos"), exist_ok=True)

    janela = "Vigia KGB - reprocessamento do material gravado"
    cv2.namedWindow(janela, cv2.WINDOW_NORMAL | cv2.WINDOW_KEEPRATIO)
    print("\nq encerra | espaco pula | p pausa\n")

    total = 0
    for caminho in caminhos:
        d = reprocessar(modelo, caminho, bd, s3, args, janela)
        if d < 0:
            break
        total += d

    cv2.destroyAllWindows()
    print(f"\nfim. {total} ocorrencias gravadas no banco.")


if __name__ == "__main__":
    main()
