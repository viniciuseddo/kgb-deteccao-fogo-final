## Why

O Vigia precisa permitir que o operador direcione o conjunto câmera/bico por um DualSense USB e solicite ou cancele água sem perder a detecção automática de incêndio. A integração deve ser opcional e verificável sem o conjunto físico, evitando concorrência entre analógico, varredura e bomba.

## What Changes

- Adicionar entrada HID USB para Sony `054C:0CE6`, validando relatório `0x01` de 64 bytes. O diagnóstico real confirmou eixo horizontal no byte 1 e botões no byte 8: Cruz `0x20`, Triângulo `0x80`, Quadrado `0x10` e Círculo `0x40`.
- Mapear Cruz para manual, analógico esquerdo para velocidade PAN, Triângulo para varredura, Quadrado para um disparo manual somente no modo manual e Círculo para cancelar a água em curso sem trocar de modo.
- Separar leitura HID, política de modos e transporte HTTP; limitar envios, descartar comandos ultrapassados e manter a inferência independente.
- Criar variante de firmware derivada do Vigia, preservando o sketch original como referência e rollback. A variante oferecerá movimento não bloqueante, estado explícito, lease manual e watchdog local, além dos comandos legados compatíveis.
- Manter detecção/disparo automáticos em ambos os modos. Durante água, congelar a mira lógica, descartar movimentos e retomar o modo anterior, salvo perda do controle/computador, que determina retorno ao automático após o disparo.
- Aplicar duração máxima e cooldown comuns a disparos manuais e automáticos na variante nova. Segurar botão, retransmitir ou reconectar não poderá repetir nem prolongar água.
- Registrar comandos do operador separadamente das detecções, sem inventar confiança de IA ou exigir migração do banco/painel.
- Tratar pausas/backlog HID e serial sem rejuvenescer dados antigos; distinguir publicação local da hora de captura, não disponível no protocolo preservado. Acrescentar gerações de combate e recuperação de sessão com autoridade restrita de cancelamento.
- Implementar proteção de relé independente de I/O da aplicação, com prazo nominal e orçamento de jitter declarados, não uma promessa física sem tolerância.
- Criar fixtures sintéticas baseadas nas medições, testes isolados, núcleo real com adaptadores adversos e checklist de bancada. Gates físicos de jitter e atraso da câmera permanecem pendentes. Nenhum flash de placa integra esta sessão de planejamento.
- **Mudança de comportamento deliberada, somente na variante opt-in:** `F`/`B` repetidos não rearmam o temporizador e ficam sujeitos ao cooldown. A variante original permanece intacta. O cancelamento por Círculo não será enviado como o `X` legado, que retoma a varredura.

## Capabilities

### New Capabilities

- `dualsense-input`: aquisição USB validada, normalização, zona morta, botões por borda e reconexão sem ações involuntárias.
- `vigia-control-arbitration`: modos manual/automático, prioridade do combate, lease/watchdog, transporte limitado e negociação de capacidades.
- `guarded-pump`: disparo manual condicionado, limite local, cooldown compartilhado, idempotência, cancelamento e rastreabilidade sem falsas detecções.

### Modified Capabilities

Nenhuma especificação preexistente foi encontrada na raiz OpenSpec local. Os contratos do sistema existente serão caracterizados como regressão, não substituídos implicitamente.

## Impact

- Integração opt-in no [script principal](<C:/Users/orugi/Documents/Projetos/KGB-sompo/sistema_vigia.py>); novos módulos de controle, dependência opcional HID e testes.
- Nova variante derivada do [firmware Vigia](<C:/Users/orugi/Documents/Projetos/KGB-sompo/arduino/esp32s3_vigia_bomba/esp32s3_vigia_bomba.ino>), com protocolo HTTP adicional e campos aditivos em `/status`.
- Sem alteração de pesos YOLO, protocolo serial da câmera, pinagem, esquema SQLite ou contrato do painel.
- Fora do escopo: Bluetooth, segundo eixo, firmware do DualSense, melhorias de acurácia, migração dos scripts legados, validação elétrica/mecânica e implantação em campo.
