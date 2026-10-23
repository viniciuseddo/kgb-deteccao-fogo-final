"""Compilacao host (g++) do nucleo real do firmware para os testes.

Nao instala nada. Se o g++ nao existir, os testes que dependem dele falham
com mensagem explicita (nao sao pulados em silencio).
"""

import hashlib
import os
import shutil
import subprocess

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKETCH = os.path.join(RAIZ, "arduino", "esp32s3_vigia_dualsense")
NUCLEO_CPP = os.path.join(RAIZ, "testes", "nucleo_cpp")
BUILD = os.path.join(RAIZ, ".tmp", "build_testes")

FONTES_NUCLEO = ["vigia_protecao.cpp", "vigia_json.cpp", "vigia_arbitro.cpp"]
FLAGS = ["-std=c++17", "-O1", "-g", "-Wall", "-Wextra", "-Werror", "-pthread"]


class ErroCompilacao(RuntimeError):
    pass


def gxx():
    caminho = shutil.which("g++")
    if not caminho:
        raise ErroCompilacao("g++ nao encontrado no PATH; testes do nucleo C++ nao podem rodar")
    return caminho


def _assinatura(arquivos, extra):
    h = hashlib.sha256()
    for a in sorted(arquivos):
        with open(a, "rb") as f:
            h.update(a.encode())
            h.update(f.read())
    h.update(" ".join(extra).encode())
    return h.hexdigest()[:16]


def compilar(nome, fontes_teste, incluir=(), defines=(), com_nucleo=True):
    """Compila e devolve o caminho do executavel. Reaproveita se nada mudou."""
    os.makedirs(BUILD, exist_ok=True)
    fontes = list(fontes_teste)
    if com_nucleo:
        fontes += [os.path.join(SKETCH, f) for f in FONTES_NUCLEO]
    cabecalhos = []
    for d in (SKETCH, NUCLEO_CPP, *incluir):
        if os.path.isdir(d):
            cabecalhos += [os.path.join(d, f) for f in os.listdir(d) if f.endswith((".h", ".ino"))]
    extra = FLAGS + [f"-D{d}" for d in defines]
    sig = _assinatura(fontes + cabecalhos, extra)
    exe = os.path.join(BUILD, f"{nome}_{sig}.exe")
    if os.path.exists(exe):
        return exe
    cmd = [gxx(), "-pipe", *extra, f"-I{SKETCH}", f"-I{NUCLEO_CPP}"]
    cmd += [f"-I{d}" for d in incluir]
    cmd += fontes + ["-o", exe]
    # Temporarios do compilador dentro de .tmp/ (o TEMP do usuario pode estar
    # bloqueado no ambiente confinado).
    tmp = os.path.join(BUILD, "tmp")
    os.makedirs(tmp, exist_ok=True)
    env = dict(os.environ, TMP=tmp, TEMP=tmp, TMPDIR=tmp)
    r = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if r.returncode != 0:
        raise ErroCompilacao(f"falha ao compilar {nome}:\n{' '.join(cmd)}\n{r.stdout}\n{r.stderr}")
    return exe
