# Evidência de Ferramentas e Compilação dos Sketches (ESP32-S3 N16R8)

Data: 2026-10-23
Ambiente: Windows Sandbox / PowerShell
Diretório Portátil: `%LOCALAPPDATA%\arduino_portatil`

---

## 1. Versões Fixadas das Ferramentas

| Componente | Versão | Origem / Identificador |
|---|---|---|
| **Arduino CLI** | `1.5.1` | Commit `01f3d4f2b` (Date: 2026-06-05T10:22:12Z) |
| **ESP32 Core** | `3.3.12` | `esp32:esp32@3.3.12` via Espressif package index |
| **ESP32Servo** | `3.2.1` | `ESP32Servo@3.2.1` |
| **LiquidCrystal I2C** | `1.1.2` | `LiquidCrystal I2C@1.1.2` (Frank de Brabander) |
| **hidapi** | `0.15.0` | `hidapi==0.15.0` (instalado no virtualenv `.\venv`) |

---

## 2. Configuração do Alvo (FQBN)

Configuração específica para a placa **ESP32-S3 N16R8** (16 MB Flash Quad, 8 MB PSRAM Octal, partição 3MB App sem OTA):

```text
esp32:esp32:esp32s3:FlashSize=16M,PSRAM=opi,PartitionScheme=app3M_fat9M_16MB,FlashMode=qio,CDCOnBoot=default,USBMode=hwcdc,UploadSpeed=921600
```

---

## 3. Resultados da Compilação Real

### 3.1. Variante Protegida: `arduino/esp32s3_vigia_dualsense`
- **Status:** Sucesso (Código 0)
- **Tamanho do Sketch (Flash):** 995.042 bytes (31% do máximo de 3.145.728 bytes)
- **Memória Dinâmica (RAM):** 52.660 bytes (16% do máximo de 327.680 bytes)
- **Recursos Adicionais:**
  - Tarefa dedicada FreeRTOS de proteção do relé (guardião estrito de bomba d'água com orçamento 5000 ms + J ≤ 10 ms)
  - Endpoints HTTP REST protegidos com validação de cabeçalho Host anti-DNS rebinding (`/cmd`, `/lease`, `/status`, `/diag`)
  - Suporte opcional a injeção limpa de credenciais Wi-Fi via `segredos_wifi.h` fora do controle de versão

### 3.2. Sketch Original (Controle de Integridade): `arduino/esp32s3_vigia_bomba`
- **Status:** Sucesso (Código 0)
- **Tamanho do Sketch (Flash):** 960.558 bytes (30% do máximo de 3.145.728 bytes)
- **Memória Dinâmica (RAM):** 48.908 bytes (14% do máximo de 327.680 bytes)

### 3.3. Comparativo de Consumo
- **Flash adicional:** +34.484 bytes (+1,10% da partição de 3 MB)
- **RAM estática adicional:** +3.752 bytes (+1,14% dos 320 KB de SRAM)

---

## 4. Reprodutibilidade

O processo de compilação é 100% automatizado e reproduzível pelo utilitário `ferramentas/arduino.py`:

```powershell
# Verificar versões instaladas:
python ferramentas/arduino.py versoes

# Compilar variante DualSense:
python ferramentas/arduino.py compilar

# Compilar variante original (controle):
python ferramentas/arduino.py compilar --original
```
