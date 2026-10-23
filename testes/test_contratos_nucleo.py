"""Executa os vetores de contrato contra o NUCLEO C++ REAL do firmware.

Cada cenario de testes/contratos/vetores_protocolo.json roda em um processo
novo de nucleo_cli (relogio simulado de 1 ms). Nao ha reimplementacao do
firmware em Python aqui: o Python so envia requisicoes e compara respostas.
"""

import json
import os
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import apoio_cpp  # noqa: E402

VETORES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "contratos", "vetores_protocolo.json")
ACOES_COM_SEQ = {"manual", "auto", "renovar", "mover", "disparar", "cancelar"}
AUSENTE = object()


def carregar_vetores():
    with open(VETORES, encoding="utf-8") as f:
        return json.load(f)


class Nucleo:
    def __init__(self, exe, t0=0, falha=False):
        args = [exe, "--t0", str(t0)]
        if falha:
            args.append("--falha-protecao")
        self.p = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True, encoding="utf-8")

    def enviar(self, t, rota, corpo=""):
        dados = corpo.encode("utf-8")
        self.p.stdin.write(f"{t} {rota} {len(dados)} {corpo}\n")
        self.p.stdin.flush()
        linha = self.p.stdout.readline()
        if not linha:
            raise RuntimeError("nucleo_cli terminou: " + self.p.stderr.read())
        return json.loads(linha)

    def fechar(self):
        try:
            self.p.stdin.close()
            self.p.wait(timeout=5)
        except Exception:
            self.p.kill()
            self.p.wait(timeout=5)
        finally:
            self.p.stdout.close()
            self.p.stderr.close()


class Executor:
    """Interpreta os passos de um cenario."""

    def __init__(self, nucleo, caso):
        self.n = nucleo
        self.caso = caso
        self.vars = {}
        self.corpos = {}  # indice do passo -> (rota, corpo bruto)

    # ------------------------------------------------------------ valores
    def resolver(self, v):
        if isinstance(v, str) and v.startswith("$"):
            nome = v[1:]
            if nome not in self.vars:
                raise KeyError(f"variavel indefinida {v}")
            return self.vars[nome]
        if isinstance(v, list):
            return [self.resolver(x) for x in v]
        return v

    @staticmethod
    def caminho(obj, cam):
        cur = obj
        for parte in cam.split("."):
            if isinstance(cur, dict) and parte in cur:
                cur = cur[parte]
            else:
                return AUSENTE
        return cur

    def valor(self, saida, cam):
        if cam.startswith("$"):
            return self.vars.get(cam[1:], AUSENTE)
        if cam == "http":
            return saida["http"]
        if cam == "texto":
            return saida["texto"]
        if cam.startswith("d."):
            return self.caminho(saida["d"], cam[2:])
        if saida.get("json") is None:
            return AUSENTE
        return self.caminho(saida["json"], cam)

    def conferir(self, saida, espera, rotulo):
        for cam, esperado in espera.items():
            if cam == "texto_contem":
                self.caso.assertIn(self.resolver(esperado), saida["texto"], f"{rotulo}: texto={saida['texto']!r}")
                continue
            obtido = self.valor(saida, cam)
            msg = f"{rotulo}: {cam} obtido={obtido!r} esperado={esperado!r}; resposta={saida}"
            if isinstance(esperado, dict) and len(esperado) == 1 and next(iter(esperado)).startswith("$"):
                op, arg = next(iter(esperado.items()))
                if op == "$nulo":
                    self.caso.assertIsNone(None if obtido is AUSENTE else obtido, msg)
                    self.caso.assertIsNot(obtido, AUSENTE, msg)
                elif op == "$naonulo":
                    self.caso.assertIsNot(obtido, AUSENTE, msg)
                    self.caso.assertIsNotNone(obtido, msg)
                elif op == "$dif":
                    self.caso.assertNotEqual(obtido, self.resolver(arg), msg)
                elif op == "$soma":
                    a, b = self.resolver(arg)
                    self.caso.assertEqual(obtido, a + b, msg)
                elif op == "$entre":
                    lo, hi = arg
                    self.caso.assertIsNot(obtido, AUSENTE, msg)
                    self.caso.assertTrue(lo <= obtido <= hi, msg)
                else:
                    raise ValueError(f"operador desconhecido {op}")
            else:
                self.caso.assertEqual(obtido, self.resolver(esperado), msg)

    def atualizar_janelas(self, sess, saida):
        js = saida.get("json") or {}
        for chave, suf in (("janela_c", "jc"), ("janela_x", "jx"), ("janela_r", "jr")):
            if chave in js:
                self.vars[f"{sess}_{suf}"] = js[chave]

    @staticmethod
    def compacto(obj):
        return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)

    # ------------------------------------------------------------ passos
    def corpo_comando(self, sess, corpo):
        c = {k: self.resolver(v) if k != "cancel_ate" or v != "$ultimo" else v for k, v in corpo.items()}
        ultimo = self.vars.get(f"{sess}_seq", 0)
        if c.get("cancel_ate") == "$ultimo":
            c["cancel_ate"] = ultimo
        if c.get("acao") in ACOES_COM_SEQ:
            if "seq" not in c:
                c["seq"] = ultimo + 1
            if isinstance(c["seq"], int):
                self.vars[f"{sess}_seq"] = max(ultimo, c["seq"])
            if "id" not in c:
                c["id"] = f"{sess}-{c['seq']}"
        base = {"v": 1, "boot_id": self.vars.get(f"{sess}_boot"), "sessao": self.vars.get(sess)}
        base.update(c)
        return self.compacto(base)

    def executar(self, idx, passo, rotulo):
        t = passo["t"]
        espera = passo.get("espera", {})
        sess = passo.get("sess")
        macro = passo.get("macro")

        if "repetir_passo" in passo:
            rota, corpo = self.corpos[passo["repetir_passo"]]
            saida = self.n.enviar(t, rota, corpo)
        elif macro == "abrir":
            st = self.n.enviar(t, "status")["json"]
            self.vars[f"{sess}_boot"] = st["boot_id"]
            corpo = self.compacto({"v": 1, "boot_id": st["boot_id"],
                                   "session_open_id": passo.get("open_id", f"{sess}-abre"),
                                   "janela": st["janela_abertura"]})
            self.corpos[idx] = ("sessao", corpo)
            saida = self.n.enviar(t, "sessao", corpo)
            js = saida.get("json") or {}
            if js.get("resultado") == "aceito":
                self.vars[sess] = js.get("sessao")
                self.vars.setdefault(f"{sess}_seq", 0)
            self.atualizar_janelas(sess, saida)
            if "espera" not in passo:
                espera = {"resultado": "aceito"}
        elif macro == "janela":
            corpo = self.corpo_comando(sess, {"acao": "janela"})
            saida = self.n.enviar(t, "comando", corpo)
            self.atualizar_janelas(sess, saida)
        else:
            rota = passo["rota"]
            if rota == "status":
                saida = self.n.enviar(t, "status")
            elif rota == "avancar":
                saida = self.n.enviar(t, "avancar")
            elif rota in ("cmd", "serial"):
                saida = self.n.enviar(t, rota, passo["letra"])
            elif rota == "sessao":
                corpo = self.compacto({k: self.resolver(v) for k, v in passo["corpo"].items()})
                self.corpos[idx] = ("sessao", corpo)
                saida = self.n.enviar(t, "sessao", corpo)
            elif rota == "comando":
                if "corpo_bruto" in passo:
                    corpo = passo["corpo_bruto"]
                else:
                    corpo = self.corpo_comando(sess, passo["corpo"])
                self.corpos[idx] = ("comando", corpo)
                saida = self.n.enviar(t, "comando", corpo)
                if sess:
                    self.atualizar_janelas(sess, saida)
            else:
                raise ValueError(f"rota desconhecida {rota}")

        for nome, cam in passo.get("capturar", {}).items():
            v = self.valor(saida, cam)
            self.caso.assertIsNot(v, AUSENTE, f"{rotulo}: captura {nome} <- {cam} ausente; {saida}")
            self.vars[nome] = v
        if not passo.get("ignorar_resposta"):
            self.conferir(saida, espera, rotulo)
        return saida


def expandir(passos):
    lista = []
    for idx, p in enumerate(passos):
        if "repetir" in p:
            r = p["repetir"]
            for t in range(r["de"], r["ate"] + 1, r["passo"]):
                q = dict(p)
                q.pop("repetir")
                q["t"] = t
                lista.append((t, idx, q))
        else:
            lista.append((p["t"], idx, p))
    lista.sort(key=lambda x: x[0])  # sort estavel: empates mantem a ordem do arquivo
    return lista


class TestContratosNucleoCpp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.exe = apoio_cpp.compilar("nucleo_cli", [os.path.join(apoio_cpp.NUCLEO_CPP, "nucleo_cli.cpp")])
        cls.vetores = carregar_vetores()

    def test_cenarios(self):
        nomes = set()
        for cen in self.vetores["cenarios"]:
            self.assertNotIn(cen["nome"], nomes)
            nomes.add(cen["nome"])
            with self.subTest(cenario=cen["nome"]):
                n = Nucleo(self.exe, t0=cen.get("t0", 0), falha=cen.get("falha_protecao", False))
                try:
                    ex = Executor(n, self)
                    for t, idx, passo in expandir(cen["passos"]):
                        ex.executar(idx, passo, f"{cen['nome']}[{idx}]@t={t}")
                finally:
                    n.fechar()


if __name__ == "__main__":
    unittest.main()
