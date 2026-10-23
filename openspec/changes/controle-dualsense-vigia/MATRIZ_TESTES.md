# Matriz de testes (tarefa 8.3)

Comando único: `.\venv\Scripts\python.exe testes\rodar.py` (limite de tempo por módulo). Última execução: 2026-10-22, todos os módulos com código 0.

## Executados e passando

| Módulo | Testes | O que exercita | Lado |
|---|---:|---|---|
| `test_contratos_nucleo` | 40 cenários / 464 passos | Vetores compartilhados contra o **núcleo C++ real** (`nucleo_cli`, relógio 1 ms): sessão idempotente, RECUPERACAO, control_epoch t=4,9→5,1, janelas, dedup/retenção, barreira, perfis, cooldown/inibição, rollover uint32, falha da proteção | C++ |
| `test_nucleo_cpp` (unitários) | 48 verificações | App retida 7 s com corte em 5000 ms, repetição não estende, falha de releitura do pino, passo grande, JSON estrito, seqlock com 2 threads | C++ |
| `test_nucleo_cpp` (adaptadores) | 4 modos | `.ino` real com stubs, proteção em thread própria; loop retido 6 s por HTTP/LCD/Serial → corte em 5000 ms (J_host 0 ms); tarefa não criada → água recusada; nível seguro do relé antes do `pinMode`; Host estranho → 421; POST sem JSON → 415 | C++ (host) |
| `test_entrada_hid` | 24 | Fixtures medidas, ID/comprimento, máscaras, zona morta, sinal PAN, rearme 300 ms, bordas/prioridade, pausa 800 ms com backlog, drenagem limitada, overflow, HID congelado | Python |
| `test_integracao_cliente_nucleo` | 18 | Política+despachante+controlador Python contra o núcleo C++ real: manual >8 s, 20 Hz, Quadrado no AUTO, Quadrado mantido, movimento durante água, Círculo, ACK perdido, reinício durante água, desconexão, IA+Quadrado, inferência antes da barreira, rede fora sem fallback, firmware original | Python+C++ |
| `test_cliente_modulos` | 19 | Câmera (3 JPEGs antigos, 1º JPEG ignorado, backlog), confirmação, adaptador HID sem escrita, despachante saturado, timeout→desconhecido, IP só local, JSONL sem identificador | Python |
| `test_legado_vigia` | 12 | Caracterização do caminho atual: parser serial, rotação, conf/imgsz, debounce 3, cooldown 12 s, `f`, `+/-`, contrato SQLite/painel, falha preexistente com S3 ausente | Python |
| `test_vigia_opt_in` | 7 | Opt-out sem importar HID/controle; sketch original intacto (SHA-256); sem hidapi → instrução; opt-in com threads reais + núcleo real: IA pelo protocolo, `f` no AUTO recusado, câmera perdida com Círculo funcionando, evidência mantida na recusa, liberação de HID/threads | Python+C++ |

A política Python e o núcleo C++ são testados separadamente; o simulador não é uma reimplementação Python do firmware.

## Revisão independente (bugbot + segurança, leitura apenas)

Um revisor separado leu o código e rodou a suíte. Cada achado ganhou um teste escrito antes da correção (vermelho → verde):

| # | Sev. | Achado | Correção | Teste |
|---|---|---|---|---|
| 1 | Alta | Pedido de água da IA ficava retido sem sessão e era enviado minutos depois | Pedido carimbado; descartado sem sessão, se > 1 s ou com publicação > 1 s | `test_r1_*` |
| 2 | Média | Firmware incompatível: fila crescia e a evidência não era registrada | Descarta com `controle_incompativel`; evidência registrada como água não solicitada | `test_r2_*` |
| 3 | Média | Lock da entrada mantido durante HTTP → lacuna HID falsa e YOLO travado | Lock só em torno da política; HTTP fora dele | `test_r3_*` |
| 4 | Média | Círculo descartado sem janela ou com janela expirada, sem aviso | Pede janela e tenta de novo até a validade; aviso “cancelamento nao confirmado” | `test_r4_*` |
| 5 | Baixa | Intenção discreta de epoch HID invalidado podia ser enviada | `input_epoch` verificado em manual/auto/disparar | `test_r5_*` |
| 6 | Baixa | Lease vencido revivido dentro de `handleClient` retido | Expiração aplicada no recebimento | `lease_expira_no_recebimento` |
| 7 | Baixa | Retenção dedup efetiva menor que a publicada | `/status` publica `dedup_capacidade` | vetores de contrato |
| 8 | Baixa | DNS rebinding no protocolo novo | `Host` deve ser o IP do S3; `/api/v1/*` exige `Content-Type: application/json` | adaptadores |
| 9 | Baixa | `--con` deixou de abreviar `--conf` | Alias `--con` | `test_abreviacao_con_continua_valendo` |

Residual não corrigido (preexistente no original): no perfil COMPAT, `/cmd?c=B` via GET pode ser disparado por uma página aberta num navegador da mesma rede; segue limitado pelo guardião. Rede local confiável continua sendo premissa.

## Não executado / pendente

| Item | Situação |
|---|---|
| Compilação Arduino para ESP32-S3 (7.6, 3.1) | **Concluída com sucesso**: Arduino CLI 1.5.1, core esp32 3.3.12, ESP32Servo 3.2.1, LiquidCrystal I2C 1.1.2; variante protegida (995 KB / 31%) e original (960 KB / 30%) compilam com código 0 (detalhes em `evidencias/ferramentas_arduino.md`) |
| `hidapi` no venv (5.1) | **Concluída com sucesso**: `hidapi==0.15.0` instalado no venv `.\venv`; DualSense USB detectado na interface 3 |
| Teste USB real do DualSense com o código novo (7.6) | **Concluída com sucesso**: 9/9 passos aprovados (`teste_usb_20261023_124337.json`), repouso, Cruz, Triângulo, Quadrado, Círculo, analógico esquerda/direita e Quadrado segurado (borda única) validados |
| Jitter J no S3 e ensaios de bancada sem atuadores | **Concluída com sucesso**: Ensaios 1, 2, 4, 5 e 6 na ESP32-S3 real (`192.168.15.43`); $J = 0,005\text{ ms}$ (meta $\le 10\text{ ms}$); transição para perfil `PROTEGIDO`, bloqueio de comandos legados (403) e retorno automático de lease validados |
| Atraso sensor→publicação da câmera, backlog persistente | Não medido; gate antes de atuação automática física |
| Torque, alinhamento câmera/jato, interferência, fluxo de água, latência Wi-Fi | Gate físico |
| Vídeos representativos para regressão visual | Não disponíveis |

## Limitações conhecidas

- `ler()` do relé no firmware devolve o nível comandado (sombra), não realimentação do contato.
- Janelas usam MAC FNV com segredo por boot: protegem contra atraso/replay acidental, **não** contra atacante na rede (HTTP sem autenticação; rede local confiável).
- `J_host` medido no Windows não é J do S3.
