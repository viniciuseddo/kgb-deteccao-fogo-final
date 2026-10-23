# Roteiro de Ensaio na ESP32-S3 e Checklist para Atuadores Físicos

Documento atualizado em 2026-10-23 após conclusão com sucesso dos Ensaios sem Atuadores na placa real ESP32-S3 N16R8 (`192.168.15.43`) e no controle DualSense USB.

---

## 1. Status dos Gates Preliminares

| Gate | Descrição | Status / Evidência |
|---|---|---|
| **Gate 0** | Confirmação de hardware e pinos | **Concluído**: ESP32-S3 N16R8 confirmada; porta COM3 identificada |
| **Gate 1** | Instalação de ferramentas portáteis | **Concluído**: Arduino CLI 1.5.1, core ESP32 3.3.12, ESP32Servo 3.2.1, LiquidCrystal I2C 1.1.2 em `%LOCALAPPDATA%\arduino_portatil` |
| **Gate 2** | Gravação da variante protegida | **Concluído**: Upload na COM3 com Wi-Fi (`New Lifefabi`) via `ferramentas/arduino.py gravar --porta COM3 --wifi`; IP obtido `192.168.15.43` |

---

## 2. Ensaios sem Atuadores Executados na Placa Real

| # | Ensaio | Critério | Resultado Observado | Status |
|---|---|---|---|---|
| **1** | Nível do GPIO 7 no reset | Nível seguro / LOW desde o boot | `rele: false`, nenhum pulso de água | **Aprovado** |
| **2** | `/status` e capacidades | `v=1`, caps, `perfil=COMPAT`, `protecao_ok=true` | `v=1`, `fw: vigia-dualsense-0.1`, caps presentes | **Aprovado** |
| **4** | **Jitter $J$ da proteção sob carga** | $5000\text{ ms} \le \text{duração} \le 5000\text{ ms} + J$, meta $J \le 10\text{ ms}$ sob carga HTTP | **$J = 0,005\text{ ms}$** (5 µs) sob 307 requisições paralelas concorrentes | **Aprovado** |
| **5** | Expiração de Lease | Cessando renovação em `MANUAL`, retorna a `AUTO` em ~1500 ms | Retornou a `AUTO` em 1,8 s | **Aprovado** |
| **6** | Transição de perfil | `/api/v1/session` aceito $\to$ perfil `PROTEGIDO`; letras legadas recebem 403 | Mudou para `PROTEGIDO`; `/cmd?c=L` retornou `HTTP 403` | **Aprovado** |
| **7** | Teste USB Real de entradas | Cruz, Triângulo, Quadrado, Círculo, analógico e anti-autofire do Quadrado | **9/9 passos aprovados** (`teste_usb_20261023_124337.json`) | **Aprovado** |

---

## 3. Checklist para Quando os Componentes Chegarem (Ensaios com Atuadores)

Assim que o relé, a bomba d'água, o servo motor PAN, o display LCD e a fonte externa estiverem disponíveis na bancada, siga rigorosamente esta sequência antes de energizar água:

### Fase A: Servo PAN e Display LCD (Sem Bomba / Sem Água)
1. **Alimentação do Servo:**
   - **NÃO** alimentar o servo motor pelo pino 5V/VBUS do ESP32 ou da USB do PC!
   - Utilizar fonte externa dedicada de 5V (capacidade de pelo menos 2A).
   - Conectar o terminal negativo (GND) da fonte externa ao GND do ESP32-S3 (terra comum obrigatório para o sinal PWM).
2. **Pinos:**
   - Sinal do Servo PAN: **GPIO 4**.
   - I2C do LCD: SDA no **GPIO 8**, SCL no **GPIO 9**.
3. **Validação do Servo:**
   - Iniciar o sistema: o servo deve centralizar em 90° suavemente sem tremer.
   - No modo manual (Cruz no DualSense), mover o analógico: verificar se o sentido mecânico é natural (alavanca à esquerda gira para a esquerda; alavanca à direita gira para a direita). Limites seguros do firmware: 10° a 170°.

### Fase B: Relé com Carga de Teste (Sem Água / Sem Bomba)
1. **Conexão do Módulo Relé:**
   - VCC no 5V, GND no GND, IN no **GPIO 7**.
   - Conectar um multímetro (continuidade) ou LED de teste aos contatos COM (Comum) e NO (Normalmente Aberto).
2. **Disparo de Teste:**
   - Pressionar Cruz ($\times$) para modo manual e depois Quadrado ($\square$): o relé deve atracar por exatamente 5 segundos e desligar com clique audível.
   - Pressionar Círculo ($\bigcirc$) durante o acionamento: o relé deve desatracar imediatamente (cancelamento por barreira).
   - Verificar se o LED de sinalização no **GPIO 6** acompanha o disparo.

### Fase C: Bomba d'Água com Corte Físico e Tubulação
> [!CAUTION]
> A bomba d'água gera ruído indutivo e opera com líquido condutor. Nunca ligue a bomba sem corte elétrico físico de emergência ao alcance imediato da mão do operador.

1. **Circuito da Bomba:**
   - Fonte de alimentação independente para a bomba.
   - Inserir uma chave liga/desliga mecânica em série na linha de alimentação da bomba (corte de emergência físico).
   - Passar um dos pólos da alimentação pelo contato Comum e Normalmente Aberto (NO) do relé mecânico.
2. **Ambiente:**
   - Bico direcionado para recipiente fechado ou bancada molhável com escoamento.
3. **Teste de Ruído e Estabilidade:**
   - Disparar a bomba pelo DualSense ou pelo teclado (`f`).
   - Confirmar que a USB do computador e o Wi-Fi do ESP32-S3 permanecem 100% estáveis durante a partida e parada do motor da bomba (isolamento galvânico garantido pelo Wi-Fi).

### Fase D: ESP32-CAM e Validação Ponta a Ponta
1. **Conectar a ESP32-CAM na USB do PC:**
   - Confirmar a porta serial atribuída no Gerenciador de Dispositivos (ex: `COM4` ou `COM5`).
   - A ESP32-CAM deve estar com o firmware de streaming USB (marcador `0xAA 0x55 0xAA 0x55` a 460800 baud).
2. **Iniciar o Sistema Integrado:**
   ```powershell
   .\venv\Scripts\python.exe sistema_vigia.py --ip 192.168.15.43 --controle-dualsense --salvar
   ```
3. **Medição de Atraso Sensor $\to$ Publicação (Gate 8.5):**
   - Com um cronômetro digital visível no campo de visão da câmera, comparar o tempo exibido na tela do notebook com o tempo do cronômetro real.
   - Meta: atraso total $\le 1000\text{ ms}$ e ausência de backlog persistente antes de aprovar operação autônoma de campo.
