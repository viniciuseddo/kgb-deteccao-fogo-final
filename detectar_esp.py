import argparse
import os
import time
import urllib.request

import cv2
import numpy as np
from ultralytics import YOLO


def baixar_frame(url, timeout=5):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        dados = r.read()
    buf = np.frombuffer(dados, dtype=np.uint8)
    return cv2.imdecode(buf, cv2.IMREAD_COLOR)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("ip")
    p.add_argument("modelo")
    p.add_argument("--conf", type=float, default=0.45)
    p.add_argument("--imgsz", type=int, default=416)
    p.add_argument("--frames", type=int, default=3)
    p.add_argument("--cooldown", type=float, default=5.0)
    p.add_argument("--classes", nargs="*", default=None)
    p.add_argument("--salvar", action="store_true")
    p.add_argument("--disparo", default=None)
    p.add_argument("--rota", default="/capture")
    args = p.parse_args()

    url = f"http://{args.ip}{args.rota}"

    print(f"carregando modelo: {args.modelo}")
    modelo = YOLO(args.modelo)
    nomes = modelo.names
    print(f"classes do modelo: {nomes}")

    if args.salvar:
        os.makedirs("deteccoes", exist_ok=True)

    seguidos = 0
    ultimo_disparo = 0.0
    n_frames = 0
    t0 = time.time()

    print(f"lendo {url}")
    print("q na janela para sair\n")

    while True:
        try:
            frame = baixar_frame(url)
        except KeyboardInterrupt:
            break
        except Exception as e:
            print("erro na captura:", e)
            time.sleep(1)
            continue

        if frame is None:
            print("frame invalido, pulando")
            continue

        n_frames += 1
        r = modelo.predict(frame, conf=args.conf, imgsz=args.imgsz, verbose=False)[0]

        achou = False
        linhas = []
        for box in r.boxes:
            cls = nomes[int(box.cls)]
            conf = float(box.conf)
            if args.classes and cls.lower() not in [c.lower() for c in args.classes]:
                continue
            achou = True
            linhas.append(f"{cls} {conf:.2f}")

        anotado = r.plot()

        if achou:
            seguidos += 1
            print(f"frame {n_frames}: " + ", ".join(linhas) + f"  (seguidos {seguidos})")
        else:
            seguidos = 0

        confirmado = seguidos >= args.frames
        agora = time.time()

        if confirmado and (agora - ultimo_disparo) > args.cooldown:
            ultimo_disparo = agora
            print(">>> FOGO CONFIRMADO <<<")

            if args.salvar:
                nome = time.strftime("deteccoes/fogo_%Y%m%d_%H%M%S.jpg")
                cv2.imwrite(nome, anotado)
                print("salvo:", nome)

            if args.disparo:
                try:
                    urllib.request.urlopen(args.disparo, timeout=3).read()
                    print("disparo enviado:", args.disparo)
                except Exception as e:
                    print("falha no disparo:", e)

        fps = n_frames / max(agora - t0, 0.001)
        cor = (0, 0, 255) if confirmado else (0, 200, 0)
        texto = "FOGO" if confirmado else "vigiando"
        cv2.putText(anotado, f"{texto}  {fps:.1f} fps", (8, 22),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, cor, 2)

        cv2.imshow("deteccao de fogo - ESP32-CAM", anotado)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    cv2.destroyAllWindows()
    print(f"\nfim. {n_frames} frames processados")


if __name__ == "__main__":
    main()