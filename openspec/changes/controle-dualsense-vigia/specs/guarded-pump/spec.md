## ADDED Requirements

### Requirement: Disparo manual condicionado ao modo

Quadrado SHALL solicitar água somente por nova borda, com entrada armada, MANUAL ativo, sessão/lease válidos e nenhuma ação incerta pendente de reconciliação. A detecção automática SHALL continuar habilitada em AUTO e MANUAL, sujeita ao mesmo guardião.

#### Scenario: Quadrado no automático
- **WHEN** Quadrado apresenta borda em AUTO
- **THEN** a solicitação é recusada sem ligar água, mudar modo ou enfileirar disparo

#### Scenario: Disparo deliberado no manual
- **WHEN** Quadrado apresenta nova borda em MANUAL saudável e o guardião está disponível
- **THEN** exatamente uma solicitação limitada é aceita e a mira é congelada

### Requirement: Limite máximo autoritativo local

O firmware novo SHALL definir prazo nominal de 5000 ms desde o comando de energização GPIO, com desligamento lógico até prazo + J no domínio em que MCU/escalonador cumprem o orçamento admitido; o objetivo inicial SHALL ser J <= 10 ms. Uma tarefa FreeRTOS dedicada de proteção, acima da prioridade dos adaptadores HTTP/LCD/logging, SHALL ser a única proprietária do relé após a inicialização segura e SHALL NOT executar ou aguardar I/O, logging, alocação ou mutex bloqueável por adaptadores. Python, USB ou Wi-Fi SHALL NOT ser necessários para expirar o prazo. Novos pedidos, heartbeat, status, mudança de origem e duplicatas SHALL NOT reiniciar ou prolongar o timer. O relé SHALL iniciar desligado; falha em iniciar a proteção SHALL recusar toda água.

#### Scenario: HTTP e I2C retêm a aplicação
- **WHEN** adaptadores HTTP parcial/lento, LCD/I2C ou logging são retidos por mais de 5 s enquanto a tarefa de proteção continua escalonada dentro do orçamento
- **THEN** o adaptador de saída ordena desligamento dentro de 5000 ms + J desde energizar, sem depender de ticks do loop HTTP

#### Scenario: Falha ao criar a tarefa de proteção
- **WHEN** a proteção não pode ser inicializada
- **THEN** o relé permanece desligado e todos os pedidos de água são recusados sem fallback legado

#### Scenario: Sem medição do jitter físico
- **WHEN** testes simulados passam mas J e o tempo real do relé ainda não foram medidos no S3
- **THEN** o aceite físico continua bloqueado; o relatório não promete máximo físico absoluto de 5000 ms nem cobre travamento total do MCU

#### Scenario: Cliente desaparece após disparar
- **WHEN** o computador para logo depois de um início aceito
- **THEN** o firmware desliga pelo limite local e retorna ao modo seguro determinado pela saúde

#### Scenario: Repetir comando durante água
- **WHEN** chegam pedidos com mesmo ID ou IDs diferentes antes do prazo
- **THEN** existe apenas uma ação física comandada, com o prazo original preservado

### Requirement: Cooldown comum e explícito

Todos os caminhos da variante nova SHALL compartilhar cooldown de 12000 ms configuráveis entre inícios aceitos. Cancelamento SHALL postergar a próxima aceitação para pelo menos 12000 ms após cancelar; boot SHALL impor 12000 ms de inibição inicial. O cliente SHALL respeitar os limites publicados pelo firmware, sem presumir alteração por argumento de metadados.

#### Scenario: Alternar origens para tentar rearmar
- **WHEN** um disparo automático é seguido de Quadrado, teclado `f` ou `B` legado antes do limite
- **THEN** todas as origens são recusadas e nenhuma altera a próxima aceitação

#### Scenario: Intervalo normal
- **WHEN** um disparo começa em t=0 e termina em t=5 s sem cancelamento
- **THEN** nenhum novo início é aceito antes de t=12 s

#### Scenario: Cancelamento postergando intervalo
- **WHEN** um disparo começa em t=0 e Círculo cancela em t=2 s
- **THEN** nenhum novo início é aceito antes de t=14 s, inclusive automático

#### Scenario: Reiniciar durante cooldown
- **WHEN** a variante reinicia antes de terminar um intervalo
- **THEN** o relé permanece desligado e novos disparos são inibidos por 12 s contados do novo boot, sem prometer exactly-once durável

### Requirement: Cancelamento sem troca de modo

Círculo SHALL solicitar desligamento da água corrente sem iniciar varredura nem modificar o modo-base por si só. O cancelamento SHALL ser uma operação própria, válida nos dois modos, com execução local pela proteção do relé após aceitação. A identidade de ação SHALL derivar do `command_id` conhecido antes do ACK. No fluxo normal, o cancelamento SHALL incluir barreira `cancel_through_sequence` da sessão, abrangendo intenções anteriores inclusive com ACK perdido. Em RECUPERACAO, a nova sessão SHALL usar capacidade de cancelamento restrita ao action_id anterior fornecida pelo S3, sem autorização de disparo/movimento. Uma ação posterior à barreira ou diferente do alvo de recuperação SHALL NOT ser cortada por cancelamento atrasado.

#### Scenario: Círculo depois de reiniciar o cliente
- **WHEN** S2 substitui S1 enquanto A protegida continua ativa e recebe capacidade de recuperação para A
- **THEN** Círculo de S2 pode cancelar somente A, sem restaurar manual, repetir água ou afetar ação posterior

#### Scenario: Cancelar disparo cujo ACK se perdeu
- **WHEN** o último status era idle, mas um disparo conhecido pelo cliente pode ter sido aceito sem resposta e o operador pressiona Círculo
- **THEN** o cliente envia a barreira conhecida sem esperar descobrir um novo ID; o firmware cancela ação abrangida ou invalida intenção anterior ainda não recebida

#### Scenario: Cancelar no manual
- **WHEN** Círculo cancela uma ação ativa em MANUAL saudável
- **THEN** água é desligada, posição é mantida e MANUAL continua após encerrar a ação

#### Scenario: Cancelar no automático
- **WHEN** Círculo cancela uma ação ativa com modo-base AUTO
- **THEN** água é desligada e AUTO retoma conforme a trajetória limitada, sem interpretar o botão como uma seleção de modo

#### Scenario: Cancelamento antigo após outra ação
- **WHEN** uma solicitação tardia referencia ação já terminada e existe outra ação ativa
- **THEN** ela é recusada como obsoleta e não corta a nova ação

### Requirement: Cancelamento invalida intenções anteriores

Cancelamento válido SHALL criar barreira que invalida pedidos de água anteriores, zerar confirmação automática anterior e impor inibição também quando não há bomba ativa. Pedidos bloqueados SHALL ser descartados, nunca adiados. Círculo SHALL ser documentado como cancelamento temporário, não parada de emergência nem inibição permanente da IA.

#### Scenario: Pedido automático atrasado após cancelar
- **WHEN** um pedido anterior à barreira chega depois do cancelamento
- **THEN** ele é rejeitado mesmo se o prazo de cooldown já terminou

#### Scenario: Cancelar em repouso
- **WHEN** Círculo é aceito sem água ativa
- **THEN** o modo-base permanece igual, intenções anteriores são invalidadas e a inibição pós-cancelamento é aplicada

#### Scenario: Fogo persiste depois da inibição
- **WHEN** o prazo terminou e existe nova confirmação automática de publicações locais válidas no camera_epoch posterior ao cancelamento, respeitando os limites de idade de captura não aferível
- **THEN** um novo disparo pode ser aceito; o sistema não promete bloqueio permanente

### Requirement: Concorrência e idempotência de água

O guardião SHALL aceitar no máximo uma ação de água por vez, contando ACEITA_PENDENTE, ENERGIZADA e DESLIGAMENTO_PENDENTE como ação em curso até confirmação do GPIO desligado pela proteção. Snapshot SHALL expor a fase; um booleano bomba=false SHALL NOT liberar outro pedido ou takeover sem aplicar a política de recuperação. Pedidos simultâneos de origens diferentes SHALL resultar em uma aceitação e recusas explícitas dos demais, sem prioridade que permita prolongar ação existente. Duplicatas SHALL devolver decisão original, e IDs divergentes SHALL NOT ser tratados como nova autorização durante busy/cooldown.

#### Scenario: Takeover antes do GPIO energizar
- **WHEN** existe ACEITA_PENDENTE e o cliente reinicia antes da tarefa de proteção energizar o relé
- **THEN** a aquisição segue RECUPERACAO para essa ação, não aceita outro disparo e um cancelamento válido impede o início pendente

#### Scenario: IA e Quadrado simultâneos
- **WHEN** ambas as solicitações chegam com a bomba disponível
- **THEN** somente uma ação é aceita, a outra recebe motivo e nenhum disparo posterior fica acumulado

#### Scenario: Resposta perdida e comando desconhecido
- **WHEN** não é possível reconciliar um ID após timeout ou retenção expirada
- **THEN** o cliente mantém o resultado desconhecido e não repete cegamente a atuação

### Requirement: Falha durante combate não altera mira

Perda de controle ou lease durante água SHALL marcar retorno AUTO sem retomar varredura antes do término. Somente cancelamento explícito ou limite local SHALL terminar a ação nessa política. Nenhum alvo solicitado durante água SHALL ser aplicado na reanexação do servo.

#### Scenario: Cabo removido durante disparo
- **WHEN** o HID deixa de ser saudável com água ativa
- **THEN** a mira lógica continua congelada, água segue até seu prazo ou cancelamento e o retorno é AUTO

### Requirement: Registro manual separado e honesto

O sistema SHALL registrar solicitações/decisões do operador em log estruturado separado das detecções, distinguindo origem, IDs, solicitado, aceito pelo firmware, recusado, desconhecido e cancelado/concluído segundo firmware. Disparo manual SHALL NOT inserir confiança fictícia nem alterar contagem/estatística de incêndios do painel. Para detecções reais do caminho novo, o campo textual `acao` na tabela existente SHALL refletir aceitação, recusa ou incerteza do comando, sem usar a ação fixa de bomba acionada em caso de falha. Ausência de duração lógica confiável SHALL ser registrada sem inventar duração física.

#### Scenario: Fogo confirmado durante cooldown
- **WHEN** existe detecção real mas o firmware recusa água pelo cooldown
- **THEN** a evidência e confiança reais continuam registradas, a ação informa a recusa e não contradiz o log de controle

#### Scenario: Disparar sem detecção de fogo
- **WHEN** uma solicitação manual é aceita sem evidência de IA
- **THEN** o comando é registrado no log de controle e a tabela de detecções permanece inalterada

#### Scenario: HTTP responde sem sensor de fluxo
- **WHEN** o firmware confirma aceitação
- **THEN** o registro informa aceitação lógica, não confirmação física de água

### Requirement: Falhas de transporte não habilitam fallback perigoso

O cliente SHALL NOT substituir comandos protegidos por `B`, `F`, `X` ou outra rota legada para contornar incompatibilidade ou erro. Cancelamento na rede SHALL NOT ser anunciado como parada elétrica garantida.

#### Scenario: Falha no endpoint de cancelamento
- **WHEN** o comando protegido falha ou fica incerto
- **THEN** o sistema mostra a incerteza e continua dependendo dos limites locais; não envia `X` como substituto silencioso
