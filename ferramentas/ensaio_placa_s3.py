"""Ensaios automatizados de bancada na ESP32-S3 real sem atuadores.

Cobre os Ensaios 2, 4, 5 e 6 do ROTEIRO_BANCADA.md:
- Ensaio 2: /status, perfil COMPAT, protecao_ok=true, capacidades
- Ensaio 4: Jitter J do guardiao da bomba sob estresse HTTP/Serial (telemetria interna FreeRTOS)
- Ensaio 5: Expiracao do lease manual e retorno a AUTO em ~1500 ms
- Ensaio 6: Transicao para perfil PROTEGIDO e bloqueio de comandos legados (403)
"""

import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

from controle_dualsense.protocolo import ClienteProtocolo, verificar_compatibilidade
from controle_dualsense.transporte import TransporteHTTP

IP = sys.argv[1] if len(sys.argv) > 1 else "192.168.15.43"
BASE_URL = f"http://{IP}"


def get_json(caminho, timeout=5.0):
    req = urllib.request.Request(f"{BASE_URL}{caminho}")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_text(caminho, timeout=5.0):
    req = urllib.request.Request(f"{BASE_URL}{caminho}")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8")


def ensaio_2_status():
    print("\n--- [Ensaio 2] /status e Capacidades Iniciais ---")
    st = get_json("/status")
    print(f"Versao: {st.get('v')} | FW: {st.get('fw')} | Boot ID: {st.get('boot_id')}")
    print(f"Perfil: {st.get('perfil')} | Modo: {st.get('modo')} | Protecao OK: {st.get('protecao_ok')}")
    print(f"Caps: {st.get('caps')}")
    incomp = verificar_compatibilidade(st)
    assert incomp is None, f"Incompatibilidade detectada: {incomp}"
    assert st.get("v") == 1, "Versao incompativel"
    assert st.get("protecao_ok") is True, "Protecao nao OK"
    print("-> Ensaio 2: PASSOU!")
    return st


def ensaio_4_jitter_bomba_estresse():
    print("\n--- [Ensaio 4] Jitter J da Protecao sob Estresse HTTP ---")
    st = get_json("/status")
    cooldown = st.get("cooldown_restante_ms", 0)
    if cooldown > 0:
        espera = (cooldown / 1000.0) + 0.5
        print(f"Aguardando cooldown restante de {cooldown} ms ({espera:.1f} s)...")
        time.sleep(espera)

    # Dispara agua pelo endpoint legado COMPAT /cmd?c=F
    print("Disparando agua (5000 ms nominal) via /cmd?c=F...")
    st_disp = get_text("/cmd?c=F")
    print(f"Resposta disparo: {st_disp.strip()}")

    # Gerador de carga estressante durante a contagem dos 5000 ms
    parar_estresse = threading.Event()
    reqs_cont = [0]

    def carga_estresse():
        while not parar_estresse.is_set():
            try:
                urllib.request.urlopen(f"{BASE_URL}/status", timeout=0.5).read()
                reqs_cont[0] += 1
            except Exception:
                pass
            time.sleep(0.02)

    threads = [threading.Thread(target=carga_estresse) for _ in range(4)]
    for th in threads:
        th.start()

    # Aguarda o ciclo nominal (5.0s) + margem de protecao
    print("Gerando estresse HTTP paralelo concorrente...")
    time.sleep(5.5)
    parar_estresse.set()
    for th in threads:
        th.join()

    diag = get_json("/diag")
    print(f"Requisicoes de estresse completadas: {reqs_cont[0]}")
    print(f"Telemetria /diag: {json.dumps(diag, indent=2)}")

    duracao_us = diag.get("agua_ult_us")
    assert duracao_us is not None, "agua_ult_us nao registrado pela tarefa de protecao"
    duracao_ms = duracao_us / 1000.0
    jitter_ms = abs(duracao_ms - 5000.0)
    print(f"DURACAO MEDIDA NO S3: {duracao_ms:.3f} ms | JITTER J: {jitter_ms:.3f} ms")
    assert jitter_ms <= 10.0, f"Jitter {jitter_ms} ms excedeu meta de 10 ms!"
    assert diag.get("rele") is False, "Rele nao foi desligado ao fim dos 5000 ms"
    print(f"-> Ensaio 4: PASSOU! (J = {jitter_ms:.3f} ms <= 10 ms sob {reqs_cont[0]} reqs concorrentes)")
    return jitter_ms


def ensaio_6_transicao_perfil_protegido(cliente):
    print("\n--- [Ensaio 6] Transicao para Perfil PROTEGIDO e Bloqueio de Comandos Legados ---")
    st = get_json("/status")
    print(f"Perfil antes da sessao: {st.get('perfil')}")

    # Abertura de sessao protegida via cliente de protocolo oficial
    r = cliente.abrir_sessao()
    print(f"abrir_sessao() -> HTTP {r.http}: {r.json}")
    assert r.aceito, f"Sessao nao aceita: {r.json}"
    assert cliente.sessao is not None, "Sessao nao inicializada no cliente"

    # Verifica se perfil agora e PROTEGIDO no /status
    st2 = get_json("/status")
    print(f"Novo perfil no /status: {st2.get('perfil')}")
    assert st2.get("perfil") == "PROTEGIDO", "Perfil nao transitou para PROTEGIDO"

    # Tentativa de comando legado DEVE ser bloqueada com HTTP 403
    print("Testando comando legado /cmd?c=L no perfil PROTEGIDO...")
    try:
        urllib.request.urlopen(f"{BASE_URL}/cmd?c=L", timeout=3.0)
        assert False, "Comando legado deveria ter sido rejeitado com HTTP 403"
    except urllib.error.HTTPError as e:
        corpo = e.read().decode("utf-8").strip()
        print(f"Resposta recebida esperada: HTTP {e.code} ({corpo})")
        assert e.code == 403, f"Esperado 403, recebido {e.code}"

    print("-> Ensaio 6: PASSOU!")


def ensaio_5_lease_manual(cliente):
    print("\n--- [Ensaio 5] Lease Manual e Retorno a AUTO ---")
    # Envia comando de entrar em MANUAL
    corpo, motivo = cliente.montar("manual")
    assert corpo is not None, f"Falha ao montar comando manual: {motivo}"
    r = cliente.enviar(corpo)
    print(f"Comando manual -> HTTP {r.http}: {r.json}")
    assert r.aceito, f"Comando manual recusado: {r.json}"

    st_manual = get_json("/status")
    print(f"Modo atual: {st_manual.get('modo')} (lease={st_manual.get('lease_restante_ms')} ms)")
    assert st_manual.get("modo") == "MANUAL", "Nao entrou em modo MANUAL"

    # Para de renovar o lease e aguarda expiracao (1500 ms + margem)
    print("Parando renovacao do lease; aguardando 1.8 s para retorno a AUTO...")
    time.sleep(1.8)

    st_auto = get_json("/status")
    print(f"Modo apos expiracao: {st_auto.get('modo')} (lease={st_auto.get('lease_restante_ms')} ms, retorno_auto={st_auto.get('retorno_auto')})")
    assert st_auto.get("modo") == "AUTO", "Nao retornou a AUTO apos expiracao do lease"
    print("-> Ensaio 5: PASSOU!")


def main():
    print(f"Iniciando bateria de ensaios de bancada contra ESP32-S3 em {IP}")
    transporte = TransporteHTTP(IP)
    cliente = ClienteProtocolo(transporte, time.monotonic)

    ensaio_2_status()
    j = ensaio_4_jitter_bomba_estresse()
    ensaio_6_transicao_perfil_protegido(cliente)
    ensaio_5_lease_manual(cliente)

    print("\n=======================================================")
    print(f"TODOS OS ENSAIOS DE BANCADA PASSARAM COM SUCESSO!")
    print(f"- Jitter interno de protecao J: {j:.3f} ms (meta <= 10 ms)")
    print(f"- Protocolo protegido, lease e fail-safe validados na placa real.")
    print("=======================================================\n")


if __name__ == "__main__":
    main()
