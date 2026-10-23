"""Parser puro dos relatorios USB do DualSense (spec dualsense-input).

Mapeamento medido (offsets base zero, byte 0 = report ID):
  byte 1: analogico esquerdo horizontal, 0 esquerda / ~128 repouso / 255 direita
  byte 8: mascaras Cruz 0x20, Triangulo 0x80, Quadrado 0x10, Circulo 0x40
"""

from dataclasses import dataclass

VID = 0x054C
PID = 0x0CE6
USAGE_PAGE = 0x01
USAGE = 0x05
RELATORIO_ID = 0x01
TAMANHO = 64

BYTE_EIXO_X = 1
BYTE_BOTOES = 8
CRUZ = 0x20
TRIANGULO = 0x80
QUADRADO = 0x10
CIRCULO = 0x40

ZONA_MORTA_PADRAO = 0.10


@dataclass(frozen=True)
class Relatorio:
    eixo_bruto: int
    cruz: bool
    triangulo: bool
    quadrado: bool
    circulo: bool

    @property
    def algum_botao(self):
        return self.cruz or self.triangulo or self.quadrado or self.circulo


def interpretar(dados):
    """Relatorio valido ou None. Aceita bytes/bytearray/lista de ints (hidapi)."""
    if dados is None:
        return None
    try:
        b = bytes(dados)
    except (TypeError, ValueError):
        return None
    if len(b) != TAMANHO or b[0] != RELATORIO_ID:
        return None
    m = b[BYTE_BOTOES]
    return Relatorio(
        eixo_bruto=b[BYTE_EIXO_X],
        cruz=bool(m & CRUZ),
        triangulo=bool(m & TRIANGULO),
        quadrado=bool(m & QUADRADO),
        circulo=bool(m & CIRCULO),
    )


def normalizar_eixo(v):
    """Assimetrico em torno de 128: 0 -> -1, 128 -> 0, 255 -> +1."""
    if v < 128:
        return (v - 128) / 128.0
    return (v - 128) / 127.0


def aplicar_zona_morta(x, zona=ZONA_MORTA_PADRAO):
    a = abs(x)
    if a <= zona:
        return 0.0
    y = (a - zona) / (1.0 - zona)
    y = min(1.0, y)
    return y if x > 0 else -y


def velocidade_pan(rel, zona=ZONA_MORTA_PADRAO):
    """Fracao da velocidade maxima. Angulo maior = esquerda no firmware, entao
    eixo negativo (esquerda) -> velocidade PAN positiva. Sentido fisico a
    confirmar em bancada."""
    return -aplicar_zona_morta(normalizar_eixo(rel.eixo_bruto), zona) + 0.0


@dataclass(frozen=True)
class Selecao:
    path: object
    interface: object
    motivo: object

    def __repr__(self):  # nunca expoe numero de serie
        return f"Selecao(interface={self.interface!r}, motivo={self.motivo!r})"


def selecionar(candidatos):
    """Escolhe exatamente um DualSense USB de gamepad; zero ou varios -> motivo."""
    ok = [c for c in candidatos
          if c.get("vendor_id") == VID and c.get("product_id") == PID
          and c.get("usage_page") == USAGE_PAGE and c.get("usage") == USAGE]
    if not ok:
        return Selecao(None, None, "dualsense_ausente")
    if len(ok) > 1:
        return Selecao(None, None, "dualsense_ambiguo")
    return Selecao(ok[0].get("path"), ok[0].get("interface_number"), None)
