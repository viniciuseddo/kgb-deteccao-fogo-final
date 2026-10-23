"""Laco do Vigia com --controle-dualsense (caminho novo, opt-in).

O laco original de sistema_vigia.main() nao e usado nem alterado aqui.
Diferencas declaradas do caminho novo:
  - camera com frame_id_local/published_at_monotonic/camera_epoch e regras
    de fronteira (CameraSerialProtegida); idade de captura NAO e conhecida;
  - confirmacao por 3 publicacoes locais distintas e frescas (<= 1 s);
  - disparo automatico e manual ('f'/Quadrado) pelo protocolo protegido;
    nenhuma letra legada e enviada ao S3;
  - 'f' so vale no modo MANUAL e respeita o guardiao comum;
  - deteccoes registradas com acao = decisao real (aceito/recusado/desconhecido),
    duracao_bomba ausente (nao ha duracao logica confiavel no momento do registro);
  - comandos/decisoes em JSONL separado.
"""

import os
import sys
import threading
import time

import cv2
import numpy as np

from .camera import CameraSerialProtegida
from .confirmacao import ConfirmacaoAutomatica
from .registro import RegistroJSONL, acao_deteccao

REGISTRO_PADRAO = os.path.join("dados", "comandos_controle.jsonl")
INTERVALO_REGISTRO_RECUSA_S = 12.0


def carregar_hid():
    try:
        import hid  # noqa: F401
        return hid
    except ImportError:
        print("--controle-dualsense exige a dependencia opcional hidapi.")
        print(r"Instale no venv do projeto: .\venv\Scripts\python.exe -m pip install -r requirements-dualsense.txt")
        print("Sem a opcao, o Vigia roda o caminho original sem HID.")
        sys.exit(2)


def executar(args, modelo, bd, base, achar_porta, modulo_hid=None, executor_cls=None):
    from .executor import ControleDualSense

    hid = modulo_hid or carregar_hid()
    caminho_log = args.log_controle or os.path.join(base, REGISTRO_PADRAO)
    reg = RegistroJSONL(caminho_log)
    print(f"[controle] DualSense habilitado; registro em {caminho_log}")

    porta = args.porta or achar_porta()
    if not porta:
        print("Nenhuma porta COM encontrada para a camera")
        sys.exit(1)
    cam = CameraSerialProtegida(porta, rotacao=args.rotacao)
    conf_auto = ConfirmacaoAutomatica(n=args.frames)
    os.makedirs(os.path.join(base, "disparos"), exist_ok=True)
    estado = {"ultimo_registro_recusa": -1e9}
    lock_reg = threading.Lock()

    def ao_resultado_ia(ctx, resultado, motivo):
        # Thread de controle. Evidencia de fogo e registrada mesmo sem agua.
        if resultado == "descartado" and motivo in ("geracao_antiga", "evidencia_antiga", "pedido_antigo"):
            return  # evidencia anterior a barreira ou velha: nao e evidencia valida agora
        agora = time.monotonic()
        with lock_reg:
            if resultado == "descartado":
                if agora - estado["ultimo_registro_recusa"] < INTERVALO_REGISTRO_RECUSA_S:
                    return
                estado["ultimo_registro_recusa"] = agora
        nome = time.strftime("disparos/fogo_%Y%m%d_%H%M%S.jpg")
        angulo = ctl.cliente.estado.pan

        def trabalho():
            try:
                cv2.imwrite(os.path.join(base, nome), ctx["imagem"])
                bd.registrar(confianca=float(ctx["confianca"]), angulo_pan=angulo,
                             acao=acao_deteccao(resultado, motivo), duracao_bomba=None,
                             imagem=nome, origem="ESP32-CAM")
            except Exception as e:
                reg.escrever("erro_registro", erro=repr(e))

        threading.Thread(target=trabalho, daemon=True).start()

    Executor = executor_cls or ControleDualSense
    ctl = Executor(args.ip, reg, ao_fronteira_camera=cam.fronteira, ao_resultado_ia=ao_resultado_ia,
                   modulo_hid=hid)
    ctl.iniciar()

    conf = args.conf
    n_quadros = 0
    ultimo_id = None
    t0 = time.monotonic()
    janela = "Vigia KGB - deteccao de chama (DualSense)"
    cv2.namedWindow(janela, cv2.WINDOW_NORMAL | cv2.WINDOW_KEEPRATIO)
    print("\nq sai | f disparo manual (so no MANUAL) | r gira | + e - mudam o limiar")
    print("DualSense: X manual | analogico esq. move | Triangulo auto | Quadrado agua (manual) | Circulo cancela\n")

    try:
        while True:
            pub = cam.publicacao()
            if pub is None or pub.frame_id_local == ultimo_id:
                tela = np.zeros((360, 640, 3), dtype=np.uint8)
                cv2.putText(tela, "aguardando quadro novo da camera...", (90, 170),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (180, 180, 180), 2)
                cv2.putText(tela, ctl.texto()[:60], (20, 210), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
                if pub is None:
                    cv2.imshow(janela, tela)
                k = cv2.waitKey(15) & 0xFF
                if k in (ord("q"), 27):
                    break
                if pub is None:
                    continue
                if pub.frame_id_local == ultimo_id:
                    continue
            ultimo_id = pub.frame_id_local
            geracao_inicio = ctl.geracao()
            n_quadros += 1
            r = modelo.predict(pub.frame, conf=conf, imgsz=args.imgsz, verbose=False)[0]
            achou = len(r.boxes) > 0
            melhor = float(r.boxes.conf.max()) if achou else 0.0
            anotado = r.plot()
            agora = time.monotonic()
            if conf_auto.registrar(pub, achou, geracao_inicio, ctl.geracao(), agora):
                print(f">>> FOGO CONFIRMADO ({melhor:.0%}) em 3 publicacoes locais - pedindo agua protegida")
                ctl.pedir_disparo_ia({"geracao": geracao_inicio, "confianca": melhor, "imagem": anotado.copy(),
                                      "frame_id_local": pub.frame_id_local, "camera_epoch": pub.camera_epoch,
                                      "publicado_em": pub.published_at_monotonic})

            fps = n_quadros / max(agora - t0, 0.001)
            if achou:
                texto, cor = f"possivel {melhor:.0%} ({conf_auto.contagem}/{args.frames})", (0, 165, 255)
            else:
                texto, cor = "vigiando", (0, 200, 0)
            larg = anotado.shape[1]
            cv2.rectangle(anotado, (0, 0), (larg, 52), (25, 25, 25), -1)
            cv2.putText(anotado, texto, (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, cor, 2)
            info = f"{fps:.1f} fps | conf {conf:.2f} | {ctl.texto()}"
            escala = 0.45
            while escala > 0.28:
                (tw, _), _ = cv2.getTextSize(info, cv2.FONT_HERSHEY_SIMPLEX, escala, 1)
                if tw <= larg - 16:
                    break
                escala -= 0.03
            cv2.putText(anotado, info, (8, 43), cv2.FONT_HERSHEY_SIMPLEX, escala, (200, 200, 200), 1)
            cv2.imshow(janela, anotado)
            k = cv2.waitKey(1) & 0xFF
            if k in (ord("q"), 27):
                break
            elif k == ord("f"):
                print(">>> disparo manual pelo teclado (exige MANUAL; guardiao comum)")
                ctl.tecla_disparo()
            elif k == ord("r"):
                print(f"rotacao: {cam.girar()} graus")
            elif k in (ord("+"), ord("=")):
                conf = min(0.95, conf + 0.05)
            elif k in (ord("-"), ord("_")):
                conf = max(0.05, conf - 0.05)
    finally:
        ctl.parar()
        cam.fechar()
        cv2.destroyAllWindows()
        print(f"\nfim. {n_quadros} quadros processados")
