## Context

Esta mudança planeja a integração; não implementa controle nem regrava placas. A revisão R2 trata as cinco lacunas da rodada adversarial R1 e deve ser reavaliada antes da aprovação humana; as definições de domínio estão no [glossário](<C:/Users/orugi/Documents/Projetos/KGB-sompo/CONTEXT.md>). O usuário confirmou o Vigia de um eixo PAN, com câmera e bico solidários, detecção automática sempre ativa e DualSense USB disponível. O conjunto ESP32/servo/bomba não está disponível.

O [script atual](<C:/Users/orugi/Documents/Projetos/KGB-sompo/sistema_vigia.py#L174-L214>) envia HTTP em uma thread por comando. O [firmware atual](<C:/Users/orugi/Documents/Projetos/KGB-sompo/arduino/esp32s3_vigia_bomba/esp32s3_vigia_bomba.ino#L217-L245>) retorna à varredura após oito segundos e bloqueia durante rampas. Durante água, mover pode alterar o alvo armazenado sem mover o servo. `X` e `V` desligam água e retomam varredura, portanto não atendem ao cancelamento sem troca de modo.

A leitura HID direta funcionou; SDL com HIDAPI desabilitado não enumerou o dispositivo, inclusive fora do confinamento. Essa falha não é atribuída definitivamente ao Windows, ao controle ou ao SDL.

### Evidência de entrada

Offsets baseados em zero, incluindo report ID no byte 0:

| Controle | Valor medido | Ação planejada |
|---|---|---|
| Analógico esquerdo horizontal, byte 1 | 0 esquerda; 128–130 repouso observado; 255 direita | Velocidade PAN no manual |
| Cruz, byte 8, máscara `0x20` | Confirmado em posição mantida | Entrar no manual |
| Triângulo, byte 8, máscara `0x80` | Confirmado em posição mantida | Entrar no automático |
| Quadrado, byte 8, máscara `0x10` | 499 relatórios em 2 s; byte completo `0x18` | Disparo manual somente no manual |
| Círculo, byte 8, máscara `0x40` | 497 relatórios em 2 s; byte completo `0x48` | Cancelar água sem trocar modo |

O byte de repouso foi `0x08`; os botões são máscaras, não valores de igualdade. Amostragem de entrada observada próxima de 250 Hz não é orçamento de HTTP nem latência do atuador. Medições locais permanecem na pasta temporária de diagnóstico; os testes futuros versionarão fixtures mínimas, sem depender dessa pasta.

## Goals / Non-Goals

**Goals:**

- Preservar o fluxo atual quando o recurso estiver desligado e manter o firmware original como rollback.
- Oferecer manual persistente em neutro, retorno automático em falha e combate prioritário.
- Permitir água manual deliberada e cancelamento, com limites autoritativos no S3.
- Validar políticas sem YOLO, câmera, COM, banco real, rede externa ou ESP físico.
- Mostrar claramente estado, incompatibilidade e resultado incerto, sem afirmar execução física.

**Non-Goals:**

- Bluetooth, TILT, firmware do DualSense, vibração, LEDs do controle ou engenharia reversa do seu firmware.
- Alterar modelo/confiança padrão, pinagem, alimentação ou arquitetura USB da câmera/Wi-Fi do S3.
- Exibir histórico manual no painel ou migrar tabelas SQLite nesta entrega.
- Resolver todos os problemas preexistentes dos scripts legados.
- Certificar segurança física ou substituir parada elétrica de emergência.

## Decisions

### 1. Variante opt-in e preservação da referência

Criar um novo sketch `arduino/esp32s3_vigia_dualsense/esp32s3_vigia_dualsense.ino`, derivado do Vigia validado. O original não será sobrescrito. Novos módulos Python serão ativados somente por opção explícita, proposta `--controle-dualsense`; sem ela, não importar HID nem abrir controles.

A variante manterá nomes/rotas e campos legados relevantes, mas TODOS os seus caminhos de bomba, inclusive serial, `F`, `B` e teclado, passarão pelo mesmo guardião. Repetir `B` não reiniciará o temporizador. Essa é uma diferença de segurança declarada, não uma promessa de equivalência exata com o firmware original. Com o recurso novo habilitado, `f` também respeitará a habilitação manual e as proteções comuns; o caminho original desabilitado permanece caracterizado.

Alternativa rejeitada: substituir imediatamente o sketch validado e tratar diferenças de temporização como se fossem invisíveis. Uma variante custa duplicação inicial, mas oferece rollback físico explícito e comparação de comportamento.

### 2. Aquisição HID pequena e desacoplada

Adaptador somente de entrada com `hidapi==0.15.0`, dependência opcional em manifesto separado. SDL não será dependência de produção nesta primeira versão. A enumeração exige VID/PID, usage page 1/usage 5 e interface apropriada; zero ou múltiplos candidatos não habilitam manual automaticamente.

O parser recebe bytes puros e valida ID e comprimento antes de interpretar. A aquisição entrega snapshot imutável com sequência local, `input_epoch` e timestamp monotônico de LEITURA, sem chamar HTTP, YOLO ou SQLite. Esse timestamp não prova a hora da ação física nem rejuvenesce uma fila antiga. APIs de saída/feature reports não serão usadas.

Uma pausa entre iterações de aquisição acima de 100 ms configuráveis, erro, reconexão, backlog acima do limite ou perda de sessão invalida imediatamente o `input_epoch`, as bordas e a autorização de movimento/disparo. Mesmo que o lease S3 de 1500 ms ainda não tenha vencido, o cliente deixa de renová-lo e não usa um token novo para transmitir amostras dessa fila. A entrada entra em RESINCRONIZACAO: drenar em leitura não bloqueante até observar fila vazia, descartando todos os relatórios; limite inicial de drenagem 4096 relatórios ou 100 ms por tentativa. Se não alcançar vazio, continuar desarmado com tentativas espaçadas, sem laço ocupado nem atuação.

Após a fronteira de fila vazia, observar um NOVO fluxo com lacunas abaixo de 100 ms e 300 ms de neutro/botões soltos antes de rearmar; uma nova seleção manual será necessária após descontinuidade. Relatórios de botão/eixo acumulados durante a pausa não geram bordas nem deslocamento. Uma leitura recém-feita, sozinha, não comprova saúde. Não se presume contador/timestamp de hardware não medido. A premissa operacional é aquisição contínua capaz de esvaziar a fila do driver; latência física oculta sem descontinuidade não é mensurável por estes relatórios e permanece limite declarado do aceite.

A aquisição processa bordas em cada relatório antes de sobrescrever o snapshot de movimento. Movimento é latest-wins; ações discretas são eventos com epoch/validade em estrutura limitada, com reserva para cancelamento. Overflow desarma e invalida intenções inseguras, nunca transforma fila acumulada em novos disparos. O despachante rejeita qualquer evento cujo epoch já foi invalidado.

Normalizar o eixo assimetricamente ao redor do centro nominal 128 para alcançar -1 e +1 nos extremos, aplicar zona morta e reescalar o restante. Neutro é uma faixa, não igualdade a 128. O firmware já define ângulo maior como esquerda; portanto sinal horizontal negativo implica velocidade PAN positiva. O sentido físico só será confirmado em bancada.

Botões usam bordas. Ao iniciar/reconectar, exigir pelo menos 300 ms de relatórios válidos com analógico neutro e os quatro botões soltos. Uma borda recebida antes de armar é descartada e exige soltar/pressionar novamente. Entrar no manual e disparar no mesmo relatório não é permitido.

### 3. Máquina de estados com combate sobreposto

Separar `modo_base = AUTO | MANUAL` de `bomba_ativa`. Não representar combate como uma troca destrutiva do modo-base.

| Evento | Efeito |
|---|---|
| Inicialização, sem seleção manual | AUTO, bomba desligada |
| Cruz com entrada armada/neutra | Adquire lease; MANUAL na posição atual, sem recentrar |
| Neutro em MANUAL, comunicação saudável | Mantém enquadramento |
| Triângulo fora de combate | Libera lease; AUTO |
| Quadrado em MANUAL saudável | Solicita disparo protegido |
| Quadrado em AUTO | Rejeita; não muda modo e não dispara |
| Fogo confirmado em qualquer modo | Solicita disparo automático protegido |
| Disparo aceito | Congela alvo; suspende varredura; descarta movimento e troca de modo durante água |
| Fim da água | Retoma modo-base; sem salto para movimento antigo |
| Círculo em qualquer modo | Cancela ação de água atual; preserva modo-base, salvo fallback AUTO já determinado por falha |
| Lease/HID/computador perdidos fora de combate | Descarta movimento; AUTO |
| Falha durante combate | Mantém mira congelada, deixa limite local terminar ou aceita cancelamento explícito; marca retorno AUTO |
| Reconexão | Não ressuscita lease/modo/comandos; rearmar e selecionar manual novamente |

Prioridade na mesma amostra: Círculo > Triângulo > Cruz > Quadrado > analógico. Se dois ou mais botões de ação surgirem juntos, somente o de maior prioridade é considerado; os demais exigem nova borda. Durante combate, apenas cancelamento/fallback e manutenção de saúde são considerados; eventos de modos/movimento são descartados, não adiados.

O firmware não deverá atualizar sequer o alvo PAN ao rejeitar movimento durante água. A posição publicada será identificada como ângulo comandado, não posição medida por encoder.

Cada entrada e cada saída de combate (natural ou por cancelamento) incrementa um `control_epoch` autoritativo no S3. Tokens de movimento, modo, disparo e renovação são vinculados ao epoch em que foram emitidos; um pacote de epoch anterior é recusado mesmo se chegar depois do término e ainda estiver dentro dos 500 ms de validade temporal. A exceção é cancelamento: usa autorização curta de cancelamento e alvo/barreira restritos à ação, não autorização para atuar em epoch novo; nunca ganha poder de cortar uma ação posterior à sua barreira.

Após observar status/ACK de término com epoch novo e estado idle, o cliente invalida suas intenções anteriores, drena a fila HID e estabelece nova fronteira de leitura. No modo-base MANUAL, fica parado até novo fluxo neutro estável por 300 ms; não exige Cruz outra vez se a sessão/lease continuam saudáveis, mas exige movimento/borda adquiridos depois dessa fronteira. Assim analógico mantido durante a água não vira movimento ao terminar. Em AUTO, a varredura local pode retomar sem esperar o cliente. Uma pausa/perda de saúde, por sua vez, segue o rearme completo e a nova seleção manual definidos acima.

Toda intenção local também carrega uma geração causal: Círculo e mudanças de fronteira incrementam a geração antes de limpar as filas. Inferência iniciada antes da barreira não pode publicar um disparo depois dela com sequência HTTP nova. O produtor registra a geração e o identificador de publicação da imagem ao iniciar a inferência; resultados de geração antiga são descartados.

### 4. Guardião único de bomba

Prazo nominal local inicial: 5000 ms, sem alteração por `--tempo-bomba` (atualmente apenas metadado). A promessa não é um máximo físico absoluto de 5000 ms com jitter zero. Com MCU e escalonador funcionando dentro do orçamento admitido, o comando GPIO de desligamento deverá ocorrer até `inicio_gpio + 5000 ms + J`, com objetivo inicial `J <= 10 ms`. Tempo do relé, vazão e travamento total do MCU não estão abrangidos por essa garantia de software e exigem corte/ensaio físicos. Disparo já ativo não é prolongado por IDs iguais ou diferentes.

Na variante nova, uma tarefa FreeRTOS dedicada de proteção da bomba, de prioridade superior ao atendimento HTTP/LCD/logging, será a única proprietária do GPIO do relé após a inicialização segura. Ela controla início, prazo e cancelamento, emite snapshot/eventos para a aplicação e não chama rede, Serial, I2C, servo, logging, alocação de heap ou mutex cujo proprietário possa bloquear em I/O. Suas seções críticas terão orçamento curto; o período/resposta de escalonamento compõe J. A rotina de aplicação pode pedir início/cancelamento por interface limitada não bloqueante, mas não escrever no relé nem reiniciar o prazo por conta própria. A tarefa é criada antes de habilitar qualquer atuação; falha de criação/proteção mantém relé desligado e recusa água, sem fallback para B.

O gate de software exige testes do mesmo núcleo real mais integração dos adaptadores com HTTP parcial/lento, LCD/I2C e logging artificialmente retidos por mais que o prazo de água, enquanto a proteção continua recebendo escalonamento e corta dentro do orçamento simulado. A compilação e a revisão da separação de tarefas não comprovam J no S3: medir a latência do GPIO sob carga é gate de bancada antes de energizar a bomba. Se J não puder ser sustentado, o aceite físico fica bloqueado e o orçamento/arquitetura deve ser revisto, não mascarado por testes de um simulador Python.

Cooldown inicial proposto: 12000 ms entre INÍCIOS aceitos, medidos na transição de energização GPIO da proteção, preservando o intervalo nominal padrão do Python. A intenção aceita antes dessa transição é pendente e pode ser cancelada sem ligar o relé; não libera outro pedido nem inicia dois timers. Para exclusão, combate, cancelamento e recuperação de sessão, ação em curso inclui ACEITA_PENDENTE, ENERGIZADA e DESLIGAMENTO_PENDENTE até a proteção confirmar o GPIO desligado. O snapshot publica a fase; não usar apenas o booleano bomba para concluir que é seguro trocar de sessão ou aceitar novo disparo. Após cancelamento, próxima aceitação será `max(limite_anterior, instante_do_cancelamento + 12000 ms)`. Assim há também 12 s mínimos de inibição após Círculo, inclusive se a bomba já estiver parada. Pedidos bloqueados são descartados, nunca enfileirados para mais tarde. A nova variante também adotará inibição de 12 s após boot para evitar que reset reduza a proteção; isso será documentado como diferença opt-in.

Círculo cancela a ação corrente, invalida intenções anteriores e não é inibição permanente. Após o cooldown, a IA poderá voltar a solicitar água se houver NOVA confirmação válida. O contador de confirmação automática é zerado após cancelamento/falha relevante; imagens anteriores ao evento não podem sustentar a nova confirmação.

A identidade de uma ação aceita será o próprio `command_id` do disparo, conhecido pelo cliente antes do ACK. Círculo enviará `cancel_through_sequence`: uma barreira sobre intenções emitidas pela sessão até a sequência conhecida no instante do botão. O firmware corta a ação ativa dessa sessão somente se sua sequência de início estiver abrangida pela barreira; mesmo sem ação ativa, invalida pedidos anteriores e aplica a inibição. Assim é possível cancelar um disparo cujo ACK se perdeu e cujo status anterior era idle. Um cancelamento atrasado não corta ação posterior à barreira. A exceção controlada de RECUPERACAO permite à sessão nova cancelar a ação anterior pelo `action_id` e capacidade restrita devolvidos pelo S3, sem ampliar a barreira para ações futuras. Durante resultado de disparo desconhecido, reconciliar status antes de novo disparo manual; não converter timeout em repetição com outro ID.

Alternativa rejeitada: cooldown somente no Python ou chamar `B` diretamente. Ambos permitem contornar proteções com retransmissão, múltiplas origens ou cliente legado.

### 5. Protocolo adicional e transporte limitado

Preservar `/status` e seus campos `pan`, `vigiando`, `fogo`, `bomba`; adicionar versão/capacidades, boot ID, modo-base, lease, ação ativa, cooldown restante, motivo/resultado e limites. A capacidade exigida abrange manual PAN, watchdog, bomba protegida, cancelamento sem troca de modo e idempotência. Ausência de qualquer capacidade mantém gamepad desabilitado, sem fallback para letras perigosamente semelhantes. Detecção legada pode continuar com aviso explícito.

Propor endpoints novos `POST /api/v1/session` e `POST /api/v1/command`, com JSON e validação estrita. A sessão negociada identifica uma instância do cliente; o lease manual é renovado apenas por estado HID fresco. Comandos incluem versão, boot ID, sessão/geração, sequência monotônica e `command_id`; ações são nomeadas, não caracteres ambíguos. Rejeitar números inválidos, IDs antigos, sessão obsoleta e ação desconhecida sem efeito lateral ou renovação de lease.

O S3 emitirá janela/token de frescor vinculado a boot/sessão/`control_epoch`, escopo de ação e expiração em seu próprio relógio monotônico; proposta inicial: validade de 500 ms, renovada pelo cliente a cada 250 ms. Janelas de cancelamento são limitadas por tempo e alvo/barreira, inclusive na RECUPERACAO; não autorizam atuação no epoch posterior. Toda ação ou renovação de lease deverá trazer uma janela ainda válida no RECEBIMENTO. O cliente não pode ampliar esse prazo nem depender de relógios sincronizados. Consultar/mintar janela não renova o lease por si só. Isso rejeita também o primeiro pacote de uma sessão que tenha ficado atrasado na rede, mesmo sem sequência posterior já recebida. O contrato distinguirá sessão da aplicação, lease manual e janela curta de entrega; automaticidade não exige HID saudável, mas exige publicação local válida no camera_epoch corrente e janela de entrega válida.

Acordar esquema e respostas no primeiro teste de contrato: aceito/recusado/duplicado, motivo, ação e estado resultantes. `command_id` duplicado com payload divergente é erro. Retenção dedup será maior que qualquer janela de reconciliação; não haverá retry automático de disparos/cancelamentos com novo ID. Um ID cujo resultado não possa mais ser reconciliado permanece desconhecido, sem replay.

A abertura de sessão também é idempotente: o cliente cria `session_open_id` antes de enviar; repetir esse ID e payload retorna a mesma decisão/sessão sem fazer outro takeover. Resposta perdida não autoriza gerar um novo ID para compensar. Uma resposta histórica não reativa sessão já substituída; o cliente reconcilia o boot/estado atual. Solicitação de abertura antiga/expirada nunca troca a sessão corrente.

Lifecycle decidido: (a) sem ação em curso, uma abertura nova válida invalida a sessão anterior, põe modo-base AUTO e não restaura manual nem intenções; (b) com ação protegida em curso, inclusive fases pendentes, a nova sessão entra em RECUPERACAO. O S3 devolve o `action_id` ativo e uma capacidade de cancelamento restrita EXCLUSIVAMENTE a essa ação, revoga os comandos da sessão antiga e marca retorno AUTO. Em RECUPERACAO são permitidos status/reconciliação e cancelamento dessa ação, nunca movimento, troca manual ou novo disparo; não há transferência de autorização para repetir água. A identidade e o prazo original da ação não mudam. O cliente reiniciado consegue assim cancelar a ação S1 por Círculo em S2, inclusive após ACK de disparo/handshake perdido. Se a ação terminar antes do cancelamento chegar, a capacidade não alcança nenhuma ação futura. Após idle confirmado, a sessão permanece AUTO, sem entrada armada; novo fluxo neutro e Cruz serão necessários para manual. (c) com água LEGADA ativa, a aquisição protegida é recusada até o término, sem transferência implícita.

Boot novo invalida todas as sessões, janelas e capacidades anteriores. Uma abertura durante RECUPERACAO repete a mesma regra sem alterar o prazo da ação; dados de sessão velha não se tornam válidos em sessão nova. Sequência/barreira deve abranger cancelamento e intenções de água, não só movimentos. Negociar a primeira sessão protegida fixa o perfil PROTEGIDO durante todo o boot: `/cmd` e serial não aceitam comandos legados que movem, acionam/cancelam água ou trocam modo nesse perfil, inclusive `F`, `B`, `X` e `V`. A IA e o teclado do novo cliente usam as ações tipadas, não letras. Expirar lease/perder USB não remove esse bloqueio; logo pacotes legados atrasados não rearmam água após Círculo. Status/ajuda continuam disponíveis. Iniciar sessão com ação legada de água ainda ativa é recusado até seu término.

Antes de qualquer sessão protegida, o perfil COMPAT permite os comandos legados documentados, sempre sujeitos ao guardião local de bomba. Nesse perfil, não há promessa de deduplicação/barreira para letras sem identidade. Voltar a COMPAT após negociação exige procedimento explícito de manutenção/reboot; não é fallback de erro. A variante original permanece a referência para reprodução exata do legado. Não há suporte a múltiplos operadores concorrentes nesta versão.

Um único despachante controla HTTP no caminho novo. Uma posição/velocidade pendente, sempre a mais recente; fila discreta limitada; cancelamento prioritário e limpeza de disparos/movimentos obsoletos. Nenhum disparo reprimido pode ser guardado para execução futura. Eventos de disparo usam entrega imediata limitada: se não forem despacháveis dentro da validade, são descartados com motivo.

No máximo uma requisição em voo. Cancelamento não preempta uma chamada já iniciada: timeout curto limita a espera no cliente, mas não garante prazo físico na rede. Timeout significa resultado DESCONHECIDO; aceitação HTTP não significa fluxo físico de água. Lease/watchdog são a garantia local de fallback, não uma mensagem final enviada por um cliente falhando.

Valores iniciais propostos, parametrizados e sujeitos à aprovação/calibração:

| Parâmetro | Valor inicial | Justificativa |
|---|---:|---|
| Zona morta | 10% da meia-faixa | Cobre centro observado 128–130; não representa calibração definitiva |
| Velocidade PAN máxima | 30 graus/s | Ponto conservador de software, ainda sem ensaio mecânico |
| Atualizações de movimento | Até 20 Hz | Não repassar os cerca de 250 relatórios/s como HTTP |
| Renovação de saúde | 250 ms | Mantém neutro manual sem depender do YOLO |
| HID considerado fresco | Até 500 ms | Relatórios atrasados não sustentam lease |
| Lease manual no S3 | 1500 ms | Fallback local após perdas consecutivas |
| Timeout HTTP | 200 ms | Orçamento inicial; validar sob Wi-Fi real |
| Entrada neutra para armar | 300 ms | Evita ação por botão/analógico já pressionado |
| Prazo nominal de água | 5000 ms | Comando GPIO, não prazo físico absoluto |
| Orçamento de jitter da proteção | J <= 10 ms | Meta a provar em bancada; cenário simulado deve cobrir I/O lento |
| Lacuna de aquisição HID | 100 ms | Invalida epoch e exige drenagem/rearme |
| Pausa de leitura serial | 500 ms | Invalida publicação e exige resincronização |
| Idade local da publicação | 1000 ms | Não mede idade real de captura |
| Cooldown | 12000 ms | Entre inícios; após cancelar/boot, inibição completa |

Os parâmetros serão consistentes no contrato/handshake; o cliente não presumirá que `--cooldown` ou `--tempo-bomba` alteram o firmware. Firmware autoritativo publica seus limites; cliente usa política pelo menos tão restritiva quanto a publicada.

### 6. Movimento e temporização não bloqueantes

Substituir rampas `while + delay` apenas na nova variante por atualização incremental com tempo monotônico e limites existentes. Separar alvo, ângulo comandado e velocidade. Cada velocidade também terá validade local máxima de 500 ms: sem novo estado de movimento válido, a velocidade passa a zero, ainda que o lease manual permaneça saudável. Heartbeat isolado não prolonga velocidade antiga. Ao recuperar o loop após pausa, não integrar retroativamente movimento além da validade da amostra; avaliar expiração antes da trajetória. Não executar callbacks de HTTP, I2C ou logging dentro de uma espera de movimento. Orçar e testar passos do loop, mantendo limite da bomba e recepção de cancelamento.

Políticas do firmware devem ser extraídas em núcleo C++ pequeno testável com relógio/saídas falsos; adaptadores de servo, relé, LCD e Wi-Fi ficam na borda. Testes de um simulador Python não substituem testes do núcleo real nem compilação Arduino.

Ao terminar água, reanexar servo na posição congelada; somente comandos NOVOS após sair do combate podem mover. A varredura pode retomar de uma posição manual fora da faixa de varredura sem salto: retornar à faixa por rampa limitada.

### 7. Evidência automática fresca e regressões

O caminho atual pode reprocessar o mesmo último quadro indefinidamente. O protocolo serial fornece apenas marcador, comprimento e JPEG, sem hora/ID do sensor. A integração nova adicionará `frame_id_local`, `published_at_monotonic` e `camera_epoch`, preservando a API legada. Esses campos representam publicação/decodificação local, NÃO instante nem idade real de captura. O limite inicial de 1000 ms se refere somente à idade desde publicação local. Não haverá alegação de frescor end-to-end sem alterar protocolo e obter autorização separada.

Partida/reconexão, pausa de leitura superior a 500 ms configuráveis, erro, backlog fora do orçamento ou barreira de cancelamento invalidam a publicação anterior e o contador de confirmação. O thread de câmera limpa seu parser, descarta bytes pendentes da COM por API de descarte de entrada, resincroniza o marcador e descarta o primeiro JPEG completo após a fronteira. Não publicar vários JPEGs acumulados como novos: em cada lote recebido, descartar os intermediários e considerar somente o mais recente após as regras de resincronização. Nenhum JPEG dos buffers locais/COM descartados por essa descontinuidade/barreira pode contar para a nova confirmação. Bytes ainda em trânsito no sensor/transmissor não têm idade aferível no protocolo; esse limite continua coberto somente pela premissa operacional e pelo gate físico abaixo. Só depois dessa fronteira o novo `camera_epoch` permite contar três IDs locais distintos; inferência da geração anterior não pode regressar pela fila de resultados.

Premissa operacional explícita: stream contínuo, host capaz de acompanhar os bytes sem backlog persistente e atraso sensor→publicação limitado pela configuração escolhida. O orçamento desejado inicial para esse atraso é 1000 ms, mas NÃO é inferível pelo protocolo e NÃO foi medido; validá-lo em bancada com referência visual/temporal é pré-requisito de aceite da atuação automática física. Sem timestamp remoto não se detecta todo atraso oculto: o software detecta pausas/acúmulos locais observáveis, não prova a idade da cena. Se a premissa não puder ser sustentada, bloquear o aceite automático físico e propor mudança de protocolo separadamente. A conclusão de software deve declarar essa pendência, não classificá-la como teste passado.

O debounce opt-in conta três publicações locais distintas, posteriores à fronteira/geração corrente e com idade local válida. Ausência de publicação válida impede novos disparos automáticos, mas não leitura do controle ou cancelamento. Não retreinar modelo nem mudar limiar/classe. Caracterizar separadamente o caminho legado desabilitado. A falha preexistente de registro offline com atuador ausente não será usada como harness nem corrigida implicitamente nesta mudança; abrir correção separada se necessária.

### 8. Registro sem falsas detecções e sem migração

Registrar comandos/decisões em JSONL separado, proposto `dados/comandos_controle.jsonl`, com origem, IDs, horário, resultado, motivo e estado reportado. Não registrar identificador serial pessoal do controle. Não inserir disparo manual em `deteccoes`: o [esquema atual](<C:/Users/orugi/Documents/Projetos/KGB-sompo/banco.py#L23-L42>) exige confiança, e inventar 0 ou 1 corromperia estatísticas.

Estados de registro distinguem solicitado, aceito pelo firmware, recusado, desconhecido e cancelado/concluído segundo firmware. Nenhum deles prova fluxo físico. Incêndios detectados continuam usando imagem e a mesma tabela/contrato do painel, mas no caminho novo o campo textual `acao` deverá refletir a decisão real: comando aceito, recusado com motivo ou resultado desconhecido. Não chamar o helper legado com sua ação fixa `bomba acionada` quando houver recusa/incerteza. O registro ocorrerá fora do loop de inferência após decisão/timeout, com a confiança da detecção real e sem afirmar duração física; `duracao_bomba` será ausente quando não houver duração lógica confiável. A evidência de fogo continua existindo mesmo se a bomba recusar. O caminho legado desabilitado não é corrigido silenciosamente. Um histórico unificado em tabela adicional é alternativa futura, não pré-requisito desta entrega.

## Risks / Trade-offs

- [Sem equipamentos do atuador] → separar testes de software, compilação e aceite de bancada; não declarar operação física validada.
- [PAN detached pode perder posição real] → manter workaround existente e ângulo lógico congelado; torque/alinhamento exigem bancada.
- [Cancelar via rede não é emergência física] → documentar latência não garantida e necessidade de corte elétrico apropriado.
- [IA pode disparar novamente após cancelar] → inibição explícita, nova confirmação fresca e aviso de que Círculo não é trava permanente.
- [Clientes legados contornarem segurança] → guardião único em todos os caminhos da variante nova; exceções legadas de modo declaradas.
- [Pacotes atrasados/ack perdido] → boot/sessão/sequência/IDs, barreira de cancelamento, ausência de retries cegos e reconciliação.
- [Rede HTTP sem autenticação herdada] → somente rede local confiável, sem exposição à internet; sessões não constituem autenticação. Implantação em rede hostil exige trabalho de segurança separado.
- [Firmware de câmera documentado incorretamente] → não regravar câmera nesta mudança; documentar divergência e confirmar imagem instalada antes de qualquer manutenção física.
- [Nova variante duplica referência] → manter origem/versionamento explícitos e comparar regressões; refatoração compartilhada fica para depois de validar a entrega.
- [Sem gravações locais para regressão visual] → obter amostras da equipe; testes sintéticos não comprovam acurácia de campo.

## Migration Plan

1. Aprovar este plano; preservar estado/diff inicial sem resetar ou sobrescrever alterações do usuário.
2. Versionar fixtures mínimas e implementar testes puros antes dos adaptadores.
3. Construir/testar núcleo C++ da nova variante e contratos com atuador simulado.
4. Integrar controle opt-in, mantendo o fluxo original desabilitado sem dependência HID.
5. Compilar variante com versões registradas de core ESP32/bibliotecas; não fazer upload nesta máquina sem autorização e equipamento.
6. Entregar matriz de testes executados versus pendentes e guia de instalação/flash para a equipe com hardware.
7. Primeiro ensaio físico com bomba eletricamente desconectada; depois validar relé e água em bancada controlada, alimentação apropriada e possibilidade de corte físico.
8. Rollback: desabilitar opção do controle; se a placa recebeu a variante, regravar o sketch original/configuração conhecida pela equipe. Não executar rollback por reset destrutivo de Git nem apagar dados.

## Open Questions

- Valores iniciais acima são propostas de engenharia; velocidade, limites físicos, zona morta e temporizações de rede exigem aceite e bancada.
- Confirmar quais versões de Arduino core/bibliotecas e qual toolchain host estarão disponíveis antes de implementar. Não foram instalados compiladores nesta sessão.
- Obter vídeos representativos para regressão visual e confirmar o firmware de câmera realmente gravado com a equipe.
- Círculo é cancelamento temporário com cooldown; uma trava persistente/emergência não faz parte deste mapeamento e demandaria requisito próprio.
