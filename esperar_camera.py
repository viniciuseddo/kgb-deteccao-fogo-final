"""
Fica esperando a ESP32-CAM aparecer na rede, e avisa quando aparecer.

Serve pra tirar o cronometro da mao. Voce roda isso, aperta RST na base, e
ele fica batendo na porta 80 de todos os IPs da faixa ate alguem atender.

Uso:
    .\\venv\\Scripts\\python.exe esperar_camera.py

Ele roda por 120 segundos por padrao. Enquanto roda, ele imprime um ponto a
cada rodada, pra voce saber que esta vivo.

O que a saida te diz:
  aparece e FICA        -> era so questao de tempo de boot
  aparece e SOME        -> a placa esta reiniciando em loop, problema de corrente
  nunca aparece         -> nao esta conectando no WiFi
"""

import argparse
import socket
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

ap = argparse.ArgumentParser()
ap.add_argument("--faixa", default=None, help="tres primeiros octetos, ex 172.20.10")
ap.add_argument("--inicio", type=int, default=2)
ap.add_argument("--fim", type=int, default=14)
ap.add_argument("--segundos", type=float, default=120.0, help="quanto tempo esperar")
ap.add_argument("--porta", type=int, default=80)
args = ap.parse_args()


def minha_rede():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    finally:
        s.close()
    return ip.rsplit(".", 1)[0], ip


faixa, meu_ip = minha_rede()
if args.faixa:
    faixa = args.faixa.rstrip(".")

print(f"Seu PC esta em {meu_ip}")
print(f"Vigiando {faixa}.{args.inicio} a {faixa}.{args.fim} por {args.segundos:.0f}s")
print("APERTE RST NA BASE AGORA.\n")


def porta_aberta(n):
    ip = f"{faixa}.{n}"
    if ip == meu_ip:
        return None
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.8)
    try:
        if s.connect_ex((ip, args.porta)) == 0:
            return ip
    except Exception:
        pass
    finally:
        s.close()
    return None


inicio = time.time()
visto = {}      # ip -> quantas rodadas seguidas apareceu
sumiu = []      # historico de quem apareceu e sumiu
rodada = 0

while time.time() - inicio < args.segundos:
    rodada += 1
    presentes = set()
    with ThreadPoolExecutor(max_workers=8) as pool:
        for r in pool.map(porta_aberta, range(args.inicio, args.fim + 1)):
            if r:
                presentes.add(r)

    decorrido = time.time() - inicio

    for ip in presentes:
        if ip not in visto:
            print(f"\n[{decorrido:5.1f}s] APARECEU em {ip}")
            visto[ip] = 0
        visto[ip] += 1

    for ip in list(visto):
        if ip not in presentes:
            print(f"\n[{decorrido:5.1f}s] SUMIU {ip} "
                  f"(ficou {visto[ip]} rodadas no ar)")
            sumiu.append(ip)
            del visto[ip]

    # se algum IP ficou estavel por 3 rodadas seguidas, tenta pegar a foto
    for ip, vezes in list(visto.items()):
        if vezes == 3:
            print(f"[{decorrido:5.1f}s] {ip} estavel, pedindo uma foto...")
            try:
                with urllib.request.urlopen(f"http://{ip}/capture", timeout=15) as r:
                    dados = r.read()
                if dados[:3] == b"\xff\xd8\xff":
                    print(f"\nCAMERA OK em {ip}, JPEG de {len(dados)} bytes.\n")
                    print("Comando pra gravar:\n")
                    print(f"  .\\venv\\Scripts\\python.exe gravar_tomadas.py {ip} "
                          f"--continuo --pular 3 --timeout 15")
                    raise SystemExit(0)
                print(f"  respondeu mas nao veio JPEG: {dados[:8]!r}")
            except SystemExit:
                raise
            except Exception as erro:
                print(f"  /capture falhou: {erro}")

    print(".", end="", flush=True)
    time.sleep(1.5)

print("\n\nTempo esgotado.")
if sumiu:
    print(f"A placa APARECEU e SUMIU ({len(sumiu)} vez(es)).")
    print("Isso e reinicio em loop, quase sempre falta de corrente:")
    print("  1. troca o cabo micro USB, muitos sao so de carga")
    print("  2. usa uma porta USB da TRASEIRA do notebook, nao a frontal")
    print("  3. tira qualquer outra coisa da USB enquanto grava")
else:
    print("A placa nunca apareceu na rede.")
    print("  1. o roteamento do celular esta em 2.4GHz, com Maximizar Compatibilidade")
    print("  2. a senha gravada no sketch e a senha atual do roteamento")
    print("  3. abre o Serial Monitor em 115200 e aperta RST pra ver o motivo")
