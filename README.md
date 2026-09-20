# Atlas — agente de configuração de servidores Discord

Bot que configura a **estrutura** de um servidor por linguagem natural. O modelo
planeja; o backend valida e executa. Nenhuma decisão de segurança vive no prompt.

A camada de IA fala com um endpoint **compatível com a API OpenAI**. O padrão é
público e **anônimo — não pede conta, cartão nem chave**. O bot não conhece
provedor nenhum: trocar de gateway é trocar três variáveis de ambiente.

```
Discord
  ↓
Discord events (on_message, canal de controle)
  ↓
Agent                      laco de raciocinio
  ↓
AI Service                 atlas.ai — unica saida para modelo
  ↓
Endpoint OpenAI-compativel  publico e anonimo, com failover entre modelos
  ↓
LLM

Tool Call
  ↓
Executor  →  Policy  →  Permissions  →  ActionQueue  →  RateLimiter
  ↓
DiscordGateway  →  Discord API
  ↓
verificacao pos-acao  →  resultado volta ao modelo  →  embed  →  usuario
```

---

## Como iniciar

```bash
cd atlas-bot
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pip install -e .

cp .env.example .env      # preencha
.venv/bin/python main.py --check
.venv/bin/python main.py
```

Outros modos:

```bash
.venv/bin/python -m pytest -q                   # 311 testes
.venv/bin/python main.py --demo                 # agente contra servidor simulado
```

O bot **sobe sem credencial de IA**. Com `AI_*` vazio ele conecta no Discord e
responde com um embed explicando que a camada de IA não está configurada, em vez
de falhar na inicialização.

---

## Configuração

Tudo via `.env`, que está no `.gitignore`. Nenhum valor é inventado, não há
default de provedor e não há chave de exemplo.

```env
DISCORD_TOKEN=
ATLAS_CONTROL_CHANNEL_ID=

AI_API_KEY=
AI_BASE_URL=
AI_MODEL=

ATLAS_AUDIT_PATH=logs/audit.jsonl
```

**Só `DISCORD_TOKEN` é obrigatório.** As três `AI_*` podem ficar vazias: o bot
cai no padrão anônimo embutido em `config.py`.

| Variável | Obrigatória | Padrão quando vazia |
|---|---|---|
| `DISCORD_TOKEN` | sim | — (exigência do Discord) |
| `AI_API_KEY` | não | nenhuma; o endpoint ignora o header de auth |
| `AI_BASE_URL` | não | `https://api.llm7.io/v1` |
| `AI_MODEL` | não | `codestral-latest,GLM-5.3-Flash,minimax-m2.7` |

`AI_MODEL` é uma **lista em ordem de preferência**. Endpoint gratuito devolve
429/503 com frequência, então o cliente tenta o próximo da lista antes de
desistir. Erros permanentes (401) não fazem failover — falham na hora.

Trocar de provedor **não exige mudança de código**: aponte `AI_BASE_URL` para
outro endpoint compatível, ajuste `AI_MODEL` e, se ele exigir, preencha
`AI_API_KEY`. As três variáveis vencem o padrão.

### Sobre o endpoint padrão

É público, gratuito e anônimo. Os três modelos da lista foram verificados como
acessíveis sem chave **e** com suporte a tool calling, que é obrigatório aqui.
Em contrapartida:

- a disponibilidade oscila — daí o failover e o backoff;
- não há SLA nem garantia de continuidade;
- suas mensagens passam por um servidor de terceiros que você não controla.
  Não mande nada sensível, e o bot já não tem acesso a dados de membros.

Para algo estável, preencha as três variáveis com um gateway pago. O código é o
mesmo.

---

## Rodar 24/7 no GitHub Actions

O sandbox de desenvolvimento morre no fim da sessão, então o bot precisa de um
lugar fixo. O GitHub Actions serve, mas **é gambiarra, não hospedagem**: o
runner mata qualquer job em 6 horas. O contorno está em
`scripts/run_bot.sh` + `.github/workflows/bot.yml`.

Como funciona o contorno:

- cada partida do bot nasce com um `timeout` de `MAX_RUN_SECONDS` (5h45), um
  pouco antes do teto de 6h;
- o cron `0 */5 * * *` dispara uma execução nova a cada 5 horas;
- `concurrency: {group: atlas-bot, cancel-in-progress: true}` derruba a execução
  antiga quando a nova começa, para nunca haver dois bots com o mesmo token
  disputando a mesma sessão do gateway;
- se o processo cair no meio do turno, o supervisor reinicia com backoff
  crescente (8s, 11s, 14s… até 60s);
- 5 quedas em menos de 30s seguidas encerram o job com erro, porque isso é
  configuração errada e não queda de rede — insistir só queimaria minutos;
- `logs/bot.log` e `logs/audit.jsonl` viram artefato ao final, retidos 7 dias.

### Configuração

1. Crie um repositório no GitHub e envie o código:

   ```bash
   cd atlas-bot
   git init -b main
   git add -A
   git commit -m "Atlas: agente de configuracao de servidores Discord"
   git remote add origin git@github.com:SEU-USUARIO/atlas-bot.git
   git push -u origin main
   ```

2. Em **Settings → Secrets and variables → Actions**, crie **um** segredo:

   | Segredo | Conteúdo |
   |---|---|
   | `DISCORD_TOKEN` | token do bot |

   É o único. A camada de IA é anônima e não precisa de chave. Se um dia você
   quiser um gateway pago, aí sim acrescente `AI_API_KEY` (secret) e
   `AI_BASE_URL` / `AI_MODEL` (variables).

   Opcional, em **Variables**: `ATLAS_CONTROL_CHANNEL_ID`. Sem ele o bot
   detecta o canal pelo nome `atlas-config` ou pelo tópico `[atlas-control]`.

   **O token não pode ir no repositório.** Ele dá controle total do bot; se for
   commitado em repo público, qualquer um assume o bot em minutos. Por isso ele
   é segredo, não arquivo.

3. Aba **Actions** → **Atlas no ar** → **Run workflow**. O `push` no `main`
   também dispara sozinho.

O job roda a suíte de testes antes de subir o bot. Se o token estiver faltando,
ele falha dizendo o nome do segredo — nunca o valor.

### Limites que você precisa saber

- **Repositório privado gasta minutos.** Um bot 24/7 precisa de ~43.200
  minutos/mês; o plano gratuito dá 2.000. Em repositório **público** os minutos
  são ilimitados, mas o código fica visível (os segredos continuam protegidos).
- **O cron atrasa.** Em horário de pico o GitHub escala execuções agendadas com
  minutos de atraso, então pode haver um intervalo sem bot entre um turno e
  outro.
- **`schedule` só roda no branch padrão.** Se o `main` não for o padrão, o
  restart automático não acontece.
- **Repositório parado desliga o agendamento.** Depois de 60 dias sem atividade
  o GitHub desativa workflows agendados; um `push` qualquer religa.
- **O token do Discord é inegociável.** Não existe forma de conectar um bot sem
  ele, e ele não pode ser commitado. É o único segredo que você precisa criar.

Para produção de verdade (sem janela de indisponibilidade), o mesmo código roda
em Fly.io, Railway ou qualquer VPS: `pip install -r requirements.txt` e
`scripts/run_bot.sh`, com as variáveis no ambiente.

---

## Estrutura

```
atlas-bot/
├── main.py                       entrada: --check | --demo | rodar
├── scripts/run_bot.sh            supervisor: restart com backoff + teto de 6h
├── .github/workflows/bot.yml     roda o bot no GitHub Actions
├── pyproject.toml  requirements.txt  .env.example  .gitignore
├── src/atlas/
│   ├── config.py                 Settings, Limits, leitura de .env
│   ├── ai/                       CAMADA DE IA (unica saida para modelo)
│   │   ├── base.py               ModelClient (Protocol), FunctionCall, ModelTurn
│   │   ├── openai_client.py      cliente OpenAI-compativel + traducao de erro
│   │   ├── schema.py             declaracoes -> envelope OpenAI de function calling
│   │   ├── fakes.py              doubles de teste (scripted / failing)
│   │   └── __init__.py           build_ai_client()
│   ├── agent.py                  laco modelo <-> ferramentas
│   ├── executor.py               validacao + dispatch + verificacao pos-acao
│   ├── policy.py                 SEGURANCA: whitelist, proibicoes, isolamento, cotas
│   ├── permissions.py            hierarquia de cargos + bits de permissao
│   ├── queue.py                  ActionQueue: unica porta para o Discord
│   ├── ratelimit.py              balde de tokens por servidor + contadores
│   ├── gateway.py                Protocol de saida Discord
│   ├── discord_gateway.py        implementacao real sobre discord.py
│   ├── tools/                    21 ferramentas
│   │   ├── base.py               Tool, ToolContext, ToolRegistry (lista fechada)
│   │   ├── read.py               get_server_info/channels/categories/channel/roles/role
│   │   ├── channels.py           canais, categorias, mover, reordenar, permissoes
│   │   ├── roles.py              criar/editar/apagar/mover cargo + permissoes
│   │   └── server.py             edit_server
│   ├── embeds.py                 templates de resposta + saida que recusa texto puro
│   ├── formatting.py             resultado -> templates
│   ├── session.py                memoria por (guild, canal) + confirmacao
│   ├── bot.py                    cliente discord.py + canal de controle
│   ├── prompts.py                prompt de sistema e hierarquia de autoridade
│   ├── audit.py                  auditoria JSONL + filtro de redacao de segredo
│   ├── models.py                 dominio: Guild, Channel, Role, Perm
│   ├── errors.py                 hierarquia de excecoes (AIError, PolicyViolation...)
│   ├── demo.py                   modo demo sem credencial
│   └── testing/fake_gateway.py   Discord em memoria com as mesmas restricoes
└── tests/                        8 arquivos de teste + conftest, 311 testes
```

---

## Camada de IA

`atlas.ai` é o único pacote que sabe que existe um modelo do outro lado. Todo o
resto importa o Protocol `ModelClient`:

```python
class ModelClient(Protocol):
    model_name: str
    def generate(*, system, history, tools) -> ModelTurn: ...
```

Responsabilidades da camada:

- **enviar mensagens** com system prompt e histórico;
- **function calling** — declaração das 21 ferramentas e parsing das chamadas;
- **histórico/conversa** com correlação de `tool_call_id` entre pedido e resposta;
- **erros** traduzidos por tipo: autenticação, rate limit, timeout, conexão,
  modelo inexistente, status HTTP;
- **timeout e retry** configuráveis em `Limits` (`ai_timeout_seconds`,
  `ai_max_retries`);
- **logs seguros** — nenhum prompt ou chave vai para o log;
- **troca de modelo sem tocar no bot** — `AI_MODEL` é lido em runtime.

O histórico interno é neutro (`{"role", "parts"}`) e convertido na fronteira.
Assim o agente e os testes não dependem do formato de nenhum provedor.

Chamadas de ferramenta recebem `id`. Quando o provedor não devolve id,
`ensure_call_ids` sintetiza um estável na fronteira — sem isso a conversa quebra
no segundo turno.

### Tool calling é obrigatório

O modelo **nunca** executa a API do Discord. Ele emite uma tool call; o
`Executor` valida, a `ActionQueue` limita, o `DiscordGateway` executa, o
resultado volta ao modelo.

---

## Segurança

Inalterada pela troca da camada de IA. Cada chamada passa, nesta ordem:

1. `Policy.check_tool` — whitelist de 21 nomes; 51 capacidades proibidas recusadas;
2. `Policy.strip_foreign_guild_keys` — remove `guild_id`, `server_id`, `target_guild`, `guild_ids`;
3. `Policy.bind_guild` — retorna sempre o guild da interação;
4. validação de parâmetros na própria ferramenta;
5. `Policy.check_budget` + `GuildRateLimiter`;
6. confirmação para operação destrutiva;
7. execução;
8. verificação pós-ação contra o Discord.

Duas camadas independentes recusam ferramenta proibida (`Policy` e
`ToolRegistry`), e os testes cobrem cada uma isoladamente.

**Proibido por construção** (não existe ferramenta): banir, expulsar, timeout,
cargo de membro, nickname, mover de voz, permissão individual de membro, DM,
mensagem em massa, spam, flood, `@everyone`, `@here`, listar/buscar membros,
chamada crua de API, executar código, trocar de servidor, comandos globais.

**Isolamento de servidor**: `guild_id` não é parâmetro de nenhuma ferramenta. Vem
do `ToolContext`, criado a partir do `discord.Guild` real da mensagem. Se o
modelo pedir outro servidor, o executor remove a chave, audita e executa no
servidor certo.

**Permissões nunca concedidas**: `administrator`, `ban_members`, `kick_members`,
`moderate_members`, `mention_everyone` — a bitmask final é limpa mesmo que
cheguem por outro caminho.

---

## Respostas

Toda saída passa por `EmbedOnlySender`, que levanta `PlainTextRejected` para
qualquer coisa que não seja `EmbedSpec`. O modelo fornece o conteúdo; a
estrutura visual vem de templates do bot.

Templates existentes: sucesso, erro, confirmação, informação, plano, resultado,
aviso, ajuda. Textos são cortados nos limites da API.

> **Nota**: a implementação atual usa **Embeds clássicos** do Discord, não
> Components V2. Ver "Pendências" abaixo.

---

## Testes

```
311 passed
```

| Arquivo | Cobre |
|---|---|
| `test_tools_basic.py` | casos 1–9 (canal, categoria, cargo, permissão, reordenação, servidor, exclusão) |
| `test_batch.py` | caso 10 (lote), confirmação destrutiva, memória de contexto |
| `test_security.py` | casos 11–15, 17 (proibidas, outro servidor, injection, spam, cota, hierarquia) |
| `test_errors.py` | casos 16, 19, 20 (permissão Discord, falha da IA, falha do Discord) + verificação |
| `test_embeds.py` | caso 18 (sempre template, nunca texto puro) |
| `test_audit.py` | auditoria e redação de segredo |
| `test_policy.py` | `Policy` e `ToolRegistry` isoladamente |
| `test_wiring.py` | canal de controle, gateway Discord, **camada de IA** |

### Teste de mutação

Desliguei cada defesa de propósito para confirmar que os testes exercitam o
caminho de verdade. Cada mutação foi aplicada e revertida com verificação por
hash, para não contar falso positivo de `str.replace` que não casou.

Segurança (rodada anterior, ainda válida):

| Mutilação | Resultado |
|---|---|
| `Policy.check_tool` → no-op | 53 falham |
| `require_role_hierarchy` → no-op | 3 falham |
| `strip_foreign_guild_keys` → passthrough | 4 falham |

Camada de IA (esta migração):

| Mutilação | Resultado |
|---|---|
| envelope `type=function` → `type=tool` | 2 falham |
| `parse_tool_arguments` sem `json.loads` | 3 falham |
| `tool_call_id` desacoplado da chamada | 1 falha |
| `ensure_call_ids` no-op | 1 falha |
| `allow_missing` ignorado | 2 falham |
| branch `RateLimitError` do `_translate` removido | 1 falha |
| `tools` deixam de ir no request | 1 falha |
| `tools` na chave legada errada | 1 falha |
| `generate` não envolve erro do SDK | 3 falham |
| descrição da ferramenta enviada vazia | 1 falha |

Há ainda um teste de guarda (`test_nenhum_provedor_esta_hardcoded_na_camada_de_ia`)
que varre `src/atlas/**/*.py` e falha se reaparecer referência a provedor antigo.

### Ponta a ponta por HTTP

Três testes sobem um gateway OpenAI-compatível mínimo em `127.0.0.1` e exercitam
o cliente de verdade: conferem caminho `/v1/chat/completions`, header
`Authorization: Bearer …`, modelo, as 21 tools no request, o parsing do
`tool_calls` da resposta e a conversão de HTTP 401 em `AIError`. Isso valida o
formato no fio, não só em memória.

---

## O que foi removido nesta migração

- `src/atlas/model.py` — **deletado** (continha o cliente e o conversor de schema
  do provedor anterior);
- dependência `google-genai` — removida de `requirements.txt` e `pyproject.toml`;
  substituída por `openai>=1.40`, usado apenas como cliente OpenAI-compatível;
- `GEMINI_API_KEY` e `ATLAS_MODEL` — removidos de `.env` e `.env.example`;
- `Settings.gemini_api_key` / `Settings.model` → `ai_api_key` / `ai_base_url` /
  `ai_model`;
- `ModelError` → `AIError` (neutro quanto a provedor);
- ação de auditoria `model.error` → `ai.error`;
- schemas das ferramentas: tipos maiúsculos (`"OBJECT"`, `"STRING"`) → JSON
  Schema padrão (`"object"`, `"string"`), portável entre provedores;
- docstrings e comentários que citavam o provedor anterior.

**Não há projeto JavaScript**: não existe `package.json`, frontend, nem backend
separado. É Python puro, então os itens de auditoria sobre JS não se aplicam.

---

## Limitações da API do Discord

**Verificadas na documentação oficial**: nome do servidor 2–100 caracteres; nome
do canal 1–100; tópico 0–1024.

**Comportamento respeitado pelo código**: cargo em posição igual ou maior que a
do bot é intocável; cargos `managed` também; apagar categoria **não** apaga os
filhos (ficam órfãos e isso é reportado); reordenação confiável exige edição em
lote; anúncio e fórum dependem da feature **Community**; `set_permissions` aceita
alvo cargo ou membro — este agente usa só cargo.

**Limites locais em `config.Limits`** (tetos conservadores, não números da doc):
50 canais/categoria, 250 cargos, 60 ações / 40 criações / 25 exclusões por
pedido, 25 turnos internos, 120 caracteres de descrição do servidor — esse
último **não está documentado**, por isso é configurável.

**Fora de propósito**: ícone e banner do servidor (a assinatura existe no
gateway, a ferramenta não expõe) e tudo que envolva membros.

---

## Pendências e riscos

**1. O endpoint padrão é gratuito e instável.** Foi testado de ponta a ponta e
funciona, mas devolve 429/503 com frequência. O failover entre três modelos e o
backoff cobrem a maior parte disso; ainda assim pode haver pedido que falhe. Se
isso incomodar, preencha as três variáveis com um gateway pago — o código não
muda.

**2. O token do Discord precisa ser segredo.** É o único. Não há como rodar o
bot sem ele e não é seguro commitá-lo.

**3. Components V2 não está implementado.** As respostas usam Embeds clássicos.
O `discord.py 2.7.1` instalado suporta V2 (`MessageFlags.components_v2`,
`discord.ui.LayoutView`, `TextDisplay`, `SectionComponent`), então a migração é
viável, mas é mudança separada e afetaria `embeds.py`, `bot.py` e os testes de
resposta.

**4. Modelo gratuito escreve pior que modelo pago.** O prompt pede para ler o
estado antes de criar e não duplicar nomes; modelos menores seguem isso de
forma irregular. A segurança não depende disso — tudo é validado em código —
mas a qualidade do plano sim.

**5. `discord_gateway.py` foi validado contra a API real** em rodada anterior
(leitura + criação de categoria/canal/cargo com verificação e limpeza). As
mudanças na camada de IA não tocaram nele.
