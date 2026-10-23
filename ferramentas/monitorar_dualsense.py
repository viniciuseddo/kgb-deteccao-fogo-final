"""Monitor passivo do DualSense USB: imprime qualquer acao no controle em tempo real."""

import sys
import time
import os

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

from controle_dualsense.adaptador_hid import AdaptadorHID
from controle_dualsense.entrada import PoliticaEntrada
import threading

lock = threading.Lock()
pol = PoliticaEntrada()

def log_hid(tipo, **k):
    pass

adaptador = AdaptadorHID(pol, lock, ao_log=log_hid)
adaptador.iniciar()

print("MONITOR ATIVO: aperte qualquer botao ou mexa o analogico no controle DualSense agora!")
print("(Pressione Ctrl+C para encerrar ou aguarde 30 segundos)\n", flush=True)

try:
    fim = time.time() + 30.0
    ultimo_estado = ""
    while time.time() < fim:
        agora = time.monotonic()
        with lock:
            inst = pol.instantaneo(agora)
            eventos = pol.retirar_eventos(agora)
        
        for ev in eventos:
            print(f">>> EVENTO DETECTADO: {ev.tipo.upper()} (epoch={ev.input_epoch})", flush=True)
            
        if abs(inst.pan_vel) > 0.1:
            print(f">>> ANALOGICO: pan_vel={inst.pan_vel:+.2f}", flush=True)
            
        time.sleep(0.05)
finally:
    adaptador.parar()
    print("\nMonitor encerrado.")
