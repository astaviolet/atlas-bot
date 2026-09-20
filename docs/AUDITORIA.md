# FASE 0 — Auditoria do projeto

Data: 2026-09-20 · HEAD auditado: `86801c3` · 0 merges · 417 testes passando · ruff limpo

Toda afirmação abaixo veio de comando executado nesta auditoria. O que não foi
verificado está marcado como **não verificado**.

---

## 1. O que existe

**7.354 linhas** em `src/atlas/`, **3.864 linhas** de teste. 40 módulos.

| Camada da spec (seção 5) | Existe? | Onde |
|---|---|---|
| Interaction / event | ✅ | `bot.py` (`on_message`) |
| Context builder | ✅ | `tools/base.py` `ToolContext`, `bot.py` |
| Security / policy | ✅ | `policy.py` (318 l.), `permissions.py` (143 l.) |
| Agent | ✅ | `agent.py` (353 l.) |
| Planner | ⚠️ parcial | implícito no laço do modelo, sem plano estruturado |
| AI router | ✅ | `ai/router.py` (275 l.) |
| LLM / provider / gateway | ✅ | `ai/providers.py`, `ai/openai_client.py` |
| Tool call | ✅ | `tools/` (21 tools) |
| Tool validator | ✅ | `tools/base.py`, `executor.py` |
| Execution engine | ✅ | `executor.py` (226 l.), `queue.py` |
| Discord API | ✅ | `discord_gateway.py` (356 l.) |
| Verification engine | ✅ | `confirmar_mudanca()` em `tools/base.py` |
| Audit log | ✅ | `audit.py` (143 l.) |
| Components V2 | ✅ | `embeds.py` (281 l.) |

**Nota sobre discord.js (seção 6):** o projeto é Python + `discord.py`. A *camada
conceitual* que a seção 6 exige existe e está correta — a IA nunca toca a API do
Discord; tudo passa por `ToolContext → Executor → Gateway`. Reescrever em
JavaScript violaria a seção 1 ("não substituir tecnologias arbitrariamente") e a
seção 3 (não perder funcionalidade). **Recomendação: manter Python.**

---

## 2. O que está quebrado ou inseguro

### 2.1 Confirmação não expira — **grave** (spec 18, 19, 177)

`PendingConfirmation` tem só três campos:

```python
class PendingConfirmation:
    token: str
    calls: list[dict[str, Any]]
    summary: str
```

`session.py` **não tem nenhuma noção de tempo** — `grep` por `time.`/`monotonic`/
`created_at` no arquivo返回零 resultado. Um "sim" digitado horas depois executa o
plano antigo.

O que **já está certo**: o token amarra a operação (`executor._plan_token()` =
sha256 do payload, 16 chars). Então um "sim" não executa *outra* operação — só a
pendente. O risco é narrower do que a spec teme, mas é real.

### 2.2 Duplicatas não são bloqueadas (spec 13, 178)

`create_channel`/`create_category`/`create_role` não checam se o nome já existe.
**Medido nesta auditoria**: um pedido de design com IA real criou `regras` e
`anuncios` duas vezes, porque o servidor já os tinha.

### 2.3 Sem lock por guild (spec 64, 65, 114)

Os únicos locks do projeto são `threading.Lock` em `ai/cache.py`, `ai/router.py`
e `ai/stats.py` — protegem estruturas de dados internas, **não** operações
estruturais concorrentes. Dois pedidos de reorganização no mesmo servidor podem
se pisar.

### 2.4 Doutrina de design é só prompt — **medido que não segura**

`design.py` injeta 647 tokens de doutrina quando o pedido é de projetar servidor
(detector determinístico, testado). Verificado que chega ao prompt:

```
detector  : True
prompt    : 7195 chars (~1798 tokens), contém "PROJETO DE SERVIDOR"
```

Mas o resultado real com IA do pool, pedido *"crie um servidor tematico de
xadrez, comunidade pequena"*:

```
categorias : ['geral-cat', 'INFORMACOES', 'COMUNIDADE', 'VOZ']
canais     : regras, anuncios, regras, anuncios, Sala Geral, AFK
tempo      : 25.1s
```

Ou seja: **exatamente o template genérico que a doutrina proíbe**, zero temática
de xadrez, zero cargos novos, e duplicatas. O prompt foi obedecido em nada.

Causa provável: os modelos gratuitos do pool são pequenos (`ling-3.0-flash`,
`nemotron`, `nex-n2.5-mini`) e recebem 2.273 tokens de schema de tools + 1.798
de prompt. Instrução longa e subjetiva não segura.

**Conclusão da auditoria:** qualidade de design não é garantível por prompt com
este pool. O que é garantível em código são defeitos objetivos — duplicata,
nome inválido, hierarquia quebrada, canal órfão. É para aí que a Fase de design
deve apontar, não para mais texto no prompt.

---

## 3. O que não existe

Verificado por `grep` em `src/`:

| Requisito da spec | Seções | Estado |
|---|---|---|
| Dry run / simulação | 12 | ❌ ausente |
| Backup lógico | 86 | ❌ ausente |
| Rollback | 87 | ❌ ausente |
| Task system com estados | 89 | ❌ ausente |
| Auto-correção pós-verificação | 25 | ❌ ausente |
| Progresso parcial ao usuário | 156 | ❌ ausente |
| Botões interativos | 73 | ❌ ausente (Components V2 é só layout) |
| Pesquisa na web | 28–33, 75 | ❌ ausente, e **deliberadamente** |
| Catálogo de padrões aprendidos | 32, 33, 140 | ❌ ausente |
| Versionamento de configuração | 88 | ❌ ausente |
| Cancelamento de tarefa | 90, 158 | ❌ ausente |
| Backpressure | 149 | ❌ ausente |
| Fairness por guild/usuário | 150 | ⚠️ só rate limiter, sem cota |

**Sobre pesquisa na web:** o bot tem 21 tools fixas, todas de operação no
Discord. Não há tool de busca, e o próprio documento proíbe scraping abusivo e
manda não atrasar `"crie um canal"` por causa de pesquisa global (seção 116).
Se pesquisa ao vivo for desejada, é **tool nova + decisão explícita**, com
custo de latência aceito — não algo para enfiar de contrabando.

---

## 4. O que está bom e não deve ser tocado

Verificado, não inferido:

- **Segurança de segredos (94):** nenhum `ghp_`/`AIza` em `src/`, `main.py`,
  `scripts/`. `.env` fora do git (`git ls-files` = 0), coberto pelo `.gitignore`.
  Nenhum token em `.git/config`.
- **Código morto (123, 166):** zero referência a Gemini/OmniRoute em produção.
  A única ocorrência é um teste que **impede** o Gemini de voltar.
- **Isolamento por guild (8):** presente em 23 arquivos; `guild_id` vem do
  contexto real da interação, nunca do modelo.
- **Prompt injection (50):** 9 padrões em `policy.py`; texto externo é dado, não
  autoridade.
- **Pool de IA (52–62):** 2 gateways anônimos, 12 rotas com tool calling,
  circuit breaker, capability routing, health states, fallback medido.
- **429 tratado corretamente:** corrigido em `86801c3` — pedido que levava 35,4s
  caiu para ~9s (log real do Actions como evidência).
- **Auto-diagnóstico (120):** `main.py --check`, `--pool`, `--health`, `--demo`.
- **Testes (97–102):** 417 passando, incluindo os 20 obrigatórios.

---

## 5. Riscos abertos

1. **Sem deadline de execução por tool** — o agente tem prazo total de 90s
   (`Limits.deadline_seconds`), mas uma tool individual presa na API do Discord
   só para no timeout do HTTP.
2. **`MAX_DESCRICAO = 220`** corta informação útil em respostas legítimas de
   listagem. Constante em `texto.py`.
3. **`set_role_permissions`/`edit_role` podem mirar `@everyone`** — renomear o
   cargo padrão não é bloqueado explicitamente.
4. **`METHOD` 3** (resolver referência dêitica como "o outro canal") é só
   prompt; não há garantia em código.
5. **Log do runner do Actions só aparece quando o job termina** — diagnosticar o
   bot em produção exige cancelar a run.

---

## 6. Documentação

Só existe `README.md`. A spec pede documentação de arquitetura, tools,
providers, env, execução, segurança, jobs, design, testes (seções 96, 181).
Este arquivo e o `ROADMAP.md` são o começo.
