"""Roda modulos de teste com limite de tempo por modulo (evita terminal preso).

Uso: .\\venv\\Scripts\\python.exe testes\\rodar.py [modulo ...] [--limite 180]
Sem modulos, roda todos os testes/test_*.py. Cada modulo roda em processo
proprio; ao estourar o limite, a arvore do processo e encerrada.
"""

import glob
import os
import subprocess
import sys
import time

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def matar_arvore(p):
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True)
    else:
        p.kill()


def main():
    args = sys.argv[1:]
    limite = 180
    if "--limite" in args:
        i = args.index("--limite")
        limite = int(args[i + 1])
        del args[i:i + 2]
    mods = args or sorted("testes." + os.path.basename(f)[:-3]
                          for f in glob.glob(os.path.join(RAIZ, "testes", "test_*.py")))
    falhou = False
    for m in mods:
        t0 = time.monotonic()
        p = subprocess.Popen([sys.executable, "-m", "unittest", m], cwd=RAIZ,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                             encoding="utf-8", errors="replace")
        try:
            saida, _ = p.communicate(timeout=limite)
            codigo = p.returncode
        except subprocess.TimeoutExpired:
            matar_arvore(p)
            saida, _ = p.communicate()
            codigo = "TIMEOUT"
        linhas = [l for l in saida.splitlines() if l.startswith(("Ran ", "OK", "FAILED", "FAIL:", "ERROR:"))
                  or "Error:" in l or "[C++" in l]
        print(f"== {m}: {codigo} em {time.monotonic() - t0:.1f}s")
        for l in linhas:
            print("   " + l[:300])
        if codigo != 0:
            falhou = True
            if codigo != "TIMEOUT":
                print("\n".join("   | " + l for l in saida.splitlines()[-30:]))
    sys.exit(1 if falhou else 0)


if __name__ == "__main__":
    main()
