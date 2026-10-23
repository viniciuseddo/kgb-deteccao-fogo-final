import hid
import time
import sys

cands = [d for d in hid.enumerate(0x054C, 0x0CE6) if d["usage_page"] == 1 and d["usage"] == 5]
if not cands:
    print("ERRO: DualSense nao encontrado!")
    sys.exit(1)

path = cands[0]["path"]
print(f"DualSense conectado: {path.decode('ascii', errors='ignore')}")

d = hid.device()
d.open_path(path)
d.set_nonblocking(0)

# Drena
d.set_nonblocking(1)
for _ in range(2000):
    if not d.read(128):
        break
d.set_nonblocking(0)

print("\n=== LEITOR AO VIVO ATIVO (45 SEGUNDOS) ===")
print("Pressione e solte botoes no controle (Cruz, Quadrado, Circulo, Triangulo) ou mexa o analogico!")
print("Cada mudanca sera impressa imediatamente abaixo:\n", flush=True)

t_fim = time.monotonic() + 45.0
ultimo_b8 = None
ultimo_lx = None
ultimo_aviso = time.monotonic()

while time.monotonic() < t_fim:
    pkt = d.read(128, 50)
    if pkt and len(pkt) == 64:
        lx = pkt[1]
        b8 = pkt[8]
        if ultimo_b8 is None:
            ultimo_b8 = b8
            ultimo_lx = lx
            print(f"[INICIAL] byte8=0x{b8:02x} | analógico_X={lx}", flush=True)
        elif b8 != ultimo_b8 or abs(lx - ultimo_lx) > 20:
            print(f">>> MUDOU: byte8=0x{b8:02x} (Cruz={(b8&0x20)!=0}, Quad={(b8&0x10)!=0}, Circ={(b8&0x40)!=0}, Tri={(b8&0x80)!=0}) | analógico_X={lx}", flush=True)
            ultimo_b8 = b8
            ultimo_lx = lx
    
    agora = time.monotonic()
    if agora - ultimo_aviso >= 3.0:
        restante = int(t_fim - agora)
        b8_val = ultimo_b8 if ultimo_b8 is not None else 0
        print(f"    (escutando... {restante}s restantes | estado atual: byte8=0x{b8_val:02x}, LX={ultimo_lx})", flush=True)
        ultimo_aviso = agora

d.close()
print("\nLeitor finalizado.")
