"""Teste USB REAL, somente de entrada, do DualSense com o codigo novo (tarefa 7.6).

Usa controle_dualsense.adaptador_hid (hidapi, so leitura) + entrada.PoliticaEntrada.
NAO fala com a ESP32-S3, nao envia output/feature reports, vibracao nem LED.
Guia o operador passo a passo e grava o resultado em .tmp/evidencias_usb/ (sem
numero de serie). Rodar pelo venv:

  .\\venv\\Scripts\\python.exe ferramentas\\teste_dualsense_usb.py [--sem-reconexao]
"""

import argparse
import json
import os
import sys
import threading
import time

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

from controle_dualsense.adaptador_hid import AdaptadorHID  # noqa: E402
from controle_dualsense.entrada import PoliticaEntrada  # noqa: E402

SAIDA = os.path.join(RAIZ, ".tmp", "evidencias_usb")


class Observador:
    def __init__(self):
        self.lock = threading.Lock()
        self.p = PoliticaEntrada()
        self.ad = AdaptadorHID(self.p, self.lock, ao_log=self._log_hid)
        self.registros = []
        self.t0 = time.monotonic()

    def _log_hid(self, tipo, **k):
        self._reg("hid", **k)

    def _reg(self, tipo, **k):
        r = {"t": round(time.monotonic() - self.t0, 3), "tipo": tipo, **k}
        self.registros.append(r)
        return r

    def amostra(self):
        agora = time.monotonic()
        with self.lock:
            inst = self.p.instantaneo(agora)
            eventos = self.p.retirar_eventos(agora)
        for e in eventos:
            self._reg("evento", evento=e.tipo, epoch=e.input_epoch, motivo=e.motivo)
        return inst, [e.tipo for e in eventos], agora


def esperar(obs, descricao, cond, limite_s, aceitar_nenhum=False):
    """cond(inst, eventos, estado_acum) -> True quando o passo foi cumprido."""
    print(f"\n>>> {descricao}  (ate {limite_s:.0f} s)", flush=True)
    obs._reg("passo", descricao=descricao)
    acum = {"eventos": [], "estados": set(), "pan_min": 0.0, "pan_max": 0.0, "epochs": set()}
    fim = time.monotonic() + limite_s
    ultimo_print = 0
    while time.monotonic() < fim:
        inst, ev, agora = obs.amostra()
        acum["eventos"] += ev
        acum["estados"].add(inst.estado)
        acum["epochs"].add(inst.input_epoch)
        acum["pan_min"] = min(acum["pan_min"], inst.pan_vel)
        acum["pan_max"] = max(acum["pan_max"], inst.pan_vel)
        if agora - ultimo_print > 0.5:
            print(f"    estado={inst.estado:16s} epoch={inst.input_epoch:3d} pan={inst.pan_vel:+.2f} "
                  f"saudavel={inst.saudavel(agora)} eventos={ev}", flush=True)
            ultimo_print = agora
        if cond(inst, ev, acum):
            res = {"ok": True}
            break
        time.sleep(0.01)
    else:
        res = {"ok": aceitar_nenhum}
    res.update(passo=descricao, eventos=acum["eventos"], estados=sorted(acum["estados"]),
               pan_min=round(acum["pan_min"], 3), pan_max=round(acum["pan_max"], 3),
               epochs=sorted(acum["epochs"]))
    obs._reg("resultado", **res)
    print(f"    -> {'OK' if res['ok'] else 'FALHOU'}", flush=True)
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sem-reconexao", action="store_true")
    ap.add_argument("--limite", type=float, default=60.0, help="segundos por passo")
    a = ap.parse_args()
    L = a.limite
    obs = Observador()
    obs.ad.iniciar()
    resultados = []
    try:
        armada = lambda i, e, s: i.armada
        resultados.append(esperar(obs, "Solte tudo (repouso) ate armar", armada, L))
        for botao in ("cruz", "triangulo", "quadrado", "circulo"):
            resultados.append(esperar(obs, f"Pressione e solte {botao.upper()}",
                                      lambda i, e, s, b=botao: b in s["eventos"], L))
        resultados.append(esperar(obs, "Analogico esquerdo todo para a ESQUERDA",
                                  lambda i, e, s: i.pan_vel >= 0.9, L))
        resultados.append(esperar(obs, "Analogico esquerdo todo para a DIREITA",
                                  lambda i, e, s: i.pan_vel <= -0.9, L))
        resultados.append(esperar(obs, "Solte o analogico (zona morta -> 0)",
                                  lambda i, e, s: i.armada and i.pan_vel == 0.0, L))
        # Quadrado segurado: uma unica borda, nenhuma repeticao.
        r = esperar(obs, "SEGURE Quadrado por ~3 s e depois solte",
                    lambda i, e, s: s["eventos"].count("quadrado") >= 1 and i.armada and False, 8.0,
                    aceitar_nenhum=True)
        r["ok"] = r["eventos"].count("quadrado") == 1
        r["criterio"] = "exatamente 1 evento quadrado em 8 s com o botao segurado"
        resultados.append(r)
        if not a.sem_reconexao:
            # Reconexao segurando Quadrado: a perda invalida o epoch; ao voltar,
            # Quadrado segurado NAO pode gerar evento (exige neutro para armar).
            r = esperar(obs, "SEGURANDO Quadrado: desconecte o cabo USB, reconecte e continue segurando",
                        lambda i, e, s: "descontinuidade" in s["eventos"] and obs.ad.dev is not None
                        and i.estado == "ARMANDO", L)
            resultados.append(r)
            r2 = esperar(obs, "Continue segurando Quadrado (5 s, nao deve armar nem disparar)",
                         lambda i, e, s: False, 5.0, aceitar_nenhum=True)
            r2["ok"] = "quadrado" not in r2["eventos"] and "ARMADA" not in r2["estados"]
            r2["criterio"] = "sem evento quadrado e sem ARMADA enquanto segurado apos reconexao"
            resultados.append(r2)
            resultados.append(esperar(obs, "Solte Quadrado e todos os controles (deve rearmar)", armada, L))
    finally:
        obs.ad.parar()
    os.makedirs(SAIDA, exist_ok=True)
    nome = os.path.join(SAIDA, time.strftime("teste_usb_%Y%m%d_%H%M%S.json"))
    with open(nome, "w", encoding="utf-8") as f:
        json.dump({"resultados": resultados, "registros": obs.registros,
                   "descartados": obs.p.descartados, "invalidos": obs.p.invalidos}, f, ensure_ascii=False, indent=1)
    ok = all(r["ok"] for r in resultados)
    print(f"\nRESUMO: {sum(r['ok'] for r in resultados)}/{len(resultados)} passos OK -> {nome}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
