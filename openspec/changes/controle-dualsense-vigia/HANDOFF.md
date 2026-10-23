# Handoff: DualSense no Vigia, sessão 3 (pendências + preparação ponta a ponta)

Workspace: `C:/Users/orugi/Documents/Projetos/KGB-sompo` (fork KGB-sompo). Confirme com `git rev-parse --show-toplevel` antes de operar. Caminhos abaixo são relativos à raiz.

## Objetivo da próxima sessão

Resolver as pendências da mudança OpenSpec `controle-dualsense-vigia` e deixar o ambiente pronto para que, quando relé/bomba/servo chegarem, o pipeline rode de ponta a ponta (ESP32-CAM → notebook/YOLO → DualSense → ESP32-S3 → relé) só conectando os componentes.

## Estado ao fim da sessão 2 (2026-10-22)

- Implementação feita e testada sem hardware: **45/48 tarefas** em `openspec/changes/controle-dualsense-vigia/tasks.md`; `openspec validate controle-dualsense-vigia --strict` passa.
- Suíte completa verde: `.\venv\Scripts\python.exe testes\rodar.py` (limite de tempo por módulo; **use sempre este runner**, rodar `unittest` direto já travou o terminal uma vez).
- Revisão independente bugbot+segurança feita; 9 achados corrigidos test-first. Detalhes em `MATRIZ_TESTES.md`.
- Nada foi instalado, gravado ou commitado. Hardware não foi tocado.

Leia, nesta ordem (não duplicados aqui):
1. `openspec/changes/controle-dualsense-vigia/IMPLEMENTACAO.md`: arquitetura entregue, uso, perfis COMPAT/PROTEGIDO, parâmetros, rollback.
2. `MATRIZ_TESTES.md`: o que foi testado, achados da revisão, pendências.
3. `ROTEIRO_BANCADA.md`: gates e ensaios propostos na placa.
4. `evidencias/linha_de_base.md`: inventário inicial, trabalho preexistente do usuário, divergências documentais.
5. `design.md` e `specs/*/spec.md`: fonte de verdade aprovada (R2). Não redesenhar; divergência substantiva exige reavaliação.

## Autorizações concedidas pelo usuário em 2026-10-23

O usuário autorizou resolver as pendências, incluindo:
- Instalar o necessário para compilar e gravar (Arduino CLI, core ESP32, bibliotecas) e a dependência opcional `hidapi==0.15.0` **no venv do projeto** (nunca global).
- **Apagar e regravar a ESP32-S3**: o programa gravado não pertence ao projeto e pode ser removido. Backup não é exigido.

Continuam valendo: sem commits automáticos, sem reset/clean/stash, não sobrescrever o trabalho preexistente do usuário (`.gitignore`, os três `.bat`, `AGENTS.md`/`CONTEXT.md` não versionados), não usar banco real `dados/deteccoes.db` em testes, não executar os `.bat` (alguns atualizam dependências e iniciam hardware).

## Hardware informado

| Item | Situação |
|---|---|
| ESP32-S3 | **N16R8** (pinos do sketch valem: PAN 4, LED 6, relé 7, SDA 8, SCL 9; não usar 33–37, PSRAM OPI). Disponível. Firmware atual descartável |
| DualSense USB | Disponível (`054C:0CE6`); medido na sessão 1. Reconectável pelo usuário |
| Câmera | ESP32-CAM com sensor **OV2640**; firmware atual a confirmar (ver pergunta aberta) |
| Relé, bomba, servo, LCD, fonte | **Não disponíveis** agora |

Consequência: nesta sessão, ensaios na placa somente **sem atuadores**. O GPIO 7 pode ser observado com LED de teste/multímetro/analisador, nunca com relé ou bomba. Bomba/relé/água ficam para quando houver os componentes e corte elétrico físico (`ROTEIRO_BANCADA.md`).

## Pendências e plano sugerido

1. **Ferramentas (fecha 3.1 parcial, 7.6).** Instalar Arduino CLI de forma portátil em pasta ignorada pelo Git (ex.: `.tmp/arduino/`), com `ARDUINO_DATA_DIR`/`ARDUINO_USER_DIR` também em `.tmp/` e o TEMP do processo apontando para `.tmp/` (o TEMP do usuário é bloqueado pelo sandbox: ver `testes/apoio_cpp.py`). Core `esp32:esp32` 3.x, `ESP32Servo`, `LiquidCrystal I2C` (Frank de Brabander). Registrar as versões em `evidencias/`. Fazer um script de build reproduzível (ex.: `ferramentas/compilar_s3.ps1`) com FQBN para N16R8: `esp32:esp32:esp32s3` com `FlashSize=16M`, `PSRAM=opi`, partição com espaço suficiente. Compilar **também o sketch original** como controle.
   - Riscos prováveis na compilação real: API do `WebServer` (`hostHeader()`, `collectHeaders`, `header`) e `std::atomic` no core 3.x; o `.ino` foi testado só com stubs (`testes/nucleo_cpp/stubs/`). Ajustar o sketch, não os stubs, se divergirem, e manter os stubs fiéis à API real.
2. **hidapi no venv (5.1)** e **teste USB real** de entradas com o código novo (7.6): adaptar um script pequeno que só lê (`controle_dualsense.adaptador_hid` + `entrada`), sem S3, e confirmar Cruz/Triângulo/Quadrado/Círculo/analógico, rearme e reconexão segurando Quadrado. Nada de output/feature reports.
3. **Gravar a variante na S3 isolada (só USB).** Antes: identificar a COM, confirmar efeito de DTR/RTS ao abrir a serial (ver README: `miniterm --rts 0 --dtr 0`). Preencher SSID/senha **fora do controle de versão** (o sketch tem placeholders; não commitar credenciais). Depois os ensaios 1–7 sem atuadores do `ROTEIRO_BANCADA.md`, em especial:
   - nível do GPIO 7 desde o reset;
   - `/status`, perfil, inibição de boot;
   - **jitter J da proteção**: sem osciloscópio/analisador, medir por telemetria interna (instantes na própria tarefa) sob HTTP/Serial adversos, meta J ≤ 10 ms; evidência parcial, gate físico continua aberto;
   - executor dos vetores de contrato contra a placa por HTTP real (hoje roda só contra `nucleo_cli`; criar variante com tempo real).
4. **Ponta a ponta sem atuadores:** ESP32-CAM pela USB + notebook (`sistema_vigia.py --ip <S3> --controle-dualsense`) + DualSense + S3, com o LED/medidor no GPIO 7 no lugar do relé. Verificar confirmação automática, Quadrado/Círculo, lease, registro JSONL e linhas da tabela `deteccoes` em um **banco separado** (não o real). Considerar adicionar `--banco <caminho>` opt-in se necessário (mudança pequena; documentar).
5. **8.5:** firmware da câmera e atraso sensor→publicação. Só existe um sketch com marcador `AA 55 AA 55` a 460800 baud (`arduino/esp32cam_coleta_universal/`); não regravar a câmera sem confirmar com o usuário. Medir o atraso com cronômetro na cena se a câmera estiver montada.
6. **Pronto para os componentes:** checklist curto em `ROTEIRO_BANCADA.md` com a ordem de ligação (servo com fonte própria e GND comum → relé com carga de teste → bomba com corte físico) e os comandos exatos já validados.

Ao terminar, atualizar `tasks.md` só com evidência real e a matriz. Gates físicos (J no S3 com relé, prazo físico, fluxo de água, torque, alinhamento, atraso da câmera) **não** são fechados por compilação ou HTTP aceito.

## Armadilhas já vistas

- Sandbox: escrita no `%TEMP%` do usuário é negada. Use `.tmp/` (ignorado pelo `.gitignore` do usuário).
- Pipes do PowerShell estragam acentos ao mandar código Python por stdin: grave scripts em arquivo UTF-8 (`.tmp/*.py`).
- `sistema_vigia.py` importa `ultralytics` no topo: testes injetam módulo falso (`testes/apoio_vigia.py`). `banco.Banco()` sem caminho cria/abre o banco real.
- A porta COM só aceita um processo; Serial Monitor aberto bloqueia.
- O S3 só fala Wi-Fi 2.4 GHz; o cliente aceita apenas IP literal privado.

## Perguntas respondidas em 2026-10-23

- Câmera: **OV2640** (ESP32-CAM).
- Rede 2.4 GHz do S3: SSID **`New Lifefabi`**. A senha NÃO está registrada; pedir ao usuário na hora e mantê-la fora do repositório (não editar o sketch versionado com a senha; usar cópia em `.tmp/` ou um `segredos.h` ignorado pelo Git).
- **Não há osciloscópio nem analisador lógico.** O jitter J da proteção só pode ser medido de forma parcial: telemetria interna do S3 (instantes de `millis()`/`micros()` na tarefa ao energizar/desligar, sob carga HTTP/Serial adversa) e LED de teste no GPIO 7. Registrar como evidência parcial, sem fechar o gate físico de J nem o tempo real do relé.

## Pergunta ainda aberta

- A ESP32-CAM já está com o firmware de captura USB (marcador `AA 55 AA 55`, 460800 baud)? Se não, confirmar com o usuário antes de gravar `arduino/esp32cam_coleta_universal/` (a autorização dada cobre a ESP32-S3, não a câmera). Verificar primeiro só lendo a serial com `--rts 0 --dtr 0`.

## Skills sugeridas

- `openspec-apply-change`: continuar a mudança `controle-dualsense-vigia`.
- `managing-python-dependencies`: antes de instalar `hidapi` no venv.
- `tdd`: qualquer ajuste de código (teste falho primeiro).
- `diagnose`: falhas de compilação/gravação ou comportamento na placa.
- `review-bugbot` / `review-security` (ou um subagente revisor somente leitura) antes da entrega.
