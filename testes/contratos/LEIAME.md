# Vetores de contrato do protocolo protegido (tarefa 1.3)

`vetores_protocolo.json` materializa os contratos decididos no design R2 (§3–§5) como sequências de requisições com tempo simulado do S3 e respostas esperadas. O mesmo arquivo é consumido pelos dois lados:

- **C++ (núcleo real do firmware):** `testes/test_contratos_nucleo.py` compila `testes/nucleo_cpp/nucleo_cli.cpp` com os fontes do sketch `arduino/esp32s3_vigia_dualsense/` e executa cada cenário contra o binário. Não há reimplementação do núcleo em Python.
- **Python (cliente):** `testes/test_protocolo_cliente.py` valida que o esquema estrito do cliente aceita/recusa os mesmos corpos que o S3 e que o intérprete de respostas entende todas as formas esperadas.

## Formato

Cada cenário tem `nome`, `requisito` (referência à spec), `t0` opcional (relógio inicial do S3 em ms, para testar rollover de `uint32`) e `passos`. Cada passo:

| Campo | Significado |
|---|---|
| `t` | ms desde o boot simulado. Antes de atender a requisição, o simulador executa todos os ms até `t` (tick da proteção, depois passo da aplicação). Requisições no mesmo `t` não têm tick entre si. |
| `rota` | `status`, `sessao`, `comando`, `cmd` (letra via `/cmd`), `serial` (letra pela serial), `avancar` (só avança o tempo). |
| `sess` | variável da sessão; o executor preenche `v`, `boot_id` e `sessao` do corpo, e captura as janelas da resposta em `$<sess>_jc` / `$<sess>_jx`. |
| `corpo` | objeto plano enviado (valores `"$x"` são substituídos). |
| `corpo_bruto` | texto enviado sem serialização (corpos malformados). |
| `repetir_passo` | reenvia byte a byte o corpo do passo de índice indicado. |
| `macro` | `abrir` (status + abertura de sessão) ou `janela` (pedido de janelas). |
| `espera` | caminho pontilhado → valor esperado. Prefixo `d.` lê a telemetria de simulação (relé/servo), que não existe na resposta HTTP real. |
| `capturar` | variável → caminho pontilhado. |

Operadores em `espera`: `{"$nulo":true}`, `{"$naonulo":true}`, `{"$dif":"$x"}`, `{"$soma":["$x",15]}`, `{"$entre":[a,b]}`.

## Limites

Estes vetores testam decisões lógicas e o prazo lógico com relógio simulado. Não medem jitter no S3, tempo do relé, fluxo de água nem latência Wi-Fi.
