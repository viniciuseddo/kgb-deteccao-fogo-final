# Linha de base da implementação (tarefas 1.1 e 1.2)

Registrada em 2026-10-22, antes de qualquer alteração de código.

## Workspace e aprovação

- Raiz confirmada: `C:/Users/orugi/Documents/Projetos/KGB-sompo` (`git rev-parse --show-toplevel`), HEAD `6b0abb1`.
- Manifesto R2 (`reviewed-r2.sha256.json`): os 8 documentos substantivos conferem byte a byte (SHA-256 recalculado, 8/8 `OK`). A versão implementada é a aprovada.
- Aprovação técnica (dois revisores) e humana (“Aprovo o plano R2”) constam em `REVIEW.md`. O checkbox 1.1 estava aberto apenas por ser administrativo; foi marcado com referência a este registro.
- `openspec status`: schema `spec-driven`, artefatos completos, 0/48 tarefas no início. Cópia exata do checklist inicial: `tasks_R2_inicial.md` (SHA-256 `E349156F…E0E4BD`, igual ao manifesto).

## Trabalho preexistente do usuário (preservado, não alterado)

`git status` inicial: modificados `.gitignore`, `INICIAR_DASHBOARD.bat`, `INICIAR_VIGIA.bat`, `VER_GRAVACOES.bat`; não versionados `AGENTS.md`, `CONTEXT.md`, `openspec/`. Cópia do diff: `diff_usuario_inicial.patch`. Hashes: `hashes_linha_de_base.txt`. Nenhum reset/clean/stash/commit foi feito.

## Inventário de ferramentas (1.2)

| Ferramenta | Situação | Evidência |
|---|---|---|
| Python do projeto | 3.11.15 em `.\venv` | `.\venv\Scripts\python.exe --version` |
| pytest | ausente no venv | `importlib.util.find_spec('pytest')` → False; testes usam `unittest` da biblioteca padrão, sem instalar nada |
| hidapi (`hid`) | ausente no venv principal | `find_spec('hid')` → False; existe somente no ambiente isolado de diagnóstico `.tmp/dualsense-diagnostico/.venv` (0.15.0) |
| requests / pyserial / cv2 / ultralytics | presentes | `find_spec` → True |
| g++ host | 16.1.0 (MinGW-W64 UCRT posix) | `g++ --version` |
| Arduino CLI / PlatformIO | não estão no PATH | `Get-Command` |
| Arduino15 / core ESP32 / bibliotecas | não encontrados nos locais padrão | `Test-Path` em `%LOCALAPPDATA%\Arduino15`, `~\.platformio`, `~\Documents\Arduino\libraries`, pastas de instalação da IDE: todos False |
| OpenSpec CLI | presente (npm) | `Get-Command openspec` |

Consequência: a compilação real da variante S3 (tarefas 3.1 e 7.6) depende de instalar Arduino CLI + core `esp32` + `ESP32Servo` + `LiquidCrystal I2C`. **Nada foi instalado.** A instalação será pedida ao usuário com versões propostas. Até lá, a variante é verificada com g++ contra cabeçalhos substitutos (stubs), o que não equivale a compilar para o S3.

## Divergências documentais confirmadas nas fontes (para 8.2)

- `AGENTS.md` descreve “Mira Pan-Tilt (Servos)” e “2 servos”. O sketch validado `esp32s3_vigia_bomba.ino` usa um eixo (`USAR_TILT = false`); o usuário confirmou um eixo PAN.
- `AGENTS.md` aponta `arduino/esp32cam_captura_v2/` como firmware da ESP32-CAM. Esse arquivo é um sketch de Arduino Uno com `Servo.h` a 9600 baud, sem câmera. O único sketch do repositório que emite o marcador `AA 55 AA 55` a 460800 baud é `arduino/esp32cam_coleta_universal/`. Qual imagem está gravada na câmera continua não confirmado; a câmera não será regravada.

## Restrições em vigor

Sem upload, sem abrir COM/IP do atuador, sem banco real, sem executar lançadores `.bat`, sem instalar pacotes. A placa ESP32-S3 informada pelo usuário não será tocada até confirmação de modelo/periféricos/alimentação e autorização específica.
