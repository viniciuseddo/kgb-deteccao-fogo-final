"""Registro JSONL de comandos/decisoes do controle, separado das deteccoes.

Nenhum estado aqui prova fluxo fisico de agua: 'aceito' e aceitacao logica
pelo firmware. Nao grava numero de serie do controle nem outro identificador
pessoal.
"""

import json
import os
import threading
import time

CAMPOS_PROIBIDOS = {"serial_number", "serial", "numero_serie", "path"}


class RegistroJSONL:
    def __init__(self, caminho):
        self.caminho = caminho
        self.lock = threading.Lock()
        d = os.path.dirname(caminho)
        if d:
            os.makedirs(d, exist_ok=True)

    def escrever(self, evento, **campos):
        for k in CAMPOS_PROIBIDOS & set(campos):
            campos.pop(k)
        linha = {"ts": round(time.time(), 3), "t_mono": round(time.monotonic(), 3), "evento": evento}
        linha.update(campos)
        texto = json.dumps(linha, ensure_ascii=False, default=str)
        with self.lock:
            with open(self.caminho, "a", encoding="utf-8") as f:
                f.write(texto + "\n")


def acao_deteccao(resultado, motivo):
    """Texto do campo 'acao' da tabela deteccoes no caminho novo.
    Reflete a decisao real; nunca afirma agua fisica."""
    if resultado == "aceito":
        return "agua aceita pelo firmware (logico)"
    if resultado == "recusado":
        return f"agua recusada: {motivo or 'sem motivo'}"
    if resultado == "descartado":
        return f"agua nao solicitada: {motivo or 'descartada'}"
    return "agua com resultado desconhecido"
