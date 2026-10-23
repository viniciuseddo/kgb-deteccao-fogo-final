# Evidência de Teste USB Real de Entradas do DualSense (Tarefa 7.6)

Data: 2026-10-23 12:43:37
Ambiente: Windows Sandbox / PowerShell
Dispositivo: DualSense Wireless Controller (`VID: 0x054C`, `PID: 0x0CE6`, Interface 3 USB Gamepad)
Script: `ferramentas/teste_dualsense_usb.py`
Log bruto gerado: `.tmp/evidencias_usb/teste_usb_20261023_124337.json`

---

## 1. Resumo da Execução Interativa com Operador

| Passo | Descrição / Critério | Ação Real Executada | Resultado |
|---|---|---|---|
| **1** | Repouso inicial até armar | Controle solto, neutro estável por 300 ms | **OK** (`estado=ARMADA`, `pan_vel=0.0`) |
| **2** | Pressione e solte CRUZ | Borda de subida detectada na máscara `0x20` | **OK** (evento `cruz` registrado) |
| **3** | Pressione e solte TRIÂNGULO | Borda de subida detectada na máscara `0x80` | **OK** (evento `triangulo` registrado) |
| **4** | Pressione e solte QUADRADO | Borda de subida detectada na máscara `0x10` | **OK** (evento `quadrado` registrado) |
| **5** | Pressione e solte CÍRCULO | Borda de subida detectada na máscara `0x40` | **OK** (evento `circulo` registrado) |
| **6** | Analógico esquerdo para ESQUERDA | Eixo $X \le 20 \implies \text{pan\_vel} \ge +0.9$ | **OK** (`pan_vel=+1.00`) |
| **7** | Analógico esquerdo para DIREITA | Eixo $X \ge 235 \implies \text{pan\_vel} \le -0.9$ | **OK** (`pan_vel=-1.00`) |
| **8** | Retorno ao centro / repouso | Zona morta de 10% aplicada $\implies \text{pan\_vel}=0.0$ | **OK** (`pan_vel=0.00`) |
| **9** | Quadrado mantido por ~3 s | Disparo manual por borda única: exatamente 1 evento em 8s | **OK** (1 evento, sem repetição/autofire) |

**Total de passos aprovados:** 9/9 (**100% de sucesso**, Código 0).

---

## 2. Conclusão da Tarefa 7.6

1. O adaptador `hidapi` USB somente de leitura lê os relatórios de 64 bytes (`ID 0x01`) a 250 Hz sem envio de pacotes de escrita ou interferência nos atuadores.
2. A política de normalização assimétrica, zona morta e prioridade de bordas (`Círculo > Triângulo > Cruz > Quadrado`) foi validada ponta a ponta com o hardware real.
3. O comportamento anti-autofire do botão Quadrado foi comprovado experimentalmente.
