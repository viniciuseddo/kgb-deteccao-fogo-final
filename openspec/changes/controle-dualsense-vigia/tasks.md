## 1. Linha de base e contratos antes de implementar

- [x] 1.1 Revisar e aprovar proposta/design, incluindo parâmetros iniciais, cooldown após cancelamento/boot e diferenças da variante; preservar o diff do usuário sem reset, limpeza ou commits automáticos.
- [x] 1.2 Inventariar Python, compilador host, Arduino CLI/core ESP32 e bibliotecas; registrar versões e solicitar autorização antes de instalar ferramentas ausentes.
- [x] 1.3 Materializar em vetores compartilhados Python/C++ os contratos já decididos de sessão/RECUPERACAO, session_open_id idempotente, control_epoch, janelas/escopos, retenção dedup e barreira/capacidade de cancelamento; definir exemplos válidos/inválidos antes de implementar os dois lados.
- [x] 1.4 Caracterizar o caminho atual desabilitado: captura serial, rotação, modelo/confiança, debounce/cooldown nominal, teclas, evidências e contrato SQLite/painel, com recursos falsos e sem hardware.

## 2. Fixtures e testes de entrada primeiro

- [x] 2.1 Versionar fixtures mínimas sintéticas baseadas nas medições de repouso, extremos, Cruz, Triângulo, Quadrado e Círculo, sem depender da pasta temporária ou incluir identificadores pessoais.
- [x] 2.2 Criar testes inicialmente falhos para VID/PID/interface, relatório ID/comprimento, bytes truncados e ambiguidade de dispositivos.
- [x] 2.3 Criar testes inicialmente falhos para normalização assimétrica, zona morta, sinais PAN, máscaras com bits extras e limites.
- [x] 2.4 Criar testes inicialmente falhos para bordas, botão segurado, neutro estável, botões simultâneos, Cruz+Quadrado sem disparo, pressão curta preservada e pausa de 800 ms com backlog HID de Quadrado/eixo, drenagem limitada e rearme sem rejuvenescer relatórios antigos.
- [x] 2.5 Implementar parser/política puros até esses testes passarem, com relógio injetável e sem imports que abram recursos externos.

## 3. Núcleo autoritativo do atuador

- [x] 3.1 Criar variante sem modificar o sketch original, separar núcleo C++ e adaptadores e criar tarefa dedicada de proteção como única proprietária do relé; revisar inicialização fail-closed, prioridade, ausência de I/O/mutex bloqueável e orçamento nominal 5000 ms + J <= 10 ms. Fazer uma compilação mínima cedo, após autorização/instalação das ferramentas necessárias.
- [x] 3.2 Escrever testes host inicialmente falhos para AUTO/MANUAL, entrada sem recentrar, neutro maior que oito segundos e retorno gradual à varredura.
- [x] 3.3 Implementar trajetória não bloqueante, alvo/ângulo/velocidade distintos e limites PAN, testando passos de tempo grandes, validade de velocidade separada do lease, heartbeat sem movimento e fronteiras de faixa.
- [x] 3.4 Escrever e satisfazer testes do lease/watchdog: USB/HID congelado, processo perdido, Wi-Fi perdido, heartbeat inválido e expiração durante combate com retorno AUTO posterior.
- [x] 3.5 Escrever e satisfazer testes do guardião: prazo nominal 5000 ms desde GPIO + orçamento J, cooldown comum de 12 s entre inícios, cancelamento/boot com 12 s de inibição, nenhuma extensão por repetição e nenhuma fila de água; distinguir garantia simulada de medição pendente no S3.
- [x] 3.6 Testar control_epoch na entrada/saída natural/cancelada de combate, inclusive pacote enviado em t=4,9 recebido em t=5,1; rejeitar modo/movimento atrasados e exigir fronteira idle + drenagem/neutro antes da nova entrada manual.
- [x] 3.7 Testar fronteiras/rollover do relógio monotônico usado no ESP, relé desligado na inicialização e invariantes de uma única ação ativa.
- [x] 3.8 Injetar HTTP parcial/lento, LCD/I2C/logging retidos além de 5 s e falha de criação da proteção; demonstrar corte no prazo lógico apesar do loop de aplicação retido, sem usar sucesso do núcleo puro como prova dos adaptadores.

## 4. Protocolo HTTP protegido e compatibilidade explícita

- [x] 4.1 Implementar status aditivo, negociação de capacidades e identidade de boot/sessão; recusar habilitação nova com firmware incompatível.
- [x] 4.2 Implementar validação estrita e janela de frescor emitida pelo S3, testando primeiro pacote atrasado, renovação expirada e consulta que não renova lease.
- [x] 4.3 Implementar IDs/sequências/gerações e dedup com limites de memória; testar mesmo ID com payload diferente, pacote antigo e resultado expirado sem replay.
- [x] 4.4 Implementar cancelamento normal por barreira e RECUPERACAO restrita a action_id; testar S1→S2 durante água protegida/ACK perdido, handshake repetido sem segundo takeover e capacidade atrasada incapaz de cortar ação posterior ou restaurar manual/disparo.
- [x] 4.5 Implementar perfil PROTEGIDO fixado durante o boot após negociação; bloquear letras legadas atuantes também após perda do lease e recusar aquisição durante ação legada ativa.
- [x] 4.6 Testar perfil COMPAT anterior à negociação: nomes/rotas/status preservados com guardião comum, sem prometer idempotência para letras; documentar diferenças em relação ao original.

## 5. Adaptador HID e despachante Python

- [x] 5.1 Adicionar dependência opcional fixada HID em manifesto separado e documentar instalação por venv; não adicionar SDL como dependência operacional.
- [x] 5.2 Implementar adaptador HID de entrada com timeout de leitura, fechamento e reconexão; mocks devem provar ausência de escrita/feature reports e de abertura no caminho desabilitado.
- [x] 5.3 Implementar snapshots com sequência/tempo/input_epoch, detecção de lacunas, drenagem limitada, rearme e invalidação por perda; saúde local não prova hora física da ação. Processar todas as bordas antes de latest-wins, limitar eventos e reservar cancelamento, independentemente dos FPS do YOLO.
- [x] 5.4 Implementar despachante único, movimento latest-wins limitado a 20 Hz, fila discreta limitada e cancelamento prioritário, com testes de saturação.
- [x] 5.5 Testar e implementar timeout curto, resultado desconhecido, reconciliação por ID e ausência de retries cegos ou fallback para letras.
- [x] 5.6 Garantir sessão/lease/frescor consistentes entre os dois lados e descarte de intenções sem validade antes do envio, inclusive água gerada durante busy/cooldown.

## 6. Integração opt-in no Vigia e registros

- [x] 6.1 Adicionar opção explícita de controle ao script principal e manter o caminho desabilitado funcional sem dependência HID instalada.
- [x] 6.2 Integrar Cruz/Triângulo/analógico/Quadrado/Círculo; Quadrado e teclado manual do caminho novo devem obedecer MANUAL e guardião comum, com estado/motivo visíveis.
- [x] 6.3 Encaminhar pedidos automáticos e manuais pelo mesmo transporte protegido no perfil novo, sem reduzir a independência da inferência.
- [x] 6.4 Adicionar frame_id_local/published_at_monotonic/camera_epoch por API aditiva, sem alegar timestamp do sensor; testar pausa e três JPEGs antigos acumulados no parser/COM, descarte/resincronização/primeiro JPEG ignorado e três novas publicações válidas.
- [x] 6.5 Invalidar confirmação/geração causal anterior após cancelamento/falha e testar inferência que começa antes da barreira e termina depois, sem reemitir intenção antiga com sequência HTTP nova; documentar a premissa de atraso sensor→publicação como não medida.
- [x] 6.6 Implementar JSONL de comandos/decisões sem inserir disparos manuais como detecções; usar armazenamento temporário nos testes e nenhum dado real.
- [x] 6.7 No caminho novo, registrar detecções reais com ação aceita/recusada/desconhecida coerente e duração lógica somente quando conhecida, mantendo esquema e contrato do painel.
- [x] 6.8 Testar encerramento limpo, perda de câmera com gamepad/cancelamento ainda responsivos e liberação de HID/threads sem depender de comando final para segurança do S3.

## 7. Integração sem atuador físico e regressão

- [x] 7.1 Construir atuador simulado com relógio/HTTP falsos e cenários de ACK perdido, latência, reorder, sessão/boot trocados, token expirado e cancelamento contra disparo em voo.
- [x] 7.2 Executar todos os cenários das três especificações, incluindo IA+Quadrado simultâneos, manter Quadrado, cancelamento idle, desconectar durante água e reconectar segurando botão.
- [x] 7.3 Demonstrar que o teste da política Python não substitui testes host do núcleo C++; executar ambos e registrar resultados separados.
- [x] 7.4 Verificar que eventos manuais não alteram contagem/confiança do painel e que evidência de incêndio permanece quando água é recusada ou fica incerta.
- [x] 7.5 Comparar regressão do caminho desabilitado e integridade do firmware original; não corrigir a falha offline preexistente silenciosamente nem usar scripts manuais de câmera como suíte.
- [x] 7.6 Compilar a nova variante para a placa S3 indicada com versões registradas e sem upload; executar novo teste USB real somente de entradas com o DualSense disponível.

## 8. Entrega e gates de aceite físico

- [x] 8.1 Documentar instalação opt-in, parâmetros, mensagens de incompatibilidade, perfis COMPAT/PROTEGIDO, limites de cancelamento e rollback para o sketch original.
- [x] 8.2 Corrigir na documentação relevante a descrição de um versus dois eixos e a referência divergente do firmware de câmera, sem regravar ou alterar a câmera nesta mudança.
- [x] 8.3 Entregar matriz explícita de testes executados, limitações e pendências físicas, sem declarar validação de água, torque, alinhamento ou latência de rede inexistente.
- [x] 8.4 Preparar checklist externo: antes de energizar a bomba, medir no S3 o jitter J da proteção sob HTTP/I2C/logging adversos e validar orçamento; depois testar servo/relé/água com alimentação adequada e corte físico. Medir ainda atraso sensor→publicação e ausência de backlog persistente antes de aprovar atuação automática física.
- [ ] 8.5 Obter da equipe com hardware confirmação de firmware, referência temporal/visual da câmera e vídeos representativos; manter gates de jitter, atraso de câmera e aceite de bancada/campo pendentes até ensaio real, separados da conclusão do software.
