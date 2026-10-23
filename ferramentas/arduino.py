"""Arduino CLI portatil para o firmware do Vigia (ESP32-S3 N16R8).

Tudo fica em .tmp/arduino/ (ignorado pelo Git): executavel, core, bibliotecas,
downloads, TEMP do processo e builds. Nada e instalado globalmente.

Uso (sempre pelo venv):
  .\\venv\\Scripts\\python.exe ferramentas\\arduino.py instalar
  .\\venv\\Scripts\\python.exe ferramentas\\arduino.py versoes
  .\\venv\\Scripts\\python.exe ferramentas\\arduino.py compilar [--original] [--wifi]
  .\\venv\\Scripts\\python.exe ferramentas\\arduino.py gravar --porta COM7 [--original]

--wifi: copia o sketch para .tmp/arduino/sketches/ e grava ao lado dele um
segredos_wifi.h com SSID/senha lidos de .tmp/segredos_wifi.json
({"ssid": "...", "senha": "..."}). O sketch versionado nunca recebe a senha.
Sem --wifi a compilacao usa os placeholders (controle de compilacao apenas).
"""

import argparse
import json
import os
import shutil
import subprocess
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE_LOCAL = os.path.join(os.environ.get("LOCALAPPDATA", ""), "arduino_portatil")
BASE = BASE_LOCAL if os.path.exists(os.path.join(BASE_LOCAL, "arduino-cli.exe")) else os.path.join(RAIZ, ".tmp", "arduino")
CLI = os.path.join(BASE, "arduino-cli.exe")
SEGREDOS_JSON = os.path.join(RAIZ, ".tmp", "segredos_wifi.json")

# Versoes fixadas (registradas em evidencias/ferramentas_arduino.md).
CORE = "esp32:esp32@3.3.12"
BIBLIOTECAS = ["ESP32Servo@3.2.1", "LiquidCrystal I2C@1.1.2"]
URL_INDICE = "https://espressif.github.io/arduino-esp32/package_esp32_index.json"

# ESP32-S3 N16R8: 16 MB flash, PSRAM octal. Particao grande sem OTA (3 MB app).
FQBN = ("esp32:esp32:esp32s3:FlashSize=16M,PSRAM=opi,PartitionScheme=app3M_fat9M_16MB,"
        "FlashMode=qio,CDCOnBoot=default,USBMode=hwcdc,UploadSpeed=921600")

SKETCHES = {
    "dualsense": os.path.join(RAIZ, "arduino", "esp32s3_vigia_dualsense"),
    "original": os.path.join(RAIZ, "arduino", "esp32s3_vigia_bomba"),
}


def ambiente():
    env = dict(os.environ)
    for d in ("data", "user", "temp", "downloads", "build", "sketches"):
        os.makedirs(os.path.join(BASE, d), exist_ok=True)
    env["ARDUINO_DIRECTORIES_DATA"] = os.path.join(BASE, "data")
    env["ARDUINO_DIRECTORIES_USER"] = os.path.join(BASE, "user")
    env["ARDUINO_DIRECTORIES_DOWNLOADS"] = os.path.join(BASE, "downloads")
    env["ARDUINO_BOARD_MANAGER_ADDITIONAL_URLS"] = URL_INDICE
    env["ARDUINO_UPDATER_ENABLE_NOTIFICATION"] = "false"
    env["ARDUINO_BUILD_CACHE_PATH"] = os.path.join(BASE, "build", "cache")
    env["TEMP"] = env["TMP"] = os.path.join(BASE, "temp")
    return env


def cli(*args, verificar=True):
    if not os.path.exists(CLI):
        sys.exit(f"arduino-cli ausente em {CLI} (ver evidencias/ferramentas_arduino.md)")
    print(">", "arduino-cli", " ".join(args), flush=True)
    r = subprocess.run([CLI, *args], env=ambiente())
    if verificar and r.returncode != 0:
        sys.exit(r.returncode)
    return r.returncode


def instalar():
    cli("core", "update-index")
    cli("core", "install", CORE)
    for b in BIBLIOTECAS:
        cli("lib", "install", b)


def versoes():
    cli("version")
    cli("core", "list")
    cli("lib", "list")


def preparar_sketch(nome, wifi):
    origem = SKETCHES[nome]
    if not wifi:
        return origem
    if nome != "dualsense":
        sys.exit("--wifi so e suportado na variante dualsense (o original tem SSID/senha no proprio .ino)")
    try:
        with open(SEGREDOS_JSON, encoding="utf-8") as f:
            seg = json.load(f)
        ssid, senha = seg["ssid"], seg["senha"]
    except (OSError, KeyError, ValueError) as e:
        sys.exit(f"segredos invalidos em {SEGREDOS_JSON}: {e}")
    destino = os.path.join(BASE, "sketches", os.path.basename(origem))
    shutil.rmtree(destino, ignore_errors=True)
    shutil.copytree(origem, destino)

    def c_str(s):
        return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'

    with open(os.path.join(destino, "segredos_wifi.h"), "w", encoding="utf-8") as f:
        f.write("// GERADO por ferramentas/arduino.py a partir de .tmp/segredos_wifi.json. NAO versionar.\n")
        f.write(f"#define VIGIA_WIFI_SSID {c_str(ssid)}\n#define VIGIA_WIFI_SENHA {c_str(senha)}\n")
    return destino


def compilar(nome, wifi, saida=None):
    sketch = preparar_sketch(nome, wifi)
    saida = saida or os.path.join(BASE, "build", nome + ("_wifi" if wifi else ""))
    cli("compile", "--fqbn", FQBN, "--warnings", "default", "--verbose", "--output-dir", saida,
        "--build-path", saida + "_tmp", sketch)
    return sketch, saida


def gravar(nome, wifi, porta):
    sketch, saida = compilar(nome, wifi)
    cli("upload", "--fqbn", FQBN, "-p", porta, "--input-dir", saida, sketch)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="acao", required=True)
    sub.add_parser("instalar")
    sub.add_parser("versoes")
    c = sub.add_parser("compilar")
    c.add_argument("--original", action="store_true")
    c.add_argument("--wifi", action="store_true")
    g = sub.add_parser("gravar")
    g.add_argument("--porta", required=True)
    g.add_argument("--original", action="store_true")
    g.add_argument("--wifi", action="store_true")
    a = ap.parse_args()
    nome = "original" if getattr(a, "original", False) else "dualsense"
    if a.acao == "instalar":
        instalar()
    elif a.acao == "versoes":
        versoes()
    elif a.acao == "compilar":
        compilar(nome, a.wifi)
    else:
        gravar(nome, a.wifi, a.porta)


if __name__ == "__main__":
    main()
