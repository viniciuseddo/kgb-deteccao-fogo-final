"""Tarefas 2.2-2.4: parser HID e politica de entrada, sem hardware.

Usa as fixtures versionadas em testes/fixtures/dualsense_relatorios.json
(bytes medidos em posicao mantida). Relogio injetado; nenhum dispositivo e aberto.
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from controle_dualsense import entrada, relatorio  # noqa: E402

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "dualsense_relatorios.json")
with open(FIX, encoding="utf-8") as f:
    R = {k: bytes.fromhex(v) for k, v in json.load(f)["relatorios"].items()}


def com(base, eixo=None, byte8=None):
    b = bytearray(R[base])
    if eixo is not None:
        b[1] = eixo
    if byte8 is not None:
        b[8] = byte8
    return bytes(b)


NEUTRO = R["repouso"]
SOLTO = 0x08


class TestRelatorio(unittest.TestCase):
    def test_fixtures_medidas(self):
        self.assertEqual(relatorio.interpretar(R["repouso"]).eixo_bruto, 128)
        self.assertEqual(relatorio.interpretar(R["esquerda"]).eixo_bruto, 0)
        self.assertEqual(relatorio.interpretar(R["direita"]).eixo_bruto, 255)
        self.assertTrue(relatorio.interpretar(R["cruz"]).cruz)
        self.assertTrue(relatorio.interpretar(R["triangulo"]).triangulo)
        self.assertTrue(relatorio.interpretar(R["quadrado"]).quadrado)
        self.assertTrue(relatorio.interpretar(R["circulo"]).circulo)
        r = relatorio.interpretar(R["repouso"])
        self.assertFalse(r.cruz or r.triangulo or r.quadrado or r.circulo)

    def test_id_e_comprimento(self):
        self.assertIsNone(relatorio.interpretar(R["repouso"][:63]), "truncado")
        self.assertIsNone(relatorio.interpretar(R["repouso"] + b"\x00"), "longo")
        self.assertIsNone(relatorio.interpretar(b"\x31" + R["repouso"][1:]), "ID Bluetooth 0x31")
        self.assertIsNone(relatorio.interpretar(b"\x02" + R["repouso"][1:]), "outro ID")
        self.assertIsNone(relatorio.interpretar(b""), "vazio")
        self.assertIsNone(relatorio.interpretar(None))
        self.assertIsNone(relatorio.interpretar(list(R["repouso"])[:10]))
        self.assertIsNotNone(relatorio.interpretar(list(R["repouso"])), "lista de ints como o hidapi devolve")

    def test_mascaras_com_bits_extras(self):
        # Quadrado 0x10 junto do direcional (nibble baixo) e de outros bits.
        r = relatorio.interpretar(com("repouso", byte8=0x10 | 0x03))
        self.assertTrue(r.quadrado)
        self.assertFalse(r.cruz or r.triangulo or r.circulo)
        r = relatorio.interpretar(com("repouso", byte8=0xF0 | 0x08))
        self.assertTrue(r.cruz and r.triangulo and r.quadrado and r.circulo)

    def test_normalizacao_assimetrica(self):
        n = relatorio.normalizar_eixo
        self.assertEqual(n(0), -1.0)
        self.assertEqual(n(128), 0.0)
        self.assertEqual(n(255), 1.0)
        self.assertLess(n(64), 0)
        self.assertGreater(n(192), 0)
        for v in range(256):
            self.assertTrue(-1.0 <= n(v) <= 1.0)

    def test_zona_morta_e_reescala(self):
        z = relatorio.aplicar_zona_morta
        for v in (126, 127, 128, 129, 130):
            self.assertEqual(z(relatorio.normalizar_eixo(v), 0.10), 0.0, v)
        self.assertEqual(z(1.0, 0.10), 1.0)
        self.assertEqual(z(-1.0, 0.10), -1.0)
        self.assertAlmostEqual(z(0.55, 0.10), 0.5)
        self.assertEqual(z(0.10, 0.10), 0.0)
        self.assertGreater(z(0.11, 0.10), 0.0)

    def test_sinal_pan(self):
        # Angulo maior = esquerda no firmware: eixo negativo -> velocidade PAN positiva.
        self.assertEqual(relatorio.velocidade_pan(relatorio.interpretar(R["esquerda"]), 0.10), 1.0)
        self.assertEqual(relatorio.velocidade_pan(relatorio.interpretar(R["direita"]), 0.10), -1.0)
        self.assertEqual(relatorio.velocidade_pan(relatorio.interpretar(R["repouso_apos_reconexao"]), 0.10), 0.0)


class TestSelecao(unittest.TestCase):
    def cand(self, **kw):
        base = {"vendor_id": 0x054C, "product_id": 0x0CE6, "usage_page": 1, "usage": 5,
                "interface_number": 3, "path": b"p1", "serial_number": "NAO-REGISTRAR"}
        base.update(kw)
        return base

    def test_um_candidato(self):
        sel = relatorio.selecionar([self.cand(), self.cand(usage_page=0xFF00, path=b"p2")])
        self.assertEqual(sel.path, b"p1")
        self.assertIsNone(sel.motivo)
        self.assertNotIn("NAO-REGISTRAR", repr(sel))

    def test_nenhum_e_ambiguo(self):
        self.assertEqual(relatorio.selecionar([]).motivo, "dualsense_ausente")
        self.assertEqual(relatorio.selecionar([self.cand(product_id=0x09CC)]).motivo, "dualsense_ausente")
        amb = relatorio.selecionar([self.cand(), self.cand(path=b"p2")])
        self.assertIsNone(amb.path)
        self.assertEqual(amb.motivo, "dualsense_ambiguo")


class Fluxo:
    """Alimenta a politica com relatorios a 4 ms (~250/s)."""

    def __init__(self, **kw):
        self.p = entrada.PoliticaEntrada(**kw)
        self.t = 100.0
        self.eventos = []

    def enviar(self, dados, n=1, dt=0.004):
        for _ in range(n):
            self.t += dt
            self.p.iteracao(self.t)
            self.p.relatorio(dados, self.t)
            self.eventos += self.p.retirar_eventos(self.t)

    def armar(self):
        self.enviar(NEUTRO, n=80)  # 320 ms
        self.assertArmada()

    def assertArmada(self):
        assert self.p.armada, self.p.estado

    def tipos(self):
        return [e.tipo for e in self.eventos]


class TestPoliticaEntrada(unittest.TestCase):
    def test_inicia_desarmada_e_arma_com_300ms_neutro(self):
        f = Fluxo()
        self.assertFalse(f.p.armada)
        f.enviar(NEUTRO, n=70)  # 280 ms
        self.assertFalse(f.p.armada)
        f.enviar(NEUTRO, n=10)
        self.assertTrue(f.p.armada)

    def test_quadrado_segurado_ao_conectar_nao_dispara(self):
        f = Fluxo()
        f.enviar(R["quadrado"], n=200)
        self.assertFalse(f.p.armada)
        self.assertEqual(f.tipos(), [])
        f.enviar(NEUTRO, n=80)
        self.assertTrue(f.p.armada)
        self.assertEqual(f.tipos(), [], "soltar nao gera evento")
        f.enviar(R["quadrado"], n=3)
        self.assertEqual(f.tipos(), ["quadrado"], "so o NOVO pressionamento")

    def test_analogico_deslocado_impede_armar(self):
        f = Fluxo()
        f.enviar(R["direita"], n=200)
        self.assertFalse(f.p.armada)
        self.assertEqual(f.p.instantaneo(f.t).pan_vel, 0.0)

    def test_botao_mantido_gera_um_evento(self):
        f = Fluxo()
        f.armar()
        f.enviar(R["quadrado"], n=500)
        self.assertEqual(f.tipos(), ["quadrado"])

    def test_prioridade_simultaneos(self):
        f = Fluxo()
        f.armar()
        f.enviar(com("repouso", byte8=SOLTO | 0x20 | 0x10))  # Cruz + Quadrado
        self.assertEqual(f.tipos(), ["cruz"])
        f.enviar(NEUTRO, n=5)
        f.enviar(com("repouso", byte8=SOLTO | 0x40 | 0x10))  # Circulo + Quadrado
        self.assertEqual(f.tipos(), ["cruz", "circulo"])
        f.enviar(com("repouso", byte8=SOLTO | 0x40), n=5)  # solta so o Quadrado: nada
        self.assertEqual(f.tipos(), ["cruz", "circulo"], "descartado, nao adiado")
        f.enviar(NEUTRO, n=2)
        f.enviar(com("repouso", byte8=SOLTO | 0x80 | 0x20 | 0x40))
        self.assertEqual(f.tipos()[-1], "circulo")

    def test_pressao_curta_preservada_entre_retiradas(self):
        f = Fluxo()
        f.armar()
        # Pressiona e solta Circulo entre duas retiradas de eventos.
        for d in (R["circulo"], R["circulo"], NEUTRO, NEUTRO):
            f.t += 0.004
            f.p.iteracao(f.t)
            f.p.relatorio(d, f.t)
        ev = f.p.retirar_eventos(f.t)
        self.assertEqual([e.tipo for e in ev], ["circulo"])
        self.assertEqual(f.p.instantaneo(f.t).pan_vel, 0.0, "movimento latest-wins nao apagou o evento")

    def test_evento_expirado_nao_e_entregue(self):
        f = Fluxo(validade_evento_s=0.5)
        f.armar()
        f.t += 0.004
        f.p.iteracao(f.t)
        f.p.relatorio(R["quadrado"], f.t)
        self.assertEqual(f.p.retirar_eventos(f.t + 0.6), [])

    def test_pausa_800ms_com_backlog_de_quadrado(self):
        f = Fluxo()
        f.armar()
        f.enviar(R["cruz"], n=2)
        f.enviar(NEUTRO, n=5)
        epoch0 = f.p.input_epoch
        self.assertEqual(f.tipos(), ["cruz"])
        # Pausa: a thread nao itera por 800 ms; o driver acumula pressoes/solturas.
        f.t += 0.8
        backlog = [R["quadrado"], NEUTRO] * 50 + [R["esquerda"]] * 20
        f.p.iteracao(f.t)
        for d in backlog:
            f.p.relatorio(d, f.t)  # timestamps de leitura NOVOS, dados antigos
        imediatos = [e.tipo for e in f.p.retirar_eventos(f.t)]
        self.assertEqual(imediatos, ["descontinuidade"], "nenhum evento do backlog; so o aviso de descontinuidade")
        self.assertNotEqual(f.p.input_epoch, epoch0)
        self.assertEqual(f.p.estado, "RESSINCRONIZACAO")
        self.assertFalse(f.p.instantaneo(f.t).saudavel(f.t))
        self.assertEqual(f.p.instantaneo(f.t).pan_vel, 0.0, "eixo antigo nao vira deslocamento")
        self.assertTrue(f.p.precisa_drenar)
        # Adaptador drena ate vazio e declara a fronteira.
        f.p.fronteira_vazia(f.t)
        self.assertEqual(f.p.estado, "ARMANDO")
        self.assertTrue(f.p.exige_nova_selecao_manual)
        f.enviar(R["quadrado"], n=3)
        self.assertEqual(f.tipos(), ["cruz"], "Quadrado do novo fluxo nao arma nem dispara")
        f.enviar(NEUTRO, n=80)
        self.assertTrue(f.p.armada)

    def test_drenagem_limitada(self):
        f = Fluxo()
        f.armar()
        f.t += 0.3
        f.p.iteracao(f.t)
        self.assertEqual(f.p.estado, "RESSINCRONIZACAO")

        class Dev:
            def __init__(self):
                self.lidos = 0

            def ler_sem_espera(self):
                self.lidos += 1
                return NEUTRO  # nunca esvazia

        d = Dev()
        ok = entrada.drenar(d, f.p, relogio=lambda: f.t, max_relatorios=4096, max_s=0.1)
        self.assertFalse(ok)
        self.assertEqual(d.lidos, 4096)
        self.assertEqual(f.p.estado, "RESSINCRONIZACAO")
        self.assertFalse(f.p.armada)

        class Vazio:
            def __init__(self):
                self.n = 3

            def ler_sem_espera(self):
                self.n -= 1
                return NEUTRO if self.n > 0 else None

        self.assertTrue(entrada.drenar(Vazio(), f.p, relogio=lambda: f.t))
        self.assertEqual(f.p.estado, "ARMANDO")

    def test_hid_congelado_nao_e_saudavel(self):
        f = Fluxo()
        f.armar()
        # Thread viva (itera), mas sem relatorio valido por > 500 ms.
        for _ in range(60):
            f.t += 0.01
            f.p.iteracao(f.t)
        self.assertFalse(f.p.instantaneo(f.t).saudavel(f.t))

    def test_relatorio_invalido_nao_renova_saude(self):
        f = Fluxo()
        f.armar()
        for _ in range(60):
            f.t += 0.01
            f.p.iteracao(f.t)
            f.p.relatorio(b"\x31" + NEUTRO[1:], f.t)
        self.assertFalse(f.p.instantaneo(f.t).saudavel(f.t))

    def test_overflow_desarma_e_reserva_cancelamento(self):
        f = Fluxo(capacidade_eventos=4)
        f.armar()
        for _ in range(3):  # 3 eventos nao retirados
            f.t += 0.004
            f.p.iteracao(f.t)
            f.p.relatorio(R["triangulo"], f.t)
            f.t += 0.004
            f.p.iteracao(f.t)
            f.p.relatorio(NEUTRO, f.t)
        f.t += 0.004
        f.p.iteracao(f.t)
        f.p.relatorio(R["circulo"], f.t)  # cabe na reserva
        tipos = [e.tipo for e in f.p.retirar_eventos(f.t)]
        self.assertEqual(tipos.count("circulo"), 1)
        f2 = Fluxo(capacidade_eventos=4)
        f2.armar()
        for _ in range(4):
            for d in (R["triangulo"], NEUTRO):
                f2.t += 0.004
                f2.p.iteracao(f2.t)
                f2.p.relatorio(d, f2.t)
        self.assertFalse(f2.p.armada, "overflow desarma")
        self.assertNotIn("triangulo", [e.tipo for e in f2.p.retirar_eventos(f2.t)], "fila descartada, nao repetida")

    def test_perda_e_reconexao(self):
        f = Fluxo()
        f.armar()
        e0 = f.p.input_epoch
        f.p.perda("erro_leitura", f.t)
        self.assertNotEqual(f.p.input_epoch, e0)
        self.assertFalse(f.p.armada)
        self.assertTrue(f.p.exige_nova_selecao_manual)
        f.p.fronteira_vazia(f.t)
        f.enviar(R["direita"], n=50)
        f.enviar(R["quadrado"], n=50)
        self.assertFalse(f.p.armada)
        self.assertNotIn("quadrado", f.tipos())

    def test_velocidade_no_instantaneo(self):
        f = Fluxo()
        f.armar()
        f.enviar(R["esquerda"], n=2)
        s = f.p.instantaneo(f.t)
        self.assertEqual(s.pan_vel, 1.0)
        self.assertTrue(s.saudavel(f.t))
        self.assertEqual(s.input_epoch, f.p.input_epoch)
        self.assertGreater(s.seq, 0)

    def test_fronteira_de_combate_exige_neutro_sem_nova_selecao(self):
        f = Fluxo()
        f.armar()
        f.enviar(R["esquerda"], n=10)
        f.p.nova_fronteira("fim_combate", f.t, exige_selecao=False)
        self.assertEqual(f.p.estado, "RESSINCRONIZACAO")
        f.p.fronteira_vazia(f.t)
        f.enviar(R["esquerda"], n=200)  # analogico mantido desde o combate
        self.assertEqual(f.p.instantaneo(f.t).pan_vel, 0.0)
        self.assertFalse(f.p.armada)
        self.assertFalse(f.p.exige_nova_selecao_manual)
        f.enviar(NEUTRO, n=80)
        f.enviar(R["esquerda"], n=2)
        self.assertEqual(f.p.instantaneo(f.t).pan_vel, 1.0)


class TestImportSemEfeitos(unittest.TestCase):
    def test_importar_nao_abre_recursos(self):
        self.assertNotIn("hid", sys.modules, "parser/politica nao importam hid")


if __name__ == "__main__":
    unittest.main()
