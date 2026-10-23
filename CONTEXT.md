# Vigia agrícola — linguagem do projeto

Glossário do monitoramento de incêndio e do controle do conjunto câmera/bico. Define significados; regras de implementação pertencem às especificações da mudança.

## Language

**Conjunto câmera/bico**:
Câmera e saída de água solidárias ao mesmo suporte horizontal; apontam juntas, sem que isso comprove alinhamento exato entre imagem e jato.

**Modo-base**:
Forma de direcionamento do conjunto: automático por varredura ou manual pelo operador. Detecção automática de incêndio permanece habilitada em ambos.

**Combate**:
Intervalo de uma ação de água comandada, sobreposto ao modo-base. A mira lógica fica congelada, mas não existe confirmação de posição física ou de fluxo de água.

**Cancelamento de água**:
Interrupção temporária de uma ação de água, sem selecionar outro modo-base por si só. Não é trava permanente contra novas detecções nem parada elétrica de emergência.
_Avoid_: parada de emergência, desativação da IA.

**Quadro recém-publicado**:
Imagem que se tornou disponível recentemente no computador. Sua publicação não comprova quando o sensor capturou a cena.
_Avoid_: captura comprovadamente recente, imagem atual garantida.

**Captura recente**:
Imagem cuja idade desde a exposição no sensor é conhecida. É distinta de quadro recém-publicado e não é demonstrável apenas pela chegada da imagem ao computador.

**Aceitação lógica de água**:
Decisão do controlador de executar uma ação de água. Não equivale a evidência de água saindo do bico.
_Avoid_: fluxo confirmado, incêndio combatido com sucesso.

## Exemplo de linguagem

Desenvolvedor: “A água foi aceita no manual; houve combate confirmado?”
Especialista: “Houve aceitação lógica de água. O modo-base era manual, mas não temos confirmação de fluxo; um cancelamento interrompe essa ação sem desativar a detecção.”
