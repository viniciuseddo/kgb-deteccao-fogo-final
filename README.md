# Detecção de Fogo, grupo KGB (FIAP + Sompo Seguros)

Sistema autônomo de detecção e combate a incêndio pensado para tratores em vias agrícolas. Uma ESP32-CAM filma, um modelo YOLO roda no notebook e decide se tem fogo, e um ESP32-S3 (ou Arduino Uno, na versão antiga) mira o Pan-Tilt, acende o LED e liga a bomba d'água.

```
ESP32-CAM  ->  USB ou Wi-Fi  ->  notebook (YOLO)  ->  Wi-Fi ou serial  ->  ESP32-S3 / Uno
 captura                          decide                                   servos, LED, bomba
```

## Estrutura

| Caminho | O que é |
|---|---|
| `sistema_vigia.py` | Sistema atual. Lê a ESP32-CAM pela USB, roda o YOLO11 de chama e dispara no ESP32-S3 por Wi-Fi. Grava as ocorrências no SQLite |
| `dashboard.py` + `banco.py` | Painel de alertas em http://localhost:8060, lendo o banco `dados/deteccoes.db` |
| `reprocessar.py` | Roda o modelo em cima de gravações já feitas (pasta `tomadas/`) |
| `sistema_completo.py` | Versão anterior: ESP32-CAM por Wi-Fi + Arduino Uno pela serial (comandos L/C/R/F) |
| `sistema_rastreio.py` | Variante em que o Pan-Tilt persegue o alvo continuamente |
| `detect_fire.py` | Detecção com webcam USB ou celular |
| `esp_yolo_test.py`, `detectar_esp.py` | Testes só de câmera + detecção, sem hardware |
| `coletar*.py`, `gravar_tomadas.py`, `montar_video.py` | Coleta de imagens e vídeos com a ESP32-CAM para treino |
| `preparar_pacote.py`, `pacote_gui.py`, `INSTRUCOES_FINETUNING.md` | Pacote de dados para o fine tuning |
| `achar_camera.py`, `esperar_camera.py` | Acham o IP da ESP32-CAM na rede |
| `arduino/` | Sketches das placas (ESP32-CAM, ESP32-S3, Arduino Uno) |
| `kit_captura_esp32cam/` | Captura pela USB com interface web (localhost:5005) |
| `kit_teste_esp32cam/` | Teste do modelo de chama em cima da ESP32-CAM |
| `modelos/best_dfire.pt` | YOLOv8n treinado no D-Fire (classes 0 Smoke, 1 Fire) |
| `kit_teste_esp32cam/chama_yolo11n_best.pt` | YOLO11n de chama pequena, uma classe `chama`. É o modelo em uso |

O modelo antigo `modelos/best.pt` (64MB, Hugging Face) não vai no repositório. Quem quiser usar roda `baixar_modelo.py`.

## Preparar a máquina (Windows)

Python 3.10 ou mais novo, com "Add Python to PATH" marcado na instalação.

```
cd C:\projetos
git clone https://github.com/viniciuseddo/deteccao-fogo.git
cd C:\projetos\deteccao-fogo
python -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
```

Os `.bat` esperam o projeto em `C:\projetos\deteccao-fogo`. Se o PowerShell bloquear o `activate` da venv, não precisa ativar, é só chamar `.\venv\Scripts\python.exe` direto como acima.

## Como rodar

Sistema atual (troque o IP pelo que o ESP32-S3 imprime na serial):

```
cd C:\projetos\deteccao-fogo
.\venv\Scripts\python.exe sistema_vigia.py --ip 192.168.0.17 --salvar
```

Ou dois cliques em `INICIAR_VIGIA.bat` (editar o `IP_S3` dentro dele) e `INICIAR_DASHBOARD.bat` para o painel.

Na janela de vídeo: `q` sai, `f` dispara manual, `r` gira a imagem, `+` e `-` mudam o limiar.

Versão com Arduino Uno pela serial:

```
cd C:\projetos\deteccao-fogo
.\venv\Scripts\python.exe sistema_completo.py IP_DA_ESP --porta COM8
```

## Sketches

Os sketches com Wi-Fi estão com `COLOQUE_O_NOME_DA_REDE` / `COLOQUE_A_SENHA`. Preencha antes de gravar. A rede tem que ser 2.4GHz (no iPhone, ligar "Maximizar Compatibilidade" no roteamento).

Na Arduino IDE: pacote `esp32 by Espressif Systems`, bibliotecas `LiquidCrystal I2C` (Frank de Brabander) e `ESP32Servo`. ESP32-CAM: placa AI Thinker ESP32-CAM, partição Huge APP.

## Problemas conhecidos

- A ESP32-CAM atende um cliente por vez. Aba do navegador aberta no IP dela derruba o Python.
- Só um programa por vez em cada porta COM. Serial Monitor aberto bloqueia o script.
- Para ler a serial da ESP32-CAM sem jogar a placa em modo download: `.\venv\Scripts\python.exe -m serial.tools.miniterm --rts 0 --dtr 0 COM13 115200`

## Time

Vinicius Eddo, Rafael Jun Aita Hirata, Guilherme Orugian, Lucas Henrique e Rodrigo Bettio.
