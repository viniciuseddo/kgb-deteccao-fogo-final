# Plano: DualSense USB no Vigia

**Versão documental: R2.** O plano foi revisto após reprovação adversarial da R1; os pareceres e o estado da aprovação técnica/humana estão no [registro da revisão](<C:/Users/orugi/Documents/Projetos/KGB-sompo/openspec/changes/controle-dualsense-vigia/REVIEW.md>). Validação estrutural OpenSpec não é aprovação técnica. Implementação, testes automatizados do recurso e compilação do novo firmware ainda NÃO foram executados. Não houve upload para placas ou acionamento de bomba.

## Mapeamento confirmado no controle real

| Entrada | Função planejada |
|---|---|
| Cruz/X | Entrar no modo manual |
| Analógico esquerdo, horizontal | Movimentar PAN; soltar mantém posição no manual |
| Triângulo | Retomar varredura automática |
| Quadrado | Um disparo manual por pressionamento, somente no manual |
| Círculo | Cancelar água em curso sem trocar o modo |

A detecção automática permanece ativa nos dois modos. Durante água, movimento é suspenso e comandos antigos não são acumulados. Desconexão determina retorno AUTO; se houver disparo em curso, o retorno aguarda término local ou cancelamento.

## Sequência de implementação

1. Caracterizar o comportamento existente e criar fixtures/testes isolados com os bytes medidos.
2. Implementar parser HID, bordas/rearme e políticas de modos sem abrir hardware nos testes.
3. Criar uma variante de firmware com movimento não bloqueante, watchdog e guardião único da bomba; manter o original intacto.
4. Integrar protocolo protegido e controle opcional ao Python, com transporte limitado e registro honesto dos resultados.
5. Executar testes de falhas/regressão, testes do núcleo C++ e compilação sem upload; repetir entradas USB reais quando necessário.
6. Entregar guia de instalação/rollback e checklist de bancada para a equipe com equipamento.

O [checklist detalhado](<C:/Users/orugi/Documents/Projetos/KGB-sompo/openspec/changes/controle-dualsense-vigia/tasks.md>) contém as tarefas na ordem de dependência; nenhuma foi marcada como implementada.

## Proteções e parâmetros propostos

- Prazo nominal de água de 5 s, com proteção dedicada independente de HTTP/LCD; objetivo de jitter de software até 10 ms, a medir no S3 antes de energizar a bomba. Não é promessa de máximo físico absoluto sem tolerância; repetição não estende o prazo.
- Cooldown comum de 12 s entre inícios aceitos; após cancelar ou reiniciar a variante nova, inibição completa de 12 s.
- Entrada neutra para rearmar; botão segurado ao conectar não dispara. Pausa de aquisição invalida/drena backlog HID antes de permitir novas ações.
- Término/cancelamento da água cria nova geração de controle: pacotes antigos que chegarem depois são rejeitados. No manual, retomar exige novo fluxo neutro, não apenas manter o analógico deslocado.
- Reiniciar o cliente durante água entra em recuperação: pode cancelar somente a ação anterior, sem repetir disparo ou restaurar manual.
- Watchdog manual local inicialmente em 1,5 s; atualização não depende do YOLO.
- Zona morta inicial de 10%, velocidade PAN até 30 graus/s e movimento HTTP até 20 Hz, todos sujeitos à aprovação e calibração.
- Círculo não será enviado como o `X` legado, que também retoma a varredura.
- Na sessão protegida, letras legadas atuantes são bloqueadas; a IA também usa o protocolo novo. Isso evita que uma rota antiga contorne as proteções.

**Círculo é cancelamento temporário, não parada de emergência física nem trava permanente.** Depois do cooldown, a IA poderá solicitar nova água com nova confirmação em publicações locais válidas. O protocolo atual não comprova a idade real de captura: atraso da câmera e ausência de backlog persistente são gates de bancada, não testes já passados. O prazo de cancelamento via Wi-Fi não é garantido fisicamente.

## Documentos para a próxima sessão

- [Proposta e escopo](<C:/Users/orugi/Documents/Projetos/KGB-sompo/openspec/changes/controle-dualsense-vigia/proposal.md>).
- [Arquitetura, parâmetros, protocolo e rollback](<C:/Users/orugi/Documents/Projetos/KGB-sompo/openspec/changes/controle-dualsense-vigia/design.md>).
- [Entrada DualSense](<C:/Users/orugi/Documents/Projetos/KGB-sompo/openspec/changes/controle-dualsense-vigia/specs/dualsense-input/spec.md>).
- [Arbitragem e watchdog](<C:/Users/orugi/Documents/Projetos/KGB-sompo/openspec/changes/controle-dualsense-vigia/specs/vigia-control-arbitration/spec.md>).
- [Bomba protegida e cancelamento](<C:/Users/orugi/Documents/Projetos/KGB-sompo/openspec/changes/controle-dualsense-vigia/specs/guarded-pump/spec.md>).
- [Tarefas verificáveis](<C:/Users/orugi/Documents/Projetos/KGB-sompo/openspec/changes/controle-dualsense-vigia/tasks.md>).

## Limites do aceite

O DualSense USB foi medido; ESP32, servo, bomba e Wi-Fi do atuador não foram testados. Sem o equipamento, é possível validar software e compilar firmware, mas não torque, limites mecânicos reais, alinhamento, interferência elétrica ou fluxo de água. Faltam também gravações representativas para regressão visual.

As fontes operacionais e o ambiente Python principal continuam intactos. As diferenças de segurança se aplicam à variante nova opt-in; o sketch validado permanece como referência e rollback.

## Retomar

Após revisar/aprovar os parâmetros e o escopo, solicitar: `Implemente a mudança controle-dualsense-vigia seguindo as tarefas, começando pelos testes, sem upload para placas.`
