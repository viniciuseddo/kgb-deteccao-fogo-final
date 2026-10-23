"""Testes compartilhados: importar sistema_vigia sem efeitos colaterais.

sistema_vigia importa ultralytics no topo; o import real carrega torch e pode
gravar configuracao no perfil do usuario. Os testes injetam um modulo falso
ANTES do import. Nada aqui abre COM, rede, janela ou banco real.
"""

import importlib
import os
import sys
import types

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)


def importar_sistema_vigia():
    if "ultralytics" not in sys.modules or not getattr(sys.modules["ultralytics"], "_falso", False):
        falso = types.ModuleType("ultralytics")
        falso._falso = True

        class YOLO:  # substituido em cada teste
            def __init__(self, *a, **k):
                raise AssertionError("YOLO real nao deve ser usado nos testes")

        falso.YOLO = YOLO
        sys.modules["ultralytics"] = falso
    if "sistema_vigia" in sys.modules:
        return sys.modules["sistema_vigia"]
    return importlib.import_module("sistema_vigia")



TMP_TESTES = os.path.join(RAIZ, ".tmp", "testes_tmp")


class DiretorioTemporario:
    """Pasta temporaria dentro de .tmp/ (ignorada pelo Git).

    O TEMP do usuario pode estar bloqueado no ambiente confinado e o SQLite no
    Windows segura o arquivo ate o coletor fechar a conexao; por isso a limpeza
    roda gc e ignora arquivos ainda presos.
    """

    def __init__(self):
        import uuid
        self.name = os.path.join(TMP_TESTES, uuid.uuid4().hex[:12])
        os.makedirs(self.name)

    def cleanup(self):
        import gc
        import shutil
        gc.collect()
        shutil.rmtree(self.name, ignore_errors=True)

    def __enter__(self):
        return self.name

    def __exit__(self, *exc):
        self.cleanup()
