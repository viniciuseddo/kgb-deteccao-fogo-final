# Controle DualSense no Vigia: instalação, operação e rollback

Recurso **opcional**. Sem `--controle-dualsense`, o Vigia roda o caminho original sem importar HID (teste `test_sem_opcao_nao_importa_controle_nem_hid`).

## O que foi criado

| Caminho | Papel |
|---|---|
| `arduino/esp32s3_vigia_dualsense/` | Variante nova do firmware S3. Núcleo C++ (`vigia_protecao`, `vigia_arbitro`, `vigia_json`) + adaptadores no `.ino`. |
| `arduino/esp32s3_vigia_bomba/` | Sketch original **inalterado** (SHA-256 `F962CC2C…C173`, conferido por teste). Referência e rollback. |
| `controle_dualsense/` | Cliente Python: parser/política HID, adaptador HID somente de entrada, protocolo, transporte, despachante, controlador, câmera com fronteiras, confirmação, registro JSONL. |
| `requirements-dualsense.txt` | Dependência opcional `hidapi==0.15.0`. |
| `sistema_vigia.py` | Duas opções novas (`--controle-dualsense`, `--log-controle`) e um desvio para o caminho novo. O laço original não foi alterado. |
| `testes/` | Suíte sem hardware. Rodar: `.\venv\Scripts\python.exe testes\rodar.py`. |

## Instalação (somente quando for usar)

1. Dependência no venv do projeto (nunca global):
   `.\venv\Scripts\python.exe -m pip install -r requirements-dualsense.txt`
2. Gravar a variante `esp32s3_vigia_dualsense` no S3 **só após** o roteiro de bancada e autorização (ver `ROTEIRO_BANCADA.md`). Preencher SSID/senha antes, como no original.
3. Rodar: `.\venv\Scripts\python.exe sistema_vigia.py --ip <IP do S3> --controle-dualsense`

Sem `hidapi`, a opção encerra com código 2 e a instrução acima. O caminho original continua disponível.

## Mapeamento

| Entrada | Efeito |
|---|---|
| Cruz | MANUAL na posição atual (exige entrada armada) |
| Analógico esquerdo, horizontal | Velocidade PAN no MANUAL (zona morta 10%, até 30 °/s); soltar mantém posição |
| Triângulo | AUTO (fora do combate) |
| Quadrado | Uma água por pressionamento, somente no MANUAL |
| Círculo | Cancela a ação de água sem trocar o modo; aplica 12 s de inibição |
| Tecla `f` (caminho novo) | Igual a Quadrado: exige MANUAL e passa pelo guardião |

Detecção automática fica ativa nos dois modos e pede água pelo mesmo protocolo protegido.

## Parâmetros (iniciais, não calibrados fisicamente)

Firmware (`vigia_config.h`): água 5000 ms desde o GPIO; cooldown 12000 ms entre inícios; inibição 12000 ms após cancelamento e após boot; lease manual 1500 ms; janela de frescor 500 ms; validade de velocidade 500 ms; PAN 10–170°, varredura 30–150°. Cliente: zona morta 10%, neutro para armar 300 ms, lacuna HID 100 ms, HID fresco 500 ms, movimento ≤ 20 Hz, renovação 250 ms, timeout HTTP 200 ms, pausa serial 500 ms, idade local da publicação 1000 ms, 3 publicações distintas para confirmar. `--cooldown` e `--tempo-bomba` **não** alteram o firmware.

## Perfis do firmware novo

- **COMPAT** (do boot até a primeira sessão protegida): letras `V L C R 4 6 F X B H` com a semântica do original, porém todas as águas passam pelo guardião. `F`/`B` repetidos não reiniciam o temporizador e respeitam cooldown/inibição; mover durante a água é recusado sem alterar o alvo; não há deduplicação para letras.
- **PROTEGIDO** (após a primeira sessão, até reboot): letras que movem, ligam/cortam água ou trocam modo retornam 403 (`/cmd`) ou `recusado:perfil_protegido` (serial), inclusive depois de o lease expirar. `H` e `/status` continuam. Voltar a COMPAT exige reboot.

Diferenças em relação ao original, todas deliberadas: guardião único, inibição de 12 s após boot e após `X`/Círculo, recusa de movimento durante a água, `X` cortando pela tarefa de proteção, regra de 8 s de silêncio somente no COMPAT.

## Rede

Somente IP literal privado/loopback/link-local no cliente. No S3, toda rota exige `Host` igual ao IP do S3 (421 caso contrário) e `/api/v1/*` exige `Content-Type: application/json` (415). Não há autenticação: use rede local confiável. No perfil COMPAT, `/cmd` por GET continua como no original.

## Mensagens de incompatibilidade

Na barra de estado do vídeo: `controle desabilitado: versao_incompativel` (firmware original ou sem `v`), `capacidades_ausentes`, `limite_ausente:<campo>`, `limites_menos_restritivos`. Nesses casos nenhum comando novo é improvisado e nenhuma letra legada é enviada. `sem sessao protegida (<motivo>)` aparece enquanto a sessão não abre (ex.: `agua_legada_ativa`).

## Limites do cancelamento

Círculo é cancelamento **temporário pela rede**, não parada de emergência. Não há prazo físico garantido via Wi-Fi; o timeout HTTP só limita a espera no cliente. Depois do cooldown, a IA pode pedir água de novo com nova confirmação. O fallback seguro é local: lease de 1500 ms e prazo de 5000 ms na tarefa de proteção do S3. Corte elétrico físico continua obrigatório na bancada.

## Registros

- `dados/comandos_controle.jsonl` (ou `--log-controle`): comandos e decisões, com estados solicitado/aceito/recusado/desconhecido/descartado/reconciliado. Sem número de série do controle.
- Tabela `deteccoes` (esquema inalterado): só detecções reais. `acao` mostra a decisão real (`agua aceita pelo firmware (logico)`, `agua recusada: <motivo>`, `agua nao solicitada: <motivo>`, `agua com resultado desconhecido`); `duracao_bomba` fica nula. Água manual não entra na tabela.

## Rollback

1. Software: não usar `--controle-dualsense` (opcional: `pip uninstall hidapi` no venv).
2. Placa: regravar `arduino/esp32s3_vigia_bomba/esp32s3_vigia_bomba.ino` com a configuração (SSID/senha) que a equipe já usa.
3. Não há migração de banco a desfazer. Nada exige `git reset`.
