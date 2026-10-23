"""Teste ultrarrápido de conexão HTTP com o ESP32-S3 na rede do Hotspot.

Uso:
  python ferramentas/testar_conexao_s3.py <IP_DO_S3>
"""

import sys
import json
import urllib.request

if len(sys.argv) < 2:
    print("Uso: python ferramentas/testar_conexao_s3.py <IP_DO_S3>")
    sys.exit(1)

ip = sys.argv[1].replace("http://", "").rstrip("/")
url = f"http://{ip}/status"

print(f"Testando conexao com ESP32-S3 em {url}...")
try:
    with urllib.request.urlopen(url, timeout=3.0) as resp:
        if resp.status == 200:
            dados = json.loads(resp.read().decode("utf-8"))
            print("\n[OK] ESP32-S3 CONECTADO E RESPONDENDO COM SUCESSO!")
            print(f"  - Firmware: {dados.get('fw')}")
            print(f"  - Perfil: {dados.get('perfil')}")
            print(f"  - Modo: {dados.get('modo')}")
            print(f"  - Angulo Pan: {dados.get('pan')} graus")
            print(f"  - Protecao Rele: {'OK' if dados.get('protecao_ok') else 'FALHA'}")
            print(f"  - Bomba: {'Ligada' if dados.get('bomba') else 'Desligada'}")
            print("\nTudo pronto para rodar o sistema_vigia.py!")
            sys.exit(0)
        else:
            print(f"[ERRO] Resposta HTTP inesperada: {resp.status}")
            sys.exit(2)
except Exception as e:
    print(f"\n[FALHA] Nao foi possivel conectar ao ESP32-S3 em {ip}: {e}")
    print("Verifique se o notebook e a placa estao no mesmo Hotspot (2.4 GHz) e se o IP esta correto.")
    sys.exit(3)
