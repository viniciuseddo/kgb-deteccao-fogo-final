from flask import Flask, request

app = Flask(__name__)

@app.route("/status", methods=["POST"])
def status():
    dados = request.get_json(silent=True) or {}
    print("Recebido do ESP32:", dados)
    return {"ok": True}

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)