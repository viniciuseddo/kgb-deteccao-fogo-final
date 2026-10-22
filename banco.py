"""
Banco de dados local do Vigia KGB
=================================

Guarda cada ocorrencia de fogo detectada pela IA em um SQLite local, em
dados/deteccoes.db. E esse banco que alimenta o dashboard de alertas.

Uma linha por deteccao confirmada, com:
    quando, confianca do modelo, angulo do servo no momento,
    acao tomada pelo atuador e o caminho da foto de prova.
"""

import os
import sqlite3
import threading
import time

BASE = os.path.dirname(os.path.abspath(__file__))
PASTA = os.path.join(BASE, "dados")
CAMINHO = os.path.join(PASTA, "deteccoes.db")

ESQUEMA = """
CREATE TABLE IF NOT EXISTS deteccoes (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            REAL    NOT NULL,
    data_hora     TEXT    NOT NULL,
    confianca     REAL    NOT NULL,
    angulo_pan    INTEGER,
    acao          TEXT    NOT NULL,
    duracao_bomba REAL,
    imagem        TEXT,
    origem        TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ts ON deteccoes(ts);

CREATE TABLE IF NOT EXISTS sessoes (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    inicio    TEXT NOT NULL,
    modelo    TEXT,
    limiar    REAL,
    ip_atuador TEXT
);
"""


class Banco:
    """Acesso ao SQLite. Seguro para chamar de varias threads."""

    def __init__(self, caminho=CAMINHO):
        os.makedirs(os.path.dirname(caminho), exist_ok=True)
        self.caminho = caminho
        self.lock = threading.Lock()
        self._criar()

    def _conn(self):
        c = sqlite3.connect(self.caminho, timeout=10)
        c.row_factory = sqlite3.Row
        return c

    def _criar(self):
        with self.lock, self._conn() as c:
            c.executescript(ESQUEMA)

    def abrir_sessao(self, modelo, limiar, ip):
        with self.lock, self._conn() as c:
            cur = c.execute(
                "INSERT INTO sessoes (inicio, modelo, limiar, ip_atuador) VALUES (?,?,?,?)",
                (time.strftime("%Y-%m-%d %H:%M:%S"), modelo, limiar, ip),
            )
            return cur.lastrowid

    def registrar(self, confianca, angulo_pan=None, acao="bomba acionada",
                  duracao_bomba=None, imagem=None, origem="ESP32-CAM"):
        agora = time.time()
        with self.lock, self._conn() as c:
            cur = c.execute(
                """INSERT INTO deteccoes
                   (ts, data_hora, confianca, angulo_pan, acao, duracao_bomba, imagem, origem)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (agora, time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(agora)),
                 float(confianca), angulo_pan, acao, duracao_bomba, imagem, origem),
            )
            return cur.lastrowid

    def ultimas(self, limite=50):
        with self.lock, self._conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT * FROM deteccoes ORDER BY id DESC LIMIT ?", (limite,))]

    def resumo(self):
        with self.lock, self._conn() as c:
            r = c.execute(
                """SELECT COUNT(*) AS total,
                          AVG(confianca) AS media,
                          MAX(confianca) AS maxima,
                          MAX(ts) AS ultimo_ts
                     FROM deteccoes""").fetchone()
            hoje = c.execute(
                "SELECT COUNT(*) AS n FROM deteccoes WHERE date(data_hora) = date('now','localtime')"
            ).fetchone()
            return {
                "total": r["total"] or 0,
                "media": round((r["media"] or 0) * 100, 1),
                "maxima": round((r["maxima"] or 0) * 100, 1),
                "ultimo_ts": r["ultimo_ts"],
                "hoje": hoje["n"] or 0,
            }


if __name__ == "__main__":
    b = Banco()
    print(f"banco em {b.caminho}")
    print("resumo:", b.resumo())
    for linha in b.ultimas(10):
        print(linha)
