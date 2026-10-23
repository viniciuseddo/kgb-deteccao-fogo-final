## ADDED Requirements

### Requirement: Entrada opcional sem efeitos no caminho legado

O sistema SHALL inicializar HID somente quando o controle DualSense for explicitamente habilitado; importar parser/política ou executar testes puros SHALL NOT abrir dispositivos, câmera, COM, rede, janela ou banco.

#### Scenario: Executar sem opção de controle
- **WHEN** o Vigia inicia sem habilitar o recurso e sem a dependência HID instalada
- **THEN** o caminho anterior permanece utilizável e nenhuma interface de gamepad é aberta

#### Scenario: Importar módulos de domínio nos testes
- **WHEN** o runner importa parser e máquina de estados
- **THEN** nenhum recurso externo é inicializado e nenhum dado real é criado

### Requirement: Seleção USB e validação de relatório

O adaptador SHALL aceitar somente um candidato Sony VID `0x054C`, PID `0x0CE6`, usage page 1/usage 5 na interface de gamepad compatível; o parser SHALL interpretar somente relatório ID `0x01` com exatamente 64 bytes. Dados inválidos SHALL NOT renovar saúde nem gerar comandos.

#### Scenario: Relatório USB válido
- **WHEN** um candidato único fornece 64 bytes com ID `0x01`
- **THEN** o snapshot recebe sequência local, input_epoch e timestamp monotônico de leitura; a leitura recente não é tratada como prova da hora da ação física

#### Scenario: ID ou comprimento inválido
- **WHEN** chegam bytes truncados, relatório Bluetooth, outro ID ou comprimento inesperado
- **THEN** o parser rejeita a entrada sem ação nem renovação de lease

#### Scenario: Ausência ou seleção ambígua
- **WHEN** não existe candidato ou existem vários candidatos compatíveis
- **THEN** o manual fica desabilitado com motivo explícito, sem escolher silenciosamente outro dispositivo

### Requirement: Eixo horizontal normalizado e zona morta

O parser SHALL obter o eixo horizontal do byte 1 e mapear 0 para -1, 128 para 0 e 255 para +1 com normalização assimétrica. A política SHALL aplicar zona morta configurável, inicialmente 10% da meia-faixa, reescalar o restante e limitar saída a [-1,+1]. A velocidade SHALL depender de tempo monotônico, não da taxa de inferência.

#### Scenario: Centro observado depois do uso
- **WHEN** chegam valores 128, 129 ou 130 com a zona morta inicial
- **THEN** a velocidade solicitada é zero, sem recentrar a câmera

#### Scenario: Extremos e sentido lógico
- **WHEN** o valor é 0 ou 255 no modo manual
- **THEN** a política solicita respectivamente velocidade PAN positiva ou negativa, limitada ao máximo configurado

#### Scenario: Inferência com taxas diferentes
- **WHEN** o mesmo comando é mantido pelo mesmo tempo com FPS distintos
- **THEN** a trajetória lógica independe desses FPS e respeita velocidade/limites

### Requirement: Máscaras de botões confirmadas

O parser SHALL ler no byte 8 as máscaras Cruz `0x20`, Triângulo `0x80`, Quadrado `0x10` e Círculo `0x40`, sem comparar o byte inteiro por igualdade.

#### Scenario: Botão com outros bits ativos
- **WHEN** Quadrado aparece junto de bits de direcional no mesmo byte
- **THEN** Quadrado é reconhecido pela máscara sem reinterpretar os demais bits como outros botões

### Requirement: Rearme deliberado e bordas

A política SHALL iniciar desarmada e exigir 300 ms configuráveis de snapshots válidos com eixo neutro e os quatro botões soltos. Cada ação discreta SHALL resultar de nova borda; eventos durante desarme SHALL ser descartados e exigir soltura antes de nova tentativa.

#### Scenario: Iniciar segurando Quadrado
- **WHEN** o controle conecta com Quadrado pressionado
- **THEN** não existe intenção de disparo até neutro/soltura estáveis, seleção manual válida e novo pressionamento

#### Scenario: Manter botão pressionado
- **WHEN** Quadrado permanece pressionado por centenas de relatórios
- **THEN** é emitida no máximo uma intenção de disparo por pressionamento válido

#### Scenario: Relatório antigo ou HID congelado
- **WHEN** a thread permanece viva mas não recebe entrada válida recente por mais de 500 ms configuráveis
- **THEN** o snapshot deixa de habilitar ações e não sustenta o lease manual

### Requirement: Prioridade determinística entre botões

A política SHALL aplicar Círculo > Triângulo > Cruz > Quadrado > analógico. Somente uma ação de botão por snapshot SHALL ser considerada; as demais bordas simultâneas SHALL ser descartadas, exigindo nova borda. Entrar no manual e disparar no mesmo relatório SHALL NOT ser permitido.

#### Scenario: Cruz e Quadrado simultâneos
- **WHEN** ambos apresentam borda no mesmo relatório
- **THEN** somente a entrada manual é considerada e não ocorre disparo

#### Scenario: Círculo e Quadrado simultâneos
- **WHEN** ambos apresentam borda no mesmo relatório
- **THEN** somente o cancelamento é considerado e a intenção de disparo não é preservada para depois

### Requirement: Reconexão sem restauração involuntária

Após remoção, erro de leitura ou sessão perdida, o adaptador SHALL fechar/liberar recursos, invalidar snapshots e rearmar apenas com nova entrada neutra. Reconectar SHALL NOT restaurar modo manual, posição pendente ou intenção de água.

#### Scenario: Reabrir USB com analógico deslocado
- **WHEN** o controle retorna com o analógico para a direita e Quadrado segurado
- **THEN** o sistema permanece sem comando manual até o procedimento de rearme e uma nova seleção manual

### Requirement: Descontinuidade e descarte de backlog HID

Uma lacuna de aquisição superior a 100 ms configuráveis, erro, reconexão, overflow ou perda de sessão SHALL invalidar o input_epoch, bordas e autorizações anteriores, mesmo antes de expirar o lease S3. O cliente SHALL deixar de renovar manual e SHALL drenar os relatórios acumulados sem gerar ações, até observar fila vazia em leitura não bloqueante. Cada tentativa SHALL ser limitada a 4096 relatórios ou 100 ms; insucesso SHALL manter desarme com novas tentativas espaçadas. Após a fronteira vazia, somente um novo fluxo sem lacunas e 300 ms de neutro/botões soltos SHALL rearmar, exigindo nova seleção manual. Timestamp novo SHALL NOT reabilitar relatório descartado.

#### Scenario: Pausa menor que o lease com Quadrado acumulado
- **WHEN** a aquisição pausa 800 ms em MANUAL e o driver acumula pressões/solturas de Quadrado durante a pausa
- **THEN** a retomada invalida o epoch e descarta essas bordas; nenhum disparo ocorre com token novo e o manual exige rearme e nova seleção

#### Scenario: Eixo antigo na fila
- **WHEN** existem relatórios antigos de eixo deslocado antes da fronteira de fila vazia
- **THEN** nenhum deslocamento é emitido por eles, mesmo que o timestamp de leitura seja atual

#### Scenario: Driver não pode ser drenado dentro do limite
- **WHEN** o limite de tempo/quantidade é atingido antes de observar vazio
- **THEN** entrada permanece desarmada, sem renovação manual e sem laço ocupado ou autorização implícita

### Requirement: Bordas discretas não se perdem em latest-wins

A aquisição SHALL processar as bordas de cada relatório antes de sobrescrever movimento. Eventos discretos SHALL portar epoch/validade em estrutura limitada com reserva para cancelamento; overflow SHALL invalidar intenções inseguras e desarmar, não reproduzir fila posteriormente.

#### Scenario: Pressão curta entre atualizações de movimento
- **WHEN** Círculo é pressionado e solto entre duas oportunidades de envio de movimento
- **THEN** o evento de cancelamento válido não desaparece por sobrescrita do snapshot, e eventos expirados não são executados depois

### Requirement: Aquisição somente de entradas

O adaptador desta versão SHALL NOT enviar relatórios de saída/feature reports, vibração, configuração de LEDs ou comandos de atualização de firmware ao DualSense.

#### Scenario: Exercitar todo o ciclo de entrada
- **WHEN** o teste cobre enumeração, abertura, leitura, erro, fechamento e reconexão
- **THEN** o mock HID confirma zero chamadas de escrita ou configuração de efeitos
