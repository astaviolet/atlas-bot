# FASE 1 — Roadmap real

Derivado da `AUDITORIA.md`, não da lista de desejos. Ordenado por **risco
corrigível primeiro**: o que é objetivo e testável vem antes do que é subjetivo.

Regras que valem para todas as fases (spec 2, 3, 160, 165):

- Uma fase por vez. Quebrou uma fase anterior → parar, corrigir, testar, só
  então continuar.
- Nada é "pronto" sem: implementado + testado + validado + documentado.
- Sem merge, sem squash, sem rebase destrutivo.
- Substituir = implementar novo → testar → migrar → verificar → remover antigo.

---

## FASE 2 — Integridade de confirmação  ·  ✅ **FEITA** — `6f153c1`  ·  risco: alto  ·  esforço: pequeno

Fecha o achado 2.1 da auditoria (spec 18, 19, 177).

- `PendingConfirmation` ganha `created_at: float` e `ttl_seconds`.
- `Session` ganha acesso a um relógio injetável (já existe `FakeClock` nos
  testes — usar, não inventar outro).
- Confirmação vencida é descartada com mensagem própria, nunca executada.
- Revalidar no momento do "sim": o plano ainda corresponde ao estado atual?

**Teste obrigatório:** criar confirmação → avançar o relógio além do TTL →
responder "sim" → deve falhar com segurança. (spec 177)

**Critério de pronto:** teste acima passando + nenhum teste antigo quebrado.

---

## FASE 3 — Idempotência  ·  ✅ **FEITA** — `95b93bf`  ·  risco: médio  ·  esforço: pequeno

Fecha o achado 2.2 (spec 13, 178).

- `create_channel`, `create_category`, `create_role` consultam o snapshot antes
  de criar. Nome igual + tipo igual + mesmo pai → não cria, devolve o existente.
- A decisão é **em código**, não no prompt. O modelo já provou que ignora.
- Resposta ao usuário distingue "criei" de "já existia".

**Teste obrigatório:** pedir duas vezes a mesma categoria → uma só no servidor.

---

## FASE 4 — Concorrência por guild  ·  ✅ **FEITA**  ·  risco: médio  ·  esforço: médio

Fecha o achado 2.3 (spec 64, 65, 114).

- Lock por `guild_id` no `Agent`, cobrindo operações estruturais.
- Segundo pedido estrutural no mesmo servidor enquanto um roda: informar, não
  misturar planos.
- Pedidos de leitura não bloqueiam.

**Teste obrigatório:** dois `handle()` concorrentes no mesmo guild com mutação →
sem estado corrompido, sem interleaving de plano.

---

### Achado da Fase 4 que mudou a implementação

`bot.py` roda cada pedido assim:

```python
loop.run_in_executor(None, lambda: asyncio.run(agent.handle(text, session)))
```

Cada mensagem vai para uma **thread** com um **event loop novo**, e
`_build_agent` constrói um Agent novo por mensagem. Um `asyncio.Lock` não
travaria nada (loops diferentes não se enxergam) e uma trava no Agent nasceria
destrancada a cada pedido. A trava é `threading.Lock` por `guild_id`, em
`concurrency.py`, fora do Agent.

## FASE 5 — Qualidade de design garantida em código  ·  ✅ **FEITA** — `cc3a5b0`  ·  risco: alto  ·  esforço: médio

Responde ao achado 2.4. **A lição da auditoria é que prompt não segura**; então
esta fase é validador, não texto.

Validador de plano, rodando antes de executar:

- duplicata de nome na mesma categoria → rejeita;
- canal sem categoria quando o plano tem categorias → avisa;
- categoria vazia no plano → rejeita;
- cargo estético com permissão administrativa → rejeita (spec 40);
- hierarquia de cargos inconsistente → rejeita;
- contagem acima do razoável para o tamanho do servidor → exige confirmação.

A doutrina em `design.py` continua, mas passa a ser **orientação**, com o
validador como rede de segurança.

**Teste obrigatório:** plano com duplicata / categoria vazia / cargo estético
com admin → rejeitado antes de tocar o Discord.

---

## FASE 6 — Plano visível e dry run  ·  ✅ **FEITA** — `46b867f`  ·  risco: baixo  ·  esforço: médio

Spec 11, 12, 133.

- `Executor` ganha modo de planejamento que devolve o plano sem executar.
- Saída resumida: cria N categorias, M canais, K cargos; altera X; remove Y.
- Confirmação obrigatória acima de limiar (já existe para deletes ≥ 3; estender
  para reconstrução).

**Critério de pronto:** pedido grande mostra o plano e espera; pedido pequeno
executa direto, sem mudar o comportamento atual.

---

## FASE 7 — Estados de tarefa e progresso  ·  ✅ **FEITA** — `3cadac1`  ·  risco: baixo  ·  esforço: médio

Spec 89, 156, 22, 23.

- Estados: `QUEUED → PLANNING → EXECUTING → VERIFYING → COMPLETED/PARTIAL/FAILED`.
- Falha na operação 7 de 10 reporta 1–6 feitas, 7 falhou, 8–10 não executadas.
  Nunca sucesso total falso.
- Progresso em Components V2 para operações longas.

---

## FASE 8 — Snapshot e rollback  ·  ✅ **FEITA** — `1991c78`  ·  risco: médio  ·  esforço: grande

Spec 86, 87, 88.

- Snapshot lógico antes de mudança grande: categorias, canais, cargos,
  permissões. Nunca segredo.
- Rollback validado, passando pelas mesmas barreiras de política.
- Versionamento: versão, timestamp, autor, guild, resumo.

**Ordem importa:** só depois das Fases 2–4, senão o rollback corre sobre estado
concorrente.

---

## FASE 9 — Observabilidade  ·  ✅ **FEITA** — `cea0bf3`  ·  risco: baixo  ·  esforço: médio

Spec 68, 121, 122.

- Painel interno já existe em `ai/stats.py` e `ai/health.py`; falta agregar
  Discord, fila, tools e tempo por fase.
- Expor via `main.py`, não via Discord (evita ruído no canal).

---

## FASE 10 — Documentação e endurecimento  ·  ✅ **FEITA**  ·  risco: baixo  ·  esforço: médio

Spec 96, 181, 159, 167.

- Documentar arquitetura, tools, providers, env, execução, segurança.
- Auditoria de segurança final: segredos, permissões, isolamento, injection,
  confirmação expirada, logs, dependências.

---

## Fora do escopo, com motivo

| Pedido | Por que não entra agora |
|---|---|
| Reescrever em discord.js | Viola spec 1 e 3. A camada conceitual já existe em Python. |
| Pesquisa na web ao vivo | Exige tool nova (a lista de 21 é fechada por decisão sua) e adiciona latência — você acabou de reclamar de lentidão. Decisão explícita, não contrabando. |
| Colar a spec inteira no prompt | ~10 mil tokens × cada volta de IA. Contradiz sua regra permanente de mínimo de token e a auditoria mediu que o pool ignora instrução longa. |
| "Aprendizado contínuo" autônomo | Spec 76 exige validar antes de incorporar. Sem fonte confiável e sem curadoria, isso vira ruído. Fica para depois da Fase 9. |

---

## Achados que mudaram a implementação (lidos depois de cada fase)

Cada um destes foi pego por um teste ou por uma medição, não por revisão:

- **Fase 5.** A primeira versão do validador rejeitava o plano inteiro em 3
  casos. Dois estavam errados: "duplicata com o servidor" brigava com a Fase 3
  (que reusa e devolve `reused=True`) e "canal órfão" matava o sucesso parcial
  que a spec 22/23 exige. Sobrou um caso que vale parar o plano: cargo novo com
  permissão administrativa. O resto virou QA pós-execução.
- **Fase 6.** A decisão de "precisa confirmar" estava duplicada: o Executor
  decidia uma coisa e o agente recontava só as exclusões. Foi por isso que
  construção grande passava direto. A decisão agora vive em `PreparedPlan`.
- **Fase 8.** O save de snapshot foi posto primeiro no laço do agente. Mas com
  a Fase 6, plano grande **sempre** passa por confirmação, que executa por outro
  caminho — ou seja, o snapshot nunca seria salvo justamente para os planos que
  precisam dele. Foi para `Executor.execute`.
- **Fase 9.** `AuditLog.__init__` começa com `_records` vazio (`audit.py:74`) e
  cada run do Actions é um processo novo: sem ler o JSONL do disco, o painel
  mostraria sempre zero.

## O que continua de pé

- **Prompt não garante qualidade de design** (medido na Fase 5). A doutrina
  estava no prompt e o modelo devolveu o template genérico proibido. Enforcement
  é em código; o validador não decide estética.
- **Rollback não restaura id, histórico nem permissão.** `plano_de_rollback`
  só inverte criações; delete/edit ficam de fora em vez de virar rollback de
  mentira.
- **Snapshot não sobrevive à run do Actions.** Serve para desfazer a operação
  que acabou de acontecer, não para arqueologia.

## Próximo passo

Nenhum. As fases 2 a 10 estão fechadas. O que sobrou está em "Fora do escopo,
com motivo" — cada item com a razão de não ter entrado, não por esquecimento.
