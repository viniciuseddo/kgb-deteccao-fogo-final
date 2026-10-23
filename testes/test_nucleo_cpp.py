"""Roda os testes C++ host do nucleo real e dos adaptadores do sketch.

Resultados separados dos testes de politica Python (tarefa 7.3).
"""

import os
import subprocess
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import apoio_cpp  # noqa: E402

STUBS = os.path.join(apoio_cpp.NUCLEO_CPP, "stubs")


class TestNucleoCpp(unittest.TestCase):
    def test_unitarios_do_nucleo(self):
        exe = apoio_cpp.compilar("test_nucleo", [os.path.join(apoio_cpp.NUCLEO_CPP, "test_nucleo.cpp")])
        r = subprocess.run([exe], capture_output=True, text=True, timeout=120)
        print("\n[C++ nucleo]", r.stdout.strip().splitlines()[-1] if r.stdout.strip() else r.stderr)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


class TestAdaptadoresSketch(unittest.TestCase):
    """O .ino real com substitutos; a protecao roda em thread propria."""

    @classmethod
    def setUpClass(cls):
        cls.exe = apoio_cpp.compilar(
            "test_adaptadores", [os.path.join(apoio_cpp.NUCLEO_CPP, "test_adaptadores.cpp")], incluir=(STUBS,))

    def test_corte_no_prazo_com_loop_retido_e_falha_de_tarefa(self):
        modos = ["http", "lcd", "serial", "falha"]

        def rodar(m):
            return m, subprocess.run([self.exe, m], capture_output=True, text=True, timeout=60)

        with ThreadPoolExecutor(max_workers=4) as ex:
            resultados = list(ex.map(rodar, modos))
        for m, r in resultados:
            with self.subTest(modo=m):
                print(f"\n[C++ adaptadores] {r.stdout.strip()}")
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_sem_segredos_usa_placeholders(self):
        # O sketch versionado nunca carrega senha: sem segredos_wifi.h ficam os placeholders.
        self.assertFalse(os.path.exists(os.path.join(apoio_cpp.SKETCH, "segredos_wifi.h")))
        r = subprocess.run([self.exe, "ssid"], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("ssid=COLOQUE_O_NOME_DA_REDE senha=COLOQUE_A_SENHA", r.stdout)

    def test_segredos_fora_do_git_substituem_placeholders(self):
        pasta = os.path.join(apoio_cpp.BUILD, "segredos_teste")
        os.makedirs(pasta, exist_ok=True)
        with open(os.path.join(pasta, "segredos_wifi.h"), "w", encoding="utf-8") as f:
            f.write('#define VIGIA_WIFI_SSID "rede_teste"\n#define VIGIA_WIFI_SENHA "senha_teste"\n')
        exe = apoio_cpp.compilar("test_adaptadores_segredos",
                                 [os.path.join(apoio_cpp.NUCLEO_CPP, "test_adaptadores.cpp")],
                                 incluir=(STUBS, pasta))
        r = subprocess.run([exe, "ssid"], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("ssid=rede_teste senha=senha_teste", r.stdout)


if __name__ == "__main__":
    unittest.main()
