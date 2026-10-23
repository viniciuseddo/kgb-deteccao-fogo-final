# Guia do Agente: Detecção de Incêndio Agrícola (KGB - Sompo Seguros / FIAP)

> **Propósito deste documento:** Permitir que qualquer agente ou desenvolvedor assuma imediatamente a manutenção, testes e evolução deste projeto sem precisar ler ou analisar todos os arquivos do repositório.

---

## 1. Visão Geral do Sistema

Sistema autônomo embarcado voltado para tratores e maquinário agrícola para detectar e combater princípios de incêndio em lavouras e vias agrícolas.

### Fluxo Operacional:
```
[ ESP32-CAM ] (Captura de vídeo via USB serial a 460800 baud)
       │ (Quadros JPEG delimitados por marcador binário 0xAA 0x55 0xAA 0x55)
       ▼
[ Notebook / Servidor ] (Inferência YOLO11 em tempo real)
       │ - Analisa frames, aplica threshold de confiança e debounce de quadros
       │ - Grava eventos e imagens em SQLite (`dados/deteccoes.db`)
       │ - Dispara requisições HTTP REST via Wi-Fi para o atuador
       ▼
[ ESP32-S3 ] (Atuador mecânico e elétrico)
       │ - Recebe requisições: `/cmd?c=L|C|R|F` e `/status`
       │ - Mira o servo PAN (um eixo; tilt desativado), acende LED e aciona bomba via relé
       │ *Obs: Uso de Wi-Fi no S3 isola o ruído eletromagnético da bomba que derrubava a USB*
       ▼
[ Dashboard Web ] (`dashboard.py` -> http://localhost:8060)
       - Exibe alertas em tempo real, fotos dos focos de incêndio, estatísticas e ângulos.
```

---

## 2. Ambiente de Execução e Python Virtualenv

O ambiente virtual isolado já está configurado na raiz: `.\venv` (Python 3.11).

- **Interpretador:** `.\venv\Scripts\python.exe`
- **Pip:** `.\venv\Scripts\pip.exe`
- **Todas as dependências instaladas:**
  - `ultralytics>=8.3.0` (YOLO11 / YOLOv8)
  - `torch` & `torchvision`
  - `opencv-python` (OpenCV)
  - `numpy`, `pyserial`, `flask`, `requests`, `huggingface_hub`, `matplotlib`

> **Nota técnica sobre Windows Sandbox:** Caso execute scripts de instalação via pip no ambiente confinado, foi inserido o utilitário `sitecustomize.py` para compatibilizar chamadas de criação de diretórios temporários com os descritores de segurança do Windows.

---

## 3. Principais Modelos de Visão Computacional

1. **`kit_teste_esp32cam/chama_yolo11n_best.pt` (MODELO ATUAL / PADRÃO)**
   - Arquitetura: YOLO11n
   - Classes: 1 classe (`0: chama`)
   - Otimizado especificamente para detecção precoce de focos de chama em resolução típica da ESP32-CAM.
2. **`modelos/best_dfire.pt` (MODELO ALTERNATIVO)**
   - Arquitetura: YOLOv8n treinado no dataset D-Fire
   - Classes: 2 classes (`0: Smoke`, `1: Fire`)
3. **`baixar_modelo.py`**
   - Faz o download do modelo histórico legado de 64MB do Hugging Face para `modelos/best.pt`, se necessário.

---

## 4. Mapa Sintético dos Arquivos e Módulos

| Arquivo / Diretório | Responsabilidade |
|---|---|
| `sistema_vigia.py` | **Script principal do sistema ativo.** Lê frames da ESP32-CAM via porta serial USB (`CameraSerial`), roda inferência com YOLO11, envia comandos HTTP para o ESP32-S3 (`ControleS3`) e salva detecções no SQLite via `banco.py`. |
| `dashboard.py` | Servidor HTTP nativo na porta 8060 exibindo a interface web de monitoramento, fotos das evidências e histórico do banco. |
| `banco.py` | Camada SQLite para o banco `dados/deteccoes.db` (tabelas `deteccoes` e `sessoes`). Gerencia imagens salvas e concorrência multithread. |
| `reprocessar.py` | Reprocessa arquivos `.mp4` gravados na pasta `tomadas/` com o modelo YOLO para validar acurácia offline sem hardware. |
| `sistema_completo.py` | Versão anterior/legada do sistema usando ESP32-CAM por Wi-Fi e Arduino Uno via porta Serial COM. |
| `sistema_rastreio.py` | Variante com loop PID/contínuo para os servos do Pan-Tilt acompanharem o fogo no centro do quadro. |
| `detect_fire.py` | Script de teste rápido usando webcam local do notebook ou celular via RTSP/HTTP. |
| `coletar*.py` / `gravar_tomadas.py` | Scripts auxiliares de gravação de imagens e vídeos pela ESP32-CAM para geração de datasets. |
| `arduino/esp32s3_vigia_bomba/` | Firmware validado do ESP32-S3 (servidor web HTTP, um servo PAN com `USAR_TILT = false` e relé da bomba d'água). Referência e rollback. |
| `arduino/esp32s3_vigia_dualsense/` | Variante opt-in para o controle DualSense (guardião único da bomba, lease, protocolo protegido). Ver `openspec/changes/controle-dualsense-vigia/IMPLEMENTACAO.md`. |
| `arduino/esp32cam_coleta_universal/` | Único sketch do repositório que envia JPEG pela USB com marcador `AA 55 AA 55` a 460800 baud. Qual imagem está gravada na câmera não foi confirmado. (`esp32cam_captura_v2/` é, apesar do nome, um sketch de Arduino Uno com servo, sem câmera.) |
| `arduino/arduino_uno_pantilt_bomba/`| Firmware legado para Arduino Uno via comandos de 1 byte pela serial (`L`, `C`, `R`, `F`). |
| `kit_captura_esp32cam/` | Mini app Flask com GUI web para calibrar foco e capturar amostras da ESP32-CAM na porta 5005. |
| `kit_teste_esp32cam/` | Scripts de bancada para testar a taxa de quadros e inferência diretamente pela USB. |

---

## 5. Como Executar os Módulos

### 5.1. Executar o Sistema Vigia Completo
```powershell
# Com IP do ESP32-S3 descoberto na rede local (2.4GHz):
.\venv\Scripts\python.exe sistema_vigia.py --ip 192.168.0.17 --salvar

# Parâmetros úteis:
#   --ip IP         (Obrigatório) IP do ESP32-S3
#   --porta COMx    (Opcional) Porta COM da ESP32-CAM (detecta automaticamente CH340/CP210)
#   --conf 0.45     Limiar de confiança (padrão: 0.45)
#   --frames 3      Quantidade de frames seguidos com fogo para confirmar disparo (filtra falso positivo)
#   --cooldown 12.0 Segundos de espera entre disparos da bomba d'água
```
*Atalhos na janela gráfica do vídeo:*
- `q` ou `ESC`: Encerra o sistema.
- `f`: Disparo manual imediato de teste (aciona bomba/LED).
- `r`: Gira o enquadramento em 90 graus.
- `+` / `-`: Aumenta ou diminui o limiar de confiança em tempo real.

### 5.2. Iniciar o Painel de Alertas (Dashboard)
```powershell
.\venv\Scripts\python.exe dashboard.py --porta 8060
# Acesse no navegador: http://localhost:8060
```

### 5.3. Reprocessar Gravações Offline
```powershell
# Listar estatísticas de ocorrências em vídeos salvos na pasta tomadas/:
.\venv\Scripts\python.exe reprocessar.py --listar

# Rodar inferência sobre um vídeo gravado específico:
.\venv\Scripts\python.exe reprocessar.py --video tomadas/tomada_01.mp4
```

---

## 6. Cuidados e Armadilhas Conhecidas (Gotchas)

1. **Conflito de Porta Serial (COM):**
   - O Windows só permite que um processo abra a porta COM por vez. Se a IDE do Arduino estiver com o *Serial Monitor* aberto na COM da ESP32-CAM, o Python falhará ao conectar.
2. **Ruído da Bomba D'água:**
   - A bomba opera em 5V/12V através de relé mecânico e gera pico de indução eletromagnética. Por isso o ESP32-S3 foi desacoplado da USB e opera puramente via Wi-Fi. Nunca alimente a bomba diretamente do barramento USB do computador.
3. **Rede Wi-Fi:**
   - Microcontroladores ESP32 suportam apenas redes Wi-Fi **2.4 GHz**. Em pontos de acesso de smartphone (iPhone/Android), ative a opção "Maximizar Compatibilidade".
4. **Caminhos nos arquivos `.bat` legados:**
   - Os arquivos `.bat` (`INICIAR_VIGIA.bat`, etc.) vinham com `C:\projetos\deteccao-fogo` pré-configurado. Ao executar neste workspace (`C:\Users\orugi\Documents\Projetos\KGB-sompo`), invoque os scripts via `.\venv\Scripts\python.exe` diretamente ou ajuste a variável `%PROJ%` para `%~dp0`.
