"""
Coletor de dataset da ESP32-CAM.
Chama http://IP/capture em loop e salva cada JPEG em uma pasta.
Rodar:  py coletar.py          (usa os valores abaixo)
        py coletar.py sessao02 (troca so o nome da pasta)
Parar:  Ctrl+C
"""
import urllib.request, time, os, sys

IP = "172.20.10.11"
PASTA_BASE = "dataset"
SESSAO = sys.argv[1] if len(sys.argv) > 1 else "sessao01"
INTERVALO = 1.5   # segundos entre fotos

destino = os.path.join(PASTA_BASE, SESSAO)
os.makedirs(destino, exist_ok=True)

# continua a numeracao se a pasta ja tiver fotos
existentes = [f for f in os.listdir(destino) if f.endswith(".jpg")]
i = len(existentes)

print(f"salvando em {destino}, ja tem {i} fotos")
print("Ctrl+C para parar")

while True:
    try:
        i += 1
        nome = os.path.join(destino, f"img_{i:04d}.jpg")
        urllib.request.urlretrieve(f"http://{IP}/capture", nome)
        tam = os.path.getsize(nome) // 1024
        print(f"{nome}  {tam} KB")
    except KeyboardInterrupt:
        print(f"\nparou com {i-1} fotos em {destino}")
        sys.exit(0)
    except Exception as e:
        print("erro:", e)
        i -= 1
    time.sleep(INTERVALO)
