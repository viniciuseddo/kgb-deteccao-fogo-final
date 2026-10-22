"""
Dashboard de alertas do Vigia KGB
=================================

Servidor HTTP local que le o SQLite alimentado pelo sistema_vigia.py e
mostra os alertas em tempo real. Abre em http://localhost:8060

    py dashboard.py
    py dashboard.py --porta 8060
"""

import argparse
import json
import mimetypes
import os
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from banco import Banco, BASE

banco = Banco()

PAGINA = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Vigia KGB - Alertas</title>
<style>
  :root{
    --bg:#0d1117; --card:#161b22; --linha:#21262d;
    --txt:#e6edf3; --fraco:#8b949e; --fogo:#f85149; --ok:#3fb950; --dest:#d29922;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--txt);
       font-family:-apple-system,Segoe UI,Roboto,sans-serif}
  header{padding:20px 24px;border-bottom:1px solid var(--linha);
         display:flex;align-items:center;gap:14px;flex-wrap:wrap}
  h1{font-size:19px;margin:0;font-weight:600;letter-spacing:-.2px}
  .sub{color:var(--fraco);font-size:13px}
  .pulso{width:9px;height:9px;border-radius:50%;background:var(--ok);
         box-shadow:0 0 0 0 rgba(63,185,80,.7);animation:p 2s infinite}
  @keyframes p{70%{box-shadow:0 0 0 9px rgba(63,185,80,0)}
               100%{box-shadow:0 0 0 0 rgba(63,185,80,0)}}
  main{padding:24px;max-width:1120px;margin:0 auto}
  .tiles{display:grid;gap:14px;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));
         margin-bottom:24px}
  .tile{background:var(--card);border:1px solid var(--linha);border-radius:10px;padding:16px 18px}
  .rot{color:var(--fraco);font-size:11px;text-transform:uppercase;letter-spacing:.7px}
  .val{font-size:30px;font-weight:650;margin-top:6px;font-variant-numeric:tabular-nums}
  .val.fogo{color:var(--fogo)}
  .val.dest{color:var(--dest)}
  .grid{display:grid;gap:18px;grid-template-columns:1fr}
  @media(min-width:900px){.grid{grid-template-columns:1.5fr 1fr}}
  .painel{background:var(--card);border:1px solid var(--linha);border-radius:10px;overflow:hidden}
  .cab{padding:13px 18px;border-bottom:1px solid var(--linha);font-size:13px;
       font-weight:600;color:var(--fraco);text-transform:uppercase;letter-spacing:.6px}
  table{width:100%;border-collapse:collapse;font-size:13.5px}
  th{text-align:left;padding:9px 18px;color:var(--fraco);font-weight:500;font-size:11.5px;
     text-transform:uppercase;letter-spacing:.5px;border-bottom:1px solid var(--linha)}
  td{padding:11px 18px;border-bottom:1px solid var(--linha);font-variant-numeric:tabular-nums}
  tr:last-child td{border-bottom:none}
  tr.nova{animation:e 2.5s ease-out}
  @keyframes e{0%{background:rgba(248,81,73,.28)}100%{background:transparent}}
  .tag{display:inline-block;padding:2.5px 9px;border-radius:20px;font-size:11.5px;font-weight:600}
  .tag.fogo{background:rgba(248,81,73,.16);color:var(--fogo)}
  .vazio{padding:38px 18px;text-align:center;color:var(--fraco);font-size:14px}
  .prova{padding:14px}
  .prova img{width:100%;border-radius:7px;display:block;border:1px solid var(--linha)}
  .prova p{color:var(--fraco);font-size:12.5px;margin:10px 2px 2px}
  footer{padding:18px 24px;color:var(--fraco);font-size:12px;text-align:center}
</style>
</head>
<body>
<header>
  <span class="pulso"></span>
  <h1>Vigia KGB</h1>
  <span class="sub">Painel de alertas de incendio &middot; SOMPO</span>
</header>
<main>
  <div class="tiles">
    <div class="tile"><div class="rot">Ocorrencias totais</div><div class="val fogo" id="total">0</div></div>
    <div class="tile"><div class="rot">Hoje</div><div class="val" id="hoje">0</div></div>
    <div class="tile"><div class="rot">Confianca media</div><div class="val dest" id="media">0%</div></div>
    <div class="tile"><div class="rot">Ultimo alerta</div><div class="val" id="ultimo" style="font-size:20px">nenhum</div></div>
  </div>
  <div class="grid">
    <div class="painel">
      <div class="cab">Historico de alertas</div>
      <div id="tabela"><div class="vazio">Nenhuma ocorrencia registrada ainda.</div></div>
    </div>
    <div class="painel">
      <div class="cab">Ultima evidencia</div>
      <div class="prova" id="prova"><div class="vazio">Sem imagem.</div></div>
    </div>
  </div>
</main>
<footer>Dados lidos de dados/deteccoes.db &middot; atualiza a cada 2 segundos</footer>
<script>
let vistos = new Set();
let primeira = true;

function quando(ts){
  if(!ts) return 'nenhum';
  const s = Math.floor(Date.now()/1000 - ts);
  if(s < 60) return 'ha ' + s + 's';
  if(s < 3600) return 'ha ' + Math.floor(s/60) + 'min';
  return 'ha ' + Math.floor(s/3600) + 'h';
}

async function atualizar(){
  let d;
  try { d = await (await fetch('/api/dados')).json(); } catch(e){ return; }

  document.getElementById('total').textContent = d.resumo.total;
  document.getElementById('hoje').textContent  = d.resumo.hoje;
  document.getElementById('media').textContent = d.resumo.media + '%';
  document.getElementById('ultimo').textContent = quando(d.resumo.ultimo_ts);

  const alvo = document.getElementById('tabela');
  if(!d.linhas.length){
    alvo.innerHTML = '<div class="vazio">Nenhuma ocorrencia registrada ainda.</div>';
  } else {
    let h = '<table><thead><tr><th>#</th><th>Data e hora</th><th>Confianca</th>'
          + '<th>Angulo</th><th>Acao</th></tr></thead><tbody>';
    for(const l of d.linhas){
      const nova = !primeira && !vistos.has(l.id) ? ' class="nova"' : '';
      vistos.add(l.id);
      h += `<tr${nova}><td>${l.id}</td><td>${l.data_hora}</td>`
         + `<td><span class="tag fogo">${Math.round(l.confianca*100)}%</span></td>`
         + `<td>${l.angulo_pan ?? '-'}&deg;</td><td>${l.acao}</td></tr>`;
    }
    alvo.innerHTML = h + '</tbody></table>';
  }
  primeira = false;

  const p = document.getElementById('prova');
  if(d.imagem){
    const url = '/' + d.imagem.replace(/\\\\/g,'/') + '?v=' + d.resumo.ultimo_ts;
    if(!p.dataset.url || p.dataset.url !== url){
      p.dataset.url = url;
      p.innerHTML = `<img src="${url}" alt="evidencia"><p>${d.linhas[0].data_hora}</p>`;
    }
  }
}
atualizar();
setInterval(atualizar, 2000);
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _enviar(self, corpo, tipo="text/html; charset=utf-8", codigo=200):
        if isinstance(corpo, str):
            corpo = corpo.encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(corpo)

    def do_GET(self):
        caminho = urlparse(self.path).path

        if caminho in ("/", "/index.html"):
            return self._enviar(PAGINA)

        if caminho == "/api/dados":
            linhas = banco.ultimas(30)
            dados = {
                "resumo": banco.resumo(),
                "linhas": linhas,
                "imagem": linhas[0]["imagem"] if linhas else None,
            }
            return self._enviar(json.dumps(dados), "application/json")

        # serve as fotos de prova da pasta disparos
        if caminho.startswith("/disparos/"):
            rel = caminho.lstrip("/").replace("/", os.sep)
            arq = os.path.normpath(os.path.join(BASE, rel))
            if arq.startswith(os.path.join(BASE, "disparos")) and os.path.isfile(arq):
                tipo = mimetypes.guess_type(arq)[0] or "application/octet-stream"
                with open(arq, "rb") as f:
                    return self._enviar(f.read(), tipo)

        self._enviar("nao encontrado", "text/plain; charset=utf-8", 404)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--porta", type=int, default=8060)
    p.add_argument("--sem-abrir", action="store_true")
    a = p.parse_args()

    url = f"http://localhost:{a.porta}"
    print("=" * 60)
    print(" DASHBOARD DE ALERTAS - VIGIA KGB")
    print("=" * 60)
    print(f" banco: {banco.caminho}")
    print(f" abra:  {url}")
    print(" Ctrl+C para encerrar")
    print()

    if not a.sem_abrir:
        try:
            webbrowser.open(url)
        except Exception:
            pass

    ThreadingHTTPServer(("0.0.0.0", a.porta), Handler).serve_forever()


if __name__ == "__main__":
    main()
