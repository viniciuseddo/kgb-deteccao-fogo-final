# Revisão adversarial contextualizada — controle DualSense / Vigia

## Estado

**Rodada R1: REPROVADA PARA IMPLEMENTAÇÃO por ambos os revisores. Rodada R2: APROVADA PARA IMPLEMENTAÇÃO por ambos, sem bloqueadores de projeto pendentes.** Todos os cinco grupos de achados foram fechados na reavaliação documental. **Aprovação humana: APROVADA.** O usuário selecionou “Aprovo o plano R2” após receber os dois pareceres e o resumo das políticas. Nenhuma aprovação estrutural do OpenSpec substitui parecer técnico, execução dos testes ou aceite físico.

## Mandato e independência

O usuário solicitou revisão adversarial antes de receber o plano para sua aprovação. Foram consultados dois revisores independentes, sem participação na autoria inicial desta rodada:

- Segurança lógica/integração: agente `e167ab6c-9daf-447a-b068-df89168815d7`.
- Viabilidade/regressões/simplicidade: agente `52146207-70f4-4b1d-b328-33a2e22bcb0b`.

Ambos leram o plano e confrontaram fontes reais do Vigia. Não executaram hardware, scripts operacionais, rede do atuador, COM ou banco; não alteraram arquivos nem instalaram dependências. As contraprovas são análises de projeto, não resultados empíricos da implementação ainda inexistente.

## Achados R1 e tratamento aprovado em R2

| Achados originais | Severidade original | Contraprova | Tratamento documental R2 |
|---|---|---|---|
| SA-01 / VA-02 | Alta / média | S1 dispara, ACK se perde, S2 substitui S1 e não pode cancelar a ação anterior | Abertura idempotente; RECUPERACAO com autoridade de cancelar apenas o action_id ativo, sem repetir água/restaurar manual; testes de handshake perdido e capacidade obsoleta |
| SA-02 | Alta | Pausa de 800 ms; Quadrado antigo é lido com timestamp novo antes de vencer lease | input_epoch invalidado por lacuna; drenagem limitada até vazio; novo fluxo neutro e seleção manual; eventos antigos não rearmam |
| SA-03 | Alta | Movimento gerado em t=4,9 durante água chega em t=5,1 após término | control_epoch no início/fim natural/cancelado; tokens vinculados ao epoch; fronteira confirmada + drenagem/neutro; geração causal local invalida inferência anterior |
| SA-04 / VA-01 | Alta / alta | HTTP/LCD retêm loop e a bomba não recebe tick no prazo | Tarefa dedicada como única dona do relé, sem I/O/mutex bloqueável; prazo nominal 5000 ms + J, meta J <= 10 ms; testes de adaptadores retidos e medição física gateada |
| SA-05 / VA-03 | Alta / média | JPEGs antigos na COM ganham timestamps de captura aparentemente novos | IDs/idade de publicação LOCAL, sem afirmar hora do sensor; descarte/resincronização de backlog local; premissa sensor→publicação explicitamente não medida e gateada |

Os tratamentos estão no [design](<C:/Users/orugi/Documents/Projetos/KGB-sompo/openspec/changes/controle-dualsense-vigia/design.md>), nas especificações de [entrada](<C:/Users/orugi/Documents/Projetos/KGB-sompo/openspec/changes/controle-dualsense-vigia/specs/dualsense-input/spec.md>), [arbitragem](<C:/Users/orugi/Documents/Projetos/KGB-sompo/openspec/changes/controle-dualsense-vigia/specs/vigia-control-arbitration/spec.md>) e [bomba](<C:/Users/orugi/Documents/Projetos/KGB-sompo/openspec/changes/controle-dualsense-vigia/specs/guarded-pump/spec.md>), com [tarefas verificáveis](<C:/Users/orugi/Documents/Projetos/KGB-sompo/openspec/changes/controle-dualsense-vigia/tasks.md>).

## Pareceres finais R2

### Segurança lógica e integração

Agente `e167ab6c-9daf-447a-b068-df89168815d7`: **“APROVADO PARA IMPLEMENTAÇÃO (aprovação técnica do plano, sem bloqueadores de projeto pendentes).”**

Confirmou fechamento de SA-01 a SA-05. Não identificou novas contradições reais bloqueadoras e declarou não exigir correção documental adicional para aprovar o projeto. Limites físicos, testes e compilação permanecem gates da entrega futura, não ressalvas de projeto indefinidas.

### Viabilidade, regressões e simplicidade

Agente `52146207-70f4-4b1d-b328-33a2e22bcb0b`: **“APROVADO PARA IMPLEMENTAÇÃO.”**

Confirmou fechamento de VA-01 a VA-03 e coerência dos tratamentos adicionais de backlog HID, fronteira de combate e geração causal. Não encontrou novo bloqueio técnico concreto. Recomendou apenas, de forma opcional, manter módulos/runners pequenos e detalhar cadência de evidências/limites do JSONL ao materializar o contrato.

### Versão efetivamente aprovada

Ambos releram os sete artefatos substantivos da mudança e o glossário, sem usar este relatório como prova de aprovação. Ambos informaram os mesmos SHA-256:

- Design: `178145E1CE7B2AE7AD5AF511ACAC099702FB5BBAA12D58A2C79FDAF8D1B58BC5`.
- Tarefas: `E349156FC1A4907E31399C874149572066382784AFF7CAD5AC640A77E3E0E4BD`.

O [manifesto R2](<C:/Users/orugi/Documents/Projetos/KGB-sompo/openspec/changes/controle-dualsense-vigia/reviewed-r2.sha256.json>) identifica os oito documentos substantivos. Este relatório administrativo de pareceres/aprovação humana é excluído do manifesto; seu preenchimento não modifica o desenho aprovado. Mudanças substantivas posteriores exigem reavaliação dos pontos afetados.

O critério de revisão foi aprovação explícita, não condicionada a decisões de projeto ainda abertas. Foi satisfeito por ambos. **O escopo aprovado é iniciar desenvolvimento/testes segundo o plano, não energizar equipamentos, regravar placas ou certificar segurança. A autorização humana para a próxima etapa de desenvolvimento/testes foi concedida; a implementação não foi iniciada nesta rodada de revisão.**

## Verificações locais desta rodada

- Compilador host presente e executável: g++ 16.1.0, MinGW-W64. Nenhuma compilação do recurso foi executada.
- Arduino CLI/PlatformIO não apareceram no inventário de PATH; isso não prova ausência em disco. Instalação/inventário continuam gateados antes de implementar.
- Código operacional e firmware original não foram editados. Foram tratados somente documentos de planejamento/glossário.
- R2 passou na validação estrutural estrita do OpenSpec com zero issues. Isso foi registrado separadamente dos dois pareceres técnicos; não foi usado como prova de segurança.

## Aprovação humana e limites de execução

Na pergunta `aprovacao_humana_plano_r2`, o usuário selecionou “Aprovo o plano R2”. O escopo apresentado foi avançar ao desenvolvimento/testes, começando pelos testes e preservando o sistema atual, sem upload para placas nem acionamento físico. Instalações necessárias continuam sujeitas a suas autorizações próprias.

Parâmetros iniciais, inibição após boot/cancelamento, restrição do teclado manual e rearme em neutro foram aceitos como base do plano para desenvolvimento; não representam calibração física comprovada. Medição do jitter do corte, atraso sensor→publicação, torque/alinhamento/ruído, fluxo de água e latência Wi-Fi permanecem pendentes. Círculo é cancelamento temporário, não emergência elétrica nem trava permanente da IA.
