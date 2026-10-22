# Fine tuning do modelo de fogo, instruções para o Guilherme

Projeto KGB / Sompo, entrega da Sprint 4 em 15/09/2026.

---

## 1. O que tem no zip

Duas pastas, de **câmeras diferentes**. Deixei separadas de propósito.

### `amostras_640x480/` — 897 imagens

Captura de 19/08, em 640x480, lente grande angular.

O conteúdo não é só fogo, e isso é intencional. Tem três tipos:

- chama de isqueiro de perto e papel queimando
- fumaça
- **negativos difíceis**: luz forte de painel, tela de monitor, lanterna de celular e uma estampa de fogo desenhada em um pano

Os negativos são a parte mais valiosa do lote. São exatamente os casos que fazem o modelo confundir luz com chama. Não descarta achando que é captura ruim, rotula como imagem sem objeto mesmo.

### `espcam_320x240/` — 44 tomadas, 215 imagens

Capturas novas, feitas com **a câmera que vai rodar na demo**.

| | |
|---|---|
| Placa | ESP32-CAM (AI Thinker) |
| Sensor | GC2145, módulo de flat preto (RHYX M21-45) |
| Resolução | 320x240 (QVGA) |
| Taxa real | cerca de 2 quadros por segundo |

Uma pasta por tomada, cada uma com até 10 segundos de captura.

**Sobre a qualidade, para não parecer descuido**: o GC2145 não tem compressor JPEG por hardware. O sensor entrega RGB565 e o próprio ESP32 converte para JPEG por software. Daí vêm a taxa baixa de quadros e a imagem crua, com ruído e cor pouco saturada. O sensor certo seria o OV2640, que comprime sozinho, e a troca ficou para depois da entrega de propósito: trocar agora faria o modelo treinar com uma imagem diferente da que ele vai encontrar no dia 15.

---

## 2. O que não foi feito, nos dois conjuntos

- **Nenhum tratamento.** Sem redimensionar, sem ajustar brilho, contraste, saturação ou nitidez. Os bytes são os que saíram da câmera.
- **Nenhuma rotulagem automática.** Não rodei o `best_dfire.pt` em cima de nada disso. A rotulagem fica inteira com você e o Lucas, como combinado.

---

## 3. O ponto mais importante: partir do best_dfire.pt

O treino é **fine tuning em cima do `best_dfire.pt`**, não treino do zero.

O `best_dfire.pt` já viu o D-Fire inteiro e está com mAP50 de 0,771. O que falta nele é conhecer a cara da nossa câmera, que é ruim e específica. O objetivo aqui é adaptação de domínio, não aprender o que é fogo de novo.

### O risco, e ele é real

São 1112 imagens, mas quase todas do mesmo quarto, mesma luz e mesmo fundo. Em cenas realmente distintas isso vale umas 150 amostras.

Se o treino for agressivo em cima disso, acontecem duas coisas ruins ao mesmo tempo:

1. **Catastrophic forgetting**: o modelo esquece o que aprendeu no D-Fire
2. **Overfitting de cenário**: ele aprende "fogo no quarto do Vinicius" e falha na sala da FIAP, com outra luz e outro fundo

### Receita segura

```python
from ultralytics import YOLO

modelo = YOLO("modelos/best_dfire.pt")

modelo.train(
    data="dataset_kgb.yaml",
    epochs=30,
    patience=8,          # early stopping
    lr0=0.001,           # taxa baixa, é fine tuning e não treino novo
    freeze=10,           # congela as primeiras camadas
    imgsz=416,
    batch=16,
    hsv_h=0.015,         # augmentation de cor ajuda contra a luz diferente
    hsv_s=0.7,
    hsv_v=0.4,
    degrees=5,
    scale=0.5,
)
```

### Misturar D-Fire no treino

Junta de 20% a 30% de imagens do D-Fire original no mesmo lote de treino. É o que segura o modelo para ele não jogar fora o que já sabia por causa de mil imagens de um quarto só.

### Validação

O conjunto de validação **não pode ser do mesmo quarto**. Se validar com imagens da mesma cena, o número vai sair ótimo e mentir. Separa para validação imagens do D-Fire e, se der, qualquer captura feita em outro ambiente.

---

## 4. Comparar antes de decidir

Depois de treinar, roda a validação **nos dois modelos**, o novo e o `best_dfire.pt` antigo, no mesmo conjunto.

**Se o novo for pior, usamos o antigo na demo.** Guarda o `best_dfire.pt` original intocado, ele é o nosso plano B e não pode ser sobrescrito.

---

## 5. Detalhes da rotulagem

- Classes do projeto: `0 = Smoke`, `1 = Fire`. Mantém essa ordem, o código do sistema filtra pelo **nome** da classe e não pelo índice, mas o dataset precisa ficar consistente.
- Quadros vizinhos da mesma tomada são parecidos. Se quiser aliviar o trabalho, pega 1 a cada 2 ou 3 de cada pasta. Preferi mandar tudo e deixar essa escolha com você.
- As imagens sem fogo nenhum entram no dataset **sem caixa**, como negativo. Elas ensinam tanto quanto as positivas.

---

## 6. Está vindo mais material

O que trava mais gravação agora é um problema de alimentação da ESP32-CAM, que está derrubando ela no meio da captura. Assim que resolver, mando um segundo lote, e dessa vez gravado em ambientes diferentes: cozinha, corredor, área externa e com luz apagada. Variedade de cenário é o que mais falta nesse dataset, mais do que quantidade de quadros.
