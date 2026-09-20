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

## FASE 2 — Integridade de confirmação  ·  risco: alto  ·  esforço: pequeno

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

## FASE 3 — Idempotência  ·  risco: médio  ·  esforço: pequeno

Fecha o achado 2.2 (spec 13, 178).

- `create_channel`, `create_category`, `create_role` consultam o snapshot antes
  de criar. Nome igual + tipo igual + mesmo pai → não cria, devolve o existente.
- A decisão é **em código**, não no prompt. O modelo já provou que ignora.
- Resposta ao usuário distingue "criei" de "já existia".

**Teste obrigatório:** pedir duas vezes a mesma categoria → uma só no servidor.

---

## FASE 4 — Concorrência por guild  ·  risco: médio  ·  esforço: médio

Fecha o achado 2.3 (spec 64, 65, 114).

- Lock por `guild_id` no `Agent`, cobrindo operações estruturais.
- Segundo pedido estrutural no mesmo servidor enquanto um roda: informar, não
  misturar planos.
- Pedidos de leitura não bloqueiam.

**Teste obrigatório:** dois `handle()` concorrentes no mesmo guild com mutação →
sem estado corrompido, sem interleaving de plano.

---

## FASE 5 — Qualidade de design garantida em código  ·  risco: alto  ·  esforço: médio

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

## FASE 6 — Plano visível e dry run  ·  risco: baixo  ·  esforço: médio

Spec 11, 12, 133.

- `Executor` ganha modo de planejamento que devolve o plano sem executar.
- Saída resumida: cria N categorias, M canais, K cargos; altera X; remove Y.
- Confirmação obrigatória acima de limiar (já existe para deletes ≥ 3; estender
  para reconstrução).

**Critério de pronto:** pedido grande mostra o plano e espera; pedido pequeno
executa direto, sem mudar o comportamento atual.

---

## FASE 7 — Estados de tarefa e progresso  ·  risco: baixo  ·  esforço: médio

Spec 89, 156, 22, 23.

- Estados: `QUEUED → PLANNING → EXECUTING → VERIFYING → COMPLETED/PARTIAL/FAILED`.
- Falha na operação 7 de 10 reporta 1–6 feitas, 7 falhou, 8–10 não executadas.
  Nunca sucesso total falso.
- Progresso em Components V2 para operações longas.

---

## FASE 8 — Snapshot e rollback  ·  risco: médio  ·  esforço: grande

Spec 86, 87, 88.

- Snapshot lógico antes de mudança grande: categorias, canais, cargos,
  permissões. Nunca segredo.
- Rollback validado, passando pelas mesmas barreiras de política.
- Versionamento: versão, timestamp, autor, guild, resumo.

**Ordem importa:** só depois das Fases 2–4, senão o rollback corre sobre estado
concorrente.

---

## FASE 9 — Observabilidade  ·  risco: baixo  ·  esforço: médio

Spec 68, 121, 122.

- Painel interno já existe em `ai/stats.py` e `ai/health.py`; falta agregar
  Discord, fila, tools e tempo por fase.
- Expor via `main.py`, não via Discord (evita ruído no canal).

---

## FASE 10 — Documentação e endurecimento  ·  risco: baixo  ·  esforço: médio

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

## Próximo passo

Fase 2. Pequena, objetiva, testável, e fecha um risco de segurança real.
