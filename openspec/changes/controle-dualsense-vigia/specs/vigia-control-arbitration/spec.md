## ADDED Requirements

### Requirement: Negociação de capacidades antes do controle

O cliente SHALL habilitar as ações novas somente após verificar versão compatível, boot ID e capacidades de PAN manual, watchdog, bomba protegida, cancelamento sem troca de modo e idempotência. O firmware SHALL preservar os campos legados de `/status` e acrescentar os novos campos sem mudar seu significado básico.

#### Scenario: Firmware antigo responde
- **WHEN** `/status` contém somente os campos legados
- **THEN** o controle novo fica desabilitado com aviso; não há fallback de Quadrado para `B` nem Círculo para `X`

#### Scenario: Versão compatível
- **WHEN** todas as capacidades exigidas são negociadas
- **THEN** o cliente conhece limites/cooldown e pode iniciar sessão e rearme de entrada

### Requirement: Manual mantém posição em neutro

O firmware SHALL separar modo-base AUTO/MANUAL da atividade da bomba. Manual saudável SHALL persistir em neutro sem recentrar nem retornar pela regra legada de oito segundos. A opção de entrar no manual SHALL manter o ângulo comandado atual.

#### Scenario: Neutro manual além de oito segundos
- **WHEN** o operador está no manual com relatórios e lease saudáveis por mais de oito segundos sem mover o analógico
- **THEN** o ângulo é mantido e a varredura não retorna

#### Scenario: Voltar ao automático
- **WHEN** Triângulo é aceito fora de combate
- **THEN** a sessão libera o lease manual e a varredura retoma por movimento limitado, sem salto para o preset

### Requirement: Lease local ligado à saúde HID

O firmware SHALL expirar o lease manual com relógio monotônico local após 1500 ms configuráveis sem renovação válida. O cliente SHALL renovar somente com HID fresco, mesmo se seu processo estiver vivo. Uma consulta de status ou mensagem inválida SHALL NOT renovar o lease.

#### Scenario: Falha de USB, processo ou Wi-Fi
- **WHEN** qualquer uma dessas falhas impede renovação válida fora de combate
- **THEN** o firmware expira o lease, elimina alvos pendentes e retorna a AUTO sem depender de comando final do computador

#### Scenario: Heartbeat com snapshot antigo
- **WHEN** o heartbeat dispõe apenas de entrada HID mais antiga que o limite de frescor
- **THEN** ele não renova o lease manual

### Requirement: Combate sobrepõe movimento sem acumulação

Ao aceitar um disparo, o firmware SHALL congelar o ângulo comandado e suspender varredura. Durante água, movimento e troca de modo pelo gamepad SHALL ser descartados sem alterar o alvo. Ao terminar, SHALL retomar o modo-base anterior, salvo fallback AUTO já determinado por perda de saúde.

#### Scenario: Mover e trocar modo durante água
- **WHEN** o operador mantém o analógico deslocado e pressiona Triângulo durante um disparo
- **THEN** esses eventos não mudam o alvo nem o modo de retorno e não são executados posteriormente

#### Scenario: Novos comandos depois da água
- **WHEN** o cliente confirma idle com control_epoch novo, drena a fila HID e observa novo fluxo neutro estável no manual ainda saudável
- **THEN** somente amostras/bordas adquiridas depois dessa fronteira podem iniciar movimento; manter analógico deslocado desde o combate não autoriza retomada automática

#### Scenario: Lease expira durante água
- **WHEN** a renovação para no meio do disparo
- **THEN** a mira permanece congelada, a água termina pelo limite local ou cancelamento explícito, e o retorno é AUTO

### Requirement: Fronteira de combate verificável no recebimento

O S3 SHALL incrementar control_epoch na entrada e na saída de combate, natural ou por cancelamento. Tokens e comandos de movimento, modo, disparo e renovação SHALL estar vinculados ao epoch autorizado e SHALL ser rejeitados em epoch posterior, mesmo se sua validade temporal ainda não expirou. Cancelamento SHALL usar autorização restrita por tempo e alvo/barreira, sem poder de atuar sobre ação futura. O cliente SHALL confirmar a fronteira idle, descartar filas antigas e observar novo fluxo neutro antes de ações manuais. Gerações locais SHALL impedir inferência anterior à barreira de publicar novo pedido com sequência HTTP posterior.

#### Scenario: Movimento atravessa término natural
- **WHEN** uma amostra gerada em t=4,9 durante água até t=5 chega em t=5,1 com janela temporal ainda válida
- **THEN** o S3 a rejeita por epoch anterior, sem movimento ou troca de modo

#### Scenario: Pacote cruza cancelamento
- **WHEN** um comando de modo/movimento anterior ao cancelamento chega depois que Círculo encerrou água e alterou o epoch
- **THEN** ele é recusado e não ressuscita intenção antiga

#### Scenario: Inferência começou antes de Círculo e terminou depois
- **WHEN** um resultado é publicado com geração causal anterior à barreira local de cancelamento
- **THEN** ele não cria disparo, mesmo que tentasse receber uma nova sequência HTTP

### Requirement: Atualização de movimento não bloqueante

A variante nova SHALL atualizar trajetórias por passos limitados e atender temporização da bomba/HTTP sem laços bloqueantes de movimento. PAN SHALL permanecer dentro dos limites configurados; retorno à faixa de varredura SHALL ser gradual. Velocidade manual SHALL expirar localmente após no máximo 500 ms configuráveis sem novo estado de movimento; heartbeat isolado SHALL NOT prolongá-la. Recuperação após pausa SHALL NOT integrar movimento retroativo além da validade.

#### Scenario: Heartbeat continua sem novos movimentos
- **WHEN** a última velocidade era não nula, mas chegam apenas renovações de saúde sem novo estado de movimento
- **THEN** a velocidade zera ao vencer sua validade, mantendo manual parado enquanto o lease continuar saudável

#### Scenario: Movimento atravessa grande amplitude
- **WHEN** existe destino distante e chega cancelamento de água
- **THEN** o controlador não precisa terminar a trajetória para processar o evento; limites e prazo local da bomba continuam verificáveis

#### Scenario: Retorno de posição fora da faixa de varredura
- **WHEN** AUTO retoma de um ângulo manual entre o limite mecânico lógico e o limite de varredura
- **THEN** a trajetória até a faixa é limitada em velocidade, sem alteração instantânea do ângulo comandado

### Requirement: Emissor único e dados ultrapassados descartados

O caminho novo SHALL usar um único despachante HTTP, no máximo uma chamada em voo, movimento latest-wins e filas limitadas. Cancelamento SHALL ter prioridade; disparos ou movimentos sem validade SHALL ser descartados, não adiados. A chamada em voo SHALL ter timeout configurável, inicialmente 200 ms, sem promessa de prazo físico.

#### Scenario: Produção de entrada mais rápida que HTTP
- **WHEN** chegam cerca de 250 relatórios/s e a rede atende mais lentamente
- **THEN** o número de threads/fila permanece limitado e movimento não ultrapassa 20 envios/s configuráveis

#### Scenario: Cancelar enquanto existe chamada em voo
- **WHEN** Círculo é detectado durante outra chamada
- **THEN** ele recebe a próxima oportunidade de envio, remove intenções obsoletas e não cria uma segunda chamada concorrente

### Requirement: Identidade, ordenação e resultado incerto

O protocolo novo SHALL validar boot, sessão/geração, control_epoch/escopo, sequência, ID de comando e janela de frescor emitida pelo S3 com expiração em seu relógio monotônico; pacotes obsoletos ou expirados no recebimento SHALL ser rejeitados sem atuação ou renovação de lease. A validade inicial da janela SHALL ser 500 ms configuráveis. Uma duplicata conhecida SHALL retornar a decisão original sem repetir efeito, mesmo se já não puder atuar novamente. Timeout SHALL ser registrado como desconhecido e SHALL NOT gerar replay automático com ID novo.

#### Scenario: Primeiro pacote chega muito atrasado
- **WHEN** uma ação ou renovação de lease chega com janela expirada, mesmo sem sequência posterior conhecida
- **THEN** o firmware rejeita o pacote sem atuação e sem prolongar o lease

#### Scenario: Resposta perdida após aceitar água
- **WHEN** o firmware aceitou o disparo mas o cliente não recebeu resposta
- **THEN** o cliente reconcilia por status/ID, mantém resultado desconhecido até confirmação e não solicita outro disparo para compensar

#### Scenario: Pacote anterior chega depois de reconectar ou reiniciar
- **WHEN** boot ou sessão/geração já mudou
- **THEN** o firmware rejeita o pacote antigo sem mover nem ligar água

#### Scenario: Mesmo ID com conteúdo diferente
- **WHEN** um ID já conhecido reaparece com outro payload
- **THEN** a requisição é recusada e não renova saúde nem altera o resultado anterior

### Requirement: Abertura idempotente e recuperação de ação ativa

O cliente SHALL atribuir session_open_id antes de abrir sessão; repetição SHALL retornar a decisão original sem executar outro takeover ou reativar sessão substituída. Boot/janela de abertura expirados SHALL ser rejeitados. Sessão nova sem ação em curso SHALL iniciar AUTO desarmado. Se houver ação protegida em curso, inclusive aceita pendente antes de energizar ou desligamento ainda não confirmado, a sessão nova SHALL entrar em RECUPERACAO: revogar comandos da anterior, receber identidade da ação e capacidade restrita para cancelar somente essa ação, marcar retorno AUTO e recusar movimento/seleção manual/disparo até idle confirmado. A ação e seu prazo SHALL permanecer inalterados. A transferência SHALL NOT permitir replay nem cancelamento de ação posterior.

#### Scenario: Cliente reinicia com água e ACK perdido
- **WHEN** S1 iniciou A, perdeu o ACK e o novo processo negocia S2 antes do término de A
- **THEN** S2 recebe autoridade restrita de cancelamento de A, Círculo pode interrompê-la e nenhum disparo ou manual é restaurado

#### Scenario: Resposta do handshake se perde
- **WHEN** o cliente repete o mesmo session_open_id após timeout
- **THEN** o firmware retorna a mesma decisão sem trocar de sessão novamente ou prolongar A

#### Scenario: Cancelamento de recuperação chega após A terminar
- **WHEN** a capacidade vinculada a A chega quando A já terminou e existe outra ação ou nenhum disparo
- **THEN** ela não corta nem autoriza ação diferente, e o cliente deve reconciliar o estado

### Requirement: Compatibilidade legada sem contornar guardas

O sketch original SHALL permanecer intacto. A variante nova SHALL documentar perfis COMPAT e PROTEGIDO; todos os caminhos de bomba SHALL respeitar o guardião comum. Negociar sessão protegida SHALL bloquear comandos legados de movimento, água e modo durante o restante do boot, inclusive após expiração do lease. IA e teclado do caminho novo SHALL usar ações tipadas. No perfil COMPAT anterior à negociação, os comandos legados SHALL manter sua semântica documentada com os novos limites de segurança, sem promessa de identidade/idempotência para letras. Retornar a COMPAT SHALL exigir manutenção/reboot explícito, não falha de USB ou rede.

#### Scenario: Letra antiga chega após perda do controle
- **WHEN** uma sessão protegida já foi negociada e o lease expirou, mas chega `F`, `B`, `X`, `V` ou movimento legado
- **THEN** a variante rejeita a letra sem atuar; o perfil não retorna implicitamente a COMPAT

#### Scenario: Negociar com ação legada ainda ativa
- **WHEN** existe água iniciada antes da sessão protegida
- **THEN** a aquisição da nova sessão é recusada até a ação terminar, sem transferência ambígua de propriedade

#### Scenario: Cliente legado envia bomba repetidamente na variante nova
- **WHEN** chegam `F` ou `B` durante água ou cooldown
- **THEN** o timer não reinicia e o limite local não é contornado

#### Scenario: Cliente de controle incompatível
- **WHEN** o usuário habilita controle com firmware sem suporte
- **THEN** nenhum comando novo é improvisado; o estado de incompatibilidade fica visível e o pipeline legado permanece identificável

### Requirement: Confirmação por publicações locais sem prometer idade de captura

A integração nova SHALL contar três IDs locais distintos no camera_epoch corrente, publicados depois da fronteira aplicável e com idade desde publicação local de até 1000 ms configuráveis. Os nomes SHALL distinguir frame_id_local/published_at_monotonic de timestamp do sensor; o sistema SHALL NOT afirmar idade real de captura, não disponível no protocolo preservado. Cancelamento ou falha relevante SHALL invalidar a confirmação anterior; manual/cancelamento SHALL continuar funcionando sem publicação válida.

#### Scenario: Último quadro publicado permanece congelado
- **WHEN** o mesmo frame_id_local é inferido repetidamente ou sua idade local excede o limite
- **THEN** ele não completa nova confirmação nem autoriza disparo automático

#### Scenario: Novo evento após cancelamento
- **WHEN** o cooldown terminou e existem três novas publicações locais válidas, distintas e da geração posterior à barreira
- **THEN** uma nova solicitação automática pode ser avaliada, sem afirmar quando o sensor capturou a cena

### Requirement: Resincronização de câmera e limite de backlog declarado

Partida/reconexão, pausa de leitura superior a 500 ms configuráveis, erro, backlog fora do orçamento ou barreira de cancelamento SHALL invalidar o camera_epoch. O receptor SHALL limpar parser e descartar entrada COM pendente, resincronizar o marcador e descartar o primeiro JPEG completo após a fronteira. JPEGs intermediários de lote acumulado SHALL NOT ser publicados como uma sequência de novas evidências. Quadros descartados/gerações antigas SHALL NOT contar para confirmação. Bytes ainda no transmissor SHALL ser reconhecidos como idade não aferível.

#### Scenario: Três JPEGs antigos em buffers locais
- **WHEN** o host retoma após pausa com três JPEGs diferentes já acumulados no parser/COM
- **THEN** eles são descartados sem novo timestamp de evidência e não completam três quadros depois da retomada

#### Scenario: Círculo com bytes pendentes de imagem
- **WHEN** o cancelamento cria nova barreira enquanto há JPEGs locais pendentes
- **THEN** a fronteira de câmera invalida esses dados e inferências antigas não geram disparos posteriores

#### Scenario: Atraso remoto não é mensurável
- **WHEN** o stream chega sem timestamp do sensor
- **THEN** o relatório distingue idade local de idade real e não declara frescor end-to-end comprovado

### Requirement: Premissa física da atuação automática explicitamente gateada

O aceite físico da atuação automática SHALL exigir stream contínuo sem backlog persistente e validação do orçamento sensor→publicação desejado de 1000 ms na configuração escolhida. Essa premissa SHALL constar como não medida enquanto não houver bancada. Se não for sustentada, o aceite físico SHALL ser bloqueado e eventual mudança de protocolo SHALL exigir autorização separada; conclusão do software SHALL NOT marcar essa premissa como teste passado.

#### Scenario: Software pronto sem referência temporal da câmera
- **WHEN** passam testes locais e compilação, mas não existe ensaio de atraso sensor→publicação
- **THEN** a entrega pode registrar conclusão de software, mantendo atuação automática física não aprovada e premissa pendente
