"""
Acha o IP da ESP32-CAM na rede, sem precisar abrir o miniterm.

Por que existe: a base ESP32-CAM-MB liga o DTR no GPIO0. Abrir um terminal
serial nela, dependendo das flags, joga a placa em modo de gravacao e ela
para de servir imagem. Esse script descobre o IP pela propria rede, sem
encostar na porta COM.

COMO ELE FAZ, e por que assim:
  A ESP32-CAM atende UM cliente por vez, e o sensor GC2145 nao tem JPEG por
  hardware, entao cada /capture leva de 1 a 3 segundos. Varrer a rede pedindo
  imagem de todo mundo ao mesmo tempo derruba a placa. Entao aqui a varredura
  e em duas fases:

    fase 1  bate na porta 80 de cada IP, so pra ver quem atende. E leve,
            nao pede imagem, e pode ser paralelo.
    fase 2  em cada candidato, UM de cada vez, pede /capture com timeout
            folgado e confere se voltou um JPEG de verdade.

Uso:
    .\\venv\\Scripts\\python.exe achar_camera.py

Se estiver em outra rede que nao a do celular:
    .\\venv\\Scripts\\python.exe achar_camera.py --faixa 192.168.0 --fim 254
"""

import argparse
import socket
import urllib.request
from concurrent.futures import ThreadPoolExecutor

ap = argparse.ArgumentParser()
ap.add_argument("--faixa", default=None,
                help="tres primeiros octetos, ex 172.20.10. Sem isso ele deduz da sua rede")
ap.add_argument("--inicio", type=int, default=2, help="ultimo octeto inicial")
ap.add_argument("--fim", type=int, default=14,
                help="ultimo octeto final. O roteamento do iPhone so vai ate 14")
ap.add_argument("--porta", type=int, default=80, help="porta do servidor da placa")
ap.add_argument("--timeout-porta", type=float, default=1.0,
                help="timeout da fase 1, so pra ver quem atende na porta")
ap.add_argument("--timeout-foto", type=float, default=10.0,
                help="timeout da fase 2. Generoso de proposito: o GC2145 e lento")
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
print(f"Fase 1: procurando quem atende na porta {args.porta}, "
      f"de {faixa}.{args.inicio} a {faixa}.{args.fim}")


def porta_aberta(n):
    ip = f"{faixa}.{n}"
    if ip == meu_ip:
        return None
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(args.timeout_porta)
    try:
        if s.connect_ex((ip, args.porta)) == 0:
            return ip
    except Exception:
        pass
    finally:
        s.close()
    return None


candidatos = []
with ThreadPoolExecutor(max_workers=8) as pool:
    for r in pool.map(porta_aberta, range(args.inicio, args.fim + 1)):
        if r:
            candidatos.append(r)
            print(f"  porta 80 aberta em {r}")

if not candidatos:
    print("\nNinguem atendeu na porta 80 nessa faixa.")
    print("Confira, nesta ordem:")
    print("  1. o Acesso Pessoal do iPhone mostra 2 conexoes, nao 1")
    print("  2. o PC esta na rede IPHONE V, nao na rede de casa")
    print("  3. tira e poe o cabo micro USB e espera 20 segundos")
    raise SystemExit(1)

print(f"\nFase 2: pedindo uma foto de cada candidato, um de cada vez.")
print("Isso pode levar alguns segundos por IP, o GC2145 converte o JPEG por software.\n")

achados = []
for ip in candidatos:
    url = f"http://{ip}/capture"
    try:
        with urllib.request.urlopen(url, timeout=args.timeout_foto) as r:
            dados = r.read()
        if dados[:3] == b"\xff\xd8\xff":
            print(f"  {ip}  CAMERA OK, {len(dados)} bytes de JPEG")
            achados.append(ip)
        else:
            print(f"  {ip}  respondeu, mas nao veio JPEG "
                  f"(primeiros bytes: {dados[:8]!r})")
    except Exception as erro:
        print(f"  {ip}  atende na porta 80 mas /capture falhou: {erro}")

print()
if len(achados) == 1:
    ip = achados[0]
    print(f"Camera em {ip}. Comando pra gravar:\n")
    print(f"  .\\venv\\Scripts\\python.exe gravar_tomadas.py {ip} --continuo --pular 3")
elif len(achados) > 1:
    print("Mais de uma camera respondeu:", ", ".join(achados))
else:
    print("Tem algo atendendo na porta 80, mas nenhuma camera devolveu imagem.")
    print("Isso costuma ser um destes:")
    print("  1. o sketch subiu e conectou, mas a camera nao inicializou")
    print("     (cabo flat frouxo, ou o modulo errado encaixado)")
    print("  2. ficou uma aba do navegador aberta no IP da camera, prendendo")
    print("     o unico cliente que ela atende. Fecha a aba e roda de novo")
    print("  3. abre o Serial Monitor em 115200, aperta RST e le o motivo")
