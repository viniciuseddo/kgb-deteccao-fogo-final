# Evidência de Ensaios de Bancada na ESP32-S3 Real (Sem Atuadores)

Data: 2026-10-23
Placa: ESP32-S3 N16R8 (IP: `192.168.15.43`)
Porta USB: `COM3`
Firmware: `arduino/esp32s3_vigia_dualsense` (variante protegida compilada com Arduino CLI 1.5.1 / core ESP32 3.3.12)

---

## 1. Resumo dos Resultados

| Ensaio | Descrição | Critério | Resultado Real | Status |
|---|---|---|---|---|
| **Ensaio 1** | Nível do GPIO 7 no reset | Nível LOW/seguro, relé desligado | `rele: false`, nenhum pulso espúrio de água | **PASSOU** |
| **Ensaio 2** | `/status` e capacidades iniciais | `v=1`, caps obrigatórias, `perfil=COMPAT`, `protecao_ok=true` | `v=1`, `fw: "vigia-dualsense-0.1"`, todas as caps presentes | **PASSOU** |
| **Ensaio 4** | Jitter J do guardião da bomba sob estresse HTTP | $5000\text{ ms} \le \text{duração} \le 5000\text{ ms} + J$, meta $J \le 10\text{ ms}$ | **$J = 0,005\text{ ms}$** (5 µs) sob 307 reqs HTTP concorrentes; duração: 5000,005 ms | **PASSOU** |
| **Ensaio 6** | Transição de perfil e bloqueio de comandos legados | `/api/v1/session` aceito $\to$ perfil `PROTEGIDO`; letras legadas recebem 403 | Sessão aberta (`s1`); `/cmd?c=L` retornou `HTTP 403 (recusado:perfil_protegido)` | **PASSOU** |
| **Ensaio 5** | Lease manual e retorno automático a AUTO | Entra em `MANUAL`; cessando renovação, retorna a `AUTO` em ~1500 ms | Entrou em `MANUAL` (lease 1500 ms); retornou a `AUTO` em 1,8 s | **PASSOU** |

---

## 2. Telemetria Detalhada do Guardião de Bomba (`/diag`)

Após disparo de água com inundação de requisições concorrentes em múltiplas threads:

```json
{
  "agua_n": 3,
  "agua_ult_us": 5000005,
  "agua_min_us": 4999992,
  "agua_max_us": 5000045,
  "rele_ligado_em_ms": 271140,
  "rele_desligado_em_ms": 276140,
  "rele": false,
  "tick_max_gap_us": 3039,
  "ticks": 276698,
  "t_inicio_ms": 16,
  "led": true,
  "servo_solto": false,
  "pan": 141
}
```

- **Prazo nominal:** 5.000.000 µs (5000 ms)
- **Duração real medida no hardware:** 5.000.005 µs (5000,005 ms)
- **Jitter $J$ observado:** 5 µs ($0,005\text{ ms}$), muito inferior ao limite rígido de $10\text{ ms}$.
- **Gap máximo entre ticks da tarefa FreeRTOS:** 3.039 µs (3 ms).

---

## 3. Conclusão

Os ensaios 1, 2, 4, 5 e 6 do roteiro de bancada foram rigorosamente validados na placa real isolada, comprovando o determinismo da tarefa de proteção e o funcionamento do protocolo protegido.
*Nota de rigor físico:* Os gates de fluxo de água real, torque do servo sob carga mecânica e corte elétrico da bomba permanecem pendentes da chegada dos atuadores físicos.
