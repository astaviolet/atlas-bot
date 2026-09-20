# Razão da MASTER SPECIFICATION

Gerado por `scripts/spec_ledger.py`. **Não editar à mão** — o script
confronta cada evidência com o repositório e falha se ela não existir.
Default é `ABERTA`: seção só sai de aberta com evidência verificada.

Seções na spec: **188**

| # | Seção | Estado | Evidência | Obs. |
|---|---|---|---|---|
| 0 | MISSÃO DO SISTEMA | ABERTA | `—` |  |
| 1 | REGRA ABSOLUTA: AUDITAR ANTES DE ALTERAR | ABERTA | `—` |  |
| 2 | EXECUÇÃO POR FASES | ABERTA | `—` |  |
| 3 | NÃO PERDER FUNCIONALIDADES EXISTENTES | ABERTA | `—` |  |
| 4 | PROIBIÇÃO DE MERGE | ABERTA | `—` |  |
| 5 | ARQUITETURA GERAL | ABERTA | `—` |  |
| 6 | DISCORD.JS É A CAMADA REAL DE EXECUÇÃO | ABERTA | `—` |  |
| 7 | CONTEXTO REAL DO DISCORD | PRONTA | `tests/test_security.py` | guild_id estranho é ignorado e não autoriza |
| 8 | ISOLAMENTO POR GUILD | PRONTA | `tests/test_security.py` | bind_guild recusa outro servidor; chaves de guild removidas em massa |
| 9 | MODELO MENTAL DO AGENTE | ABERTA | `—` |  |
| 10 | INTENÇÃO DO USUÁRIO | ABERTA | `—` |  |
| 11 | PLANNER | PARCIAL | `src/atlas/design.py` | proposta é gerada, mas plano != execução ainda depende do modelo seguir |
| 12 | DRY RUN | PRONTA | `46b867f` | dry run / simulação |
| 13 | IDEMPOTÊNCIA | PRONTA | `tests/test_tools_basic.py` | categoria pedida duas vezes não duplica |
| 14 | SISTEMA DE TOOLS | PRONTA | `tests/test_policy.py` | registry tem exatamente as ferramentas permitidas |
| 15 | SCHEMA VALIDATION | PRONTA | `tests/test_tools_basic.py` | configuração inválida é recusada |
| 16 | AUTORIZAÇÃO | PRONTA | `tests/test_policy.py` | policy recusa cada capacidade proibida |
| 17 | POLÍTICAS DO BOT | PRONTA | `tests/test_security.py` | ação proibida recusada; nenhuma ferramenta proibida registrada |
| 18 | CONFIRMAÇÃO | PRONTA | `tests/test_batch.py` | exclusão múltipla exige confirmação; ambígua não executa |
| 19 | EXPIRAÇÃO DE CONFIRMAÇÕES | PRONTA | `tests/test_batch.py` | confirmação vencida não executa |
| 20 | EXECUTION ENGINE | PRONTA | `tests/test_wiring.py` | executor centralizado testado de ponta a ponta |
| 21 | DEPENDÊNCIAS DE EXECUÇÃO | PRONTA | `tests/test_dependencias.py` | ordenação por dependência de execução |
| 22 | TRANSAÇÕES LÓGICAS | PRONTA | `tests/test_batch.py` | lote com falha parcial reporta o que falhou |
| 23 | PARTIAL SUCCESS | PRONTA | `tests/test_batch.py` | sucesso parcial reportado, não fingido |
| 24 | VERIFICAÇÃO PÓS-EXECUÇÃO | PRONTA | `tests/test_errors.py` | verificação detecta mudança que não aconteceu |
| 25 | AUTO-CORREÇÃO | PRONTA | `tests/test_autofix.py` | auto-correção antes de falhar |
| 26 | SISTEMA DE DESIGN DE SERVIDORES | PRONTA | `tests/test_design_system.py` | composição domínio x porte x público x estilo |
| 27 | DESIGN NÃO-GENÉRICO | PRONTA | `tests/test_design_system.py` | domínios diferentes dão estruturas diferentes |
| 28 | PESQUISA DE REFERÊNCIAS | FORA DE ESCOPO | `decisão` | pesquisa na web: 21 tools fixas, todas de operação no Discord |
| 29 | PESQUISA POR TEMA | FORA DE ESCOPO | `decisão` | pesquisa na web |
| 30 | PESQUISA POR ARQUITETURA | FORA DE ESCOPO | `decisão` | pesquisa na web |
| 31 | NÃO COPIAR SERVIDORES | FORA DE ESCOPO | `decisão` | pesquisa na web |
| 32 | CATÁLOGO DE PADRÕES | PARCIAL | `src/atlas/catalogo.py` | estrutura existe; a FONTE da spec é 'referências pesquisadas' e não houve pesquisa - padrões estão NÃO VERIFICADO |
| 33 | EVOLUÇÃO DO CATÁLOGO | PRONTA | `tests/test_catalogo.py` | armazena princípios, não templates; cresce por feedback |
| 34 | IDENTIDADE TEMÁTICA | ABERTA | `—` |  |
| 35 | DIREÇÃO VISUAL | PRONTA | `tests/test_design_system.py` | 13 estilos visuais |
| 36 | NOMENCLATURA | PRONTA | `tests/test_design_system.py` | nomenclatura uniforme, sem misturar |
| 37 | CATEGORIAS | PRONTA | `tests/test_design_system.py` | áreas conceituais com propósito |
| 38 | CANAIS | PRONTA | `tests/test_design_system.py` | todo canal tem propósito declarado |
| 39 | TIPOS DE CANAL | ABERTA | `—` |  |
| 40 | CARGOS | PRONTA | `tests/test_design_system.py` | funcional x identidade separados |
| 41 | HIERARQUIA DE CARGOS | PRONTA | `tests/test_design_system.py` | hierarquia cresce com o porte |
| 42 | PERMISSÕES | PRONTA | `tests/test_design_system.py` | nenhum funcional nasce com administrator |
| 43 | ONBOARDING | PRONTA | `tests/test_design_system.py` | jornada de onboarding por domínio |
| 44 | ESCALA | PRONTA | `tests/test_design_system.py` | porte corta a arquitetura |
| 45 | RECONSTRUÇÃO DE SERVIDORES | ABERTA | `—` |  |
| 46 | PRESERVAÇÃO | ABERTA | `—` |  |
| 47 | SERVER DESIGN QA | PRONTA | `tests/test_design_check.py` | QA interno: categoria vazia, canal duplicado, cargo com admin, canal órfão |
| 48 | MEMÓRIA | ABERTA | `—` |  |
| 49 | CONTEXTO | ABERTA | `—` |  |
| 50 | PROMPT INJECTION | PRONTA | `tests/test_security.py` | prompt injection bloqueado; unicode invisível detectado |
| 51 | AI ROUTER | ABERTA | `—` |  |
| 52 | MULTI-PROVIDER | ABERTA | `—` |  |
| 53 | DESCOBERTA DE PROVIDERS | ABERTA | `—` |  |
| 54 | NO-KEY / FREE-FIRST | ABERTA | `—` |  |
| 55 | NÃO BYPASSAR LIMITES | ABERTA | `—` |  |
| 56 | HEALTH CHECK | PRONTA | `tests/test_router.py` | falhas repetidas colocam a rota em cooldown |
| 57 | FALLBACK | PRONTA | `tests/test_router.py` | falha transitória vai para a próxima rota |
| 58 | CAPABILITY ROUTING | PRONTA | `tests/test_router.py` | pedido com tools exige rota com tool calling |
| 59 | REGRA "NÃO CONSIGO" | PRONTA | `tests/test_router.py` | só informa limitação depois de esgotar o pool |
| 60 | LOAD BALANCING | PRONTA | `tests/test_router.py` | carga se distribui em vez de empilhar na primeira rota |
| 61 | CIRCUIT BREAKER | PRONTA | `tests/test_router.py` | cooldown acaba e a rota volta em half-open |
| 62 | RETRIES | PRONTA | `tests/test_router.py` | cooldown cresce a cada queda seguida |
| 63 | FILAS | ABERTA | `—` |  |
| 64 | CONCORRÊNCIA | PRONTA | `tests/test_flow_control.py` | concorrência controlada |
| 65 | LOCK POR GUILD | PRONTA | `tests/test_flow_control.py` | trava por guild |
| 66 | RATE LIMIT DISCORD | PRONTA | `tests/test_security.py` | rate limit por servidor |
| 67 | CACHE | PRONTA | `tests/test_router.py` | cache expira e é invalidado por mutação |
| 68 | OBSERVABILIDADE | ABERTA | `—` |  |
| 69 | LOGS | PRONTA | `tests/test_audit.py` | segredo mascarado; parâmetros sensíveis não são auditados |
| 70 | AUDITORIA | PRONTA | `tests/test_audit.py` | registro de auditoria tem os campos exigidos |
| 71 | COMPONENTS V2 | ABERTA | `—` |  |
| 72 | UI CONTROLADA PELO CÓDIGO | ABERTA | `—` |  |
| 73 | BOTÕES | PRONTA | `tests/test_botoes.py` | as sete barreiras do clique |
| 74 | ERROS | PRONTA | `tests/test_errors.py` | erro de permissão e erro da API viram mensagem útil |
| 75 | PESQUISA CONTÍNUA | FORA DE ESCOPO | `decisão` | pesquisa na web |
| 76 | APRENDIZADO | ABERTA | `—` |  |
| 77 | LICENÇAS | ABERTA | `—` |  |
| 78 | SISTEMA DE TEMPLATES | PRONTA | `tests/test_design_system.py` | tema sozinho não muda a estrutura |
| 79 | REGRAS DE DESIGN | PRONTA | `tests/test_design_system.py` | público muda a estrutura |
| 80 | FORTNITE | ABERTA | `—` |  |
| 81 | MINECRAFT | ABERTA | `—` |  |
| 82 | GTA RP | ABERTA | `—` |  |
| 83 | OUTROS TEMAS | ABERTA | `—` |  |
| 84 | SERVER REBUILD | ABERTA | `—` |  |
| 85 | MIGRAÇÃO | ABERTA | `—` |  |
| 86 | BACKUP LÓGICO | PRONTA | `1991c78` | backup lógico |
| 87 | ROLLBACK | PARCIAL | `1991c78` | rollback só inverte criações |
| 88 | CONFIGURATION VERSIONING | PRONTA | `tests/test_snapshot.py` | versionamento JSONL por guild (Fase 13 `9797e35`) |
| 89 | TASK SYSTEM | PRONTA | `3cadac1` | task system com estados |
| 90 | CANCELAMENTO | PRONTA | `76ae5c1` | cancelamento de tarefa |
| 91 | TIMEOUTS | ABERTA | `—` |  |
| 92 | RESILIÊNCIA | ABERTA | `—` |  |
| 93 | RECUPERAÇÃO APÓS RESTART | PRONTA | `tests/test_recuperacao.py` | classifica pós-restart, não executa |
| 94 | SEGURANÇA DE SEGREDOS | PRONTA | `tests/test_audit.py` | segredo mascarado antes do handler de log |
| 95 | CONFIGURAÇÃO | ABERTA | `—` |  |
| 96 | DOCUMENTAÇÃO | ABERTA | `—` |  |
| 97 | TESTES UNITÁRIOS | ABERTA | `—` |  |
| 98 | TESTES DE INTEGRAÇÃO | ABERTA | `—` |  |
| 99 | TESTES E2E | ABERTA | `—` |  |
| 100 | TESTES DE SEGURANÇA | ABERTA | `—` |  |
| 101 | TESTES DE CONCORRÊNCIA | ABERTA | `—` |  |
| 102 | TESTES DE FALHA | ABERTA | `—` |  |
| 103 | LOAD TESTING | ABERTA | `—` |  |
| 104 | PERFORMANCE | ABERTA | `—` |  |
| 105 | CUSTO | ABERTA | `—` |  |
| 106 | PROVIDER COST-AWARE ROUTING | ABERTA | `—` |  |
| 107 | MODEL SELECTION | PRONTA | `tests/test_classificacao.py` | classe da tarefa influencia a rota |
| 108 | TOOL-CALLING | ABERTA | `—` |  |
| 109 | STRUCTURED OUTPUT | ABERTA | `—` |  |
| 110 | STREAMING | ABERTA | `—` |  |
| 111 | CONVERSAÇÃO NATURAL | ABERTA | `—` |  |
| 112 | NÃO EXPOR RACIOCÍNIO INTERNO | ABERTA | `—` |  |
| 113 | ESTADO DO AGENTE | PRONTA | `tests/test_estados.py` | estados do agente |
| 114 | CANCELAMENTO E CONFLITOS | ABERTA | `—` |  |
| 115 | PRIORIDADE | PRONTA | `tests/test_classificacao.py` | prioridade de rota |
| 116 | BACKGROUND DISCOVERY | FORA DE ESCOPO | `decisão` | verificada como satisfeita por ausência: nada atrasa pedido simples |
| 117 | CACHE DE PESQUISA | ABERTA | `—` |  |
| 118 | QUALIDADE DAS FONTES | ABERTA | `—` |  |
| 119 | SISTEMA DE CONFIANÇA | PRONTA | `tests/test_catalogo.py` | filtro por confiança mínima |
| 120 | AUTO-DIAGNÓSTICO | ABERTA | `—` |  |
| 121 | HEALTH DASHBOARD INTERNO | ABERTA | `—` |  |
| 122 | ALERTAS | ABERTA | `—` |  |
| 123 | LIMPEZA DE CÓDIGO | ABERTA | `—` |  |
| 124 | COMPATIBILIDADE | ABERTA | `—` |  |
| 125 | DISCORD API CHANGES | ABERTA | `—` |  |
| 126 | EXTENSIBILIDADE | ABERTA | `—` |  |
| 127 | PLUGIN-STYLE TOOLS | ABERTA | `—` |  |
| 128 | NÃO CRIAR COMPLEXIDADE SEM NECESSIDADE | ABERTA | `—` |  |
| 129 | PRINCÍPIO DE SIMPLICIDADE | ABERTA | `—` |  |
| 130 | EXPERIÊNCIA DO USUÁRIO | PARCIAL | `src/atlas/design.py` | proposta concreta entra no prompt |
| 131 | INTERPRETAÇÃO DE PEDIDOS CURTOS | ABERTA | `—` |  |
| 132 | NÃO ASSUMIR DEMAIS | ABERTA | `—` |  |
| 133 | EXPLICAÇÃO DE AÇÕES | ABERTA | `—` |  |
| 134 | LOGS TÉCNICOS | ABERTA | `—` |  |
| 135 | SISTEMA DE DESIGN ADAPTATIVO | PRONTA | `tests/test_design_system.py` | briefing antes de qualquer canal |
| 136 | DESIGN SCORE INTERNO | PRONTA | `tests/test_design_system.py` | 7 critérios com pontos e motivo |
| 137 | REVISÃO ANTES DE EXECUTAR | PRONTA | `tests/test_design_system.py` | precisa_refazer, limiar 8.0 |
| 138 | REVISÃO DEPOIS DE EXECUTAR | PARCIAL | `src/atlas/agent.py` | _qa_pos_execucao existe e a divergência é testada em test_autofix, mas falta teste dedicado do laço estado-real-vs-design |
| 139 | APRENDIZADO POR FEEDBACK | ABERTA | `—` |  |
| 140 | NÃO REPETIR ERROS | PRONTA | `tests/test_catalogo.py` | feedback por guild, promover exige fonte |
| 141 | PESQUISA CONTÍNUA DE DESIGN | ABERTA | `—` |  |
| 142 | PESQUISA CONTÍNUA DE TECNOLOGIA | ABERTA | `—` |  |
| 143 | PESQUISA CONTÍNUA DE IA | ABERTA | `—` |  |
| 144 | FILTRO DE PROVIDERS | ABERTA | `—` |  |
| 145 | POOL DINÂMICO | ABERTA | `—` |  |
| 146 | MANUAL REQUIRED | ABERTA | `—` |  |
| 147 | SEM CHAVE NÃO SIGNIFICA SEM RESTRIÇÃO | ABERTA | `—` |  |
| 148 | ESCALABILIDADE | PRONTA | `tests/test_flow_control.py` | backpressure e fila |
| 149 | BACKPRESSURE | PRONTA | `tests/test_flow_control.py` | backpressure |
| 150 | FAIRNESS | PRONTA | `tests/test_flow_control.py` | cota por guild em janela |
| 151 | SEGURANÇA DE TOOLS | PRONTA | `tests/test_security.py` | barreiras de schema, auth, policy e contexto |
| 152 | TOOL RESULT | ABERTA | `—` |  |
| 153 | OBSERVAÇÃO DO DISCORD | ABERTA | `—` |  |
| 154 | EVENTUAL CONSISTENCY | ABERTA | `—` |  |
| 155 | OPERAÇÕES EM LOTE | PRONTA | `tests/test_batch.py` | lote respeita a cota e reporta falhas |
| 156 | PROGRESSO | PRONTA | `76ae5c1` | progresso parcial |
| 157 | CONCLUSÃO | ABERTA | `—` |  |
| 158 | CANCELAMENTO SEGURO | PRONTA | `76ae5c1` | cancelamento cooperativo |
| 159 | AUDITORIA FINAL DO SISTEMA | ABERTA | `—` |  |
| 160 | REGRA DE "DONE" | ABERTA | `—` |  |
| 161 | ROADMAP AUTOMÁTICO | ABERTA | `—` |  |
| 162 | NÃO PARAR NO ROADMAP | ABERTA | `—` |  |
| 163 | NÃO PULAR DEPENDÊNCIAS | ABERTA | `—` |  |
| 164 | CHECKPOINTS | ABERTA | `—` |  |
| 165 | REGRA DE RECUPERAÇÃO | ABERTA | `—` |  |
| 166 | LIMPEZA FINAL | ABERTA | `—` |  |
| 167 | AUDITORIA DE SEGURANÇA FINAL | ABERTA | `—` |  |
| 168 | AUDITORIA DE DESIGN FINAL | ABERTA | `—` |  |
| 169 | TESTE DE PERSONALIDADE | PRONTA | `tests/test_design_system.py` | compara forma pelo propósito, nunca pelo nome |
| 170 | TESTE DE USABILIDADE | ABERTA | `—` |  |
| 171 | TESTE DE ADMINISTRADOR | ABERTA | `—` |  |
| 172 | TESTE DE ESCALA | ABERTA | `—` |  |
| 173 | TESTE DE CONCORRÊNCIA | ABERTA | `—` |  |
| 174 | TESTE DE PROVIDERS | ABERTA | `—` |  |
| 175 | TESTE DE TOOL CAPABILITY | ABERTA | `—` |  |
| 176 | TESTE DE SEGURANÇA | PRONTA | `tests/test_security.py` | outra guild, permissão proibida, membro, injection — todos falham |
| 177 | TESTE DE CONFIRMAÇÃO | PRONTA | `tests/test_batch.py` | confirmação vencida não executa |
| 178 | TESTE DE DUPLICAÇÃO | PRONTA | `tests/test_tools_basic.py` | não cria duas categorias |
| 179 | TESTE DE RESTART | ABERTA | `—` |  |
| 180 | TESTE DE PARTIAL FAILURE | PRONTA | `tests/test_batch.py` | falha parcial: estado, logs e resposta |
| 181 | DOCUMENTAÇÃO FINAL | ABERTA | `—` |  |
| 182 | RESULTADO FINAL ESPERADO | ABERTA | `—` |  |
| 183 | REGRA FINAL DE INTELIGÊNCIA | ABERTA | `—` |  |
| 184 | REGRA FINAL DE PESQUISA | ABERTA | `—` |  |
| 185 | REGRA FINAL DE IMPLEMENTAÇÃO | ABERTA | `—` |  |
| 186 | REGRA FINAL DE AUTONOMIA | ABERTA | `—` |  |
| 187 | PRIMEIRA AÇÃO AO RECEBER ESTE DOCUMENTO | ABERTA | `—` |  |

## Resumo

- PRONTA: **73**
- PARCIAL: **5**
- ABERTA: **104**
- FORA DE ESCOPO: **6**
- Total: **188**

Se a soma não bater com o total, o parser perdeu seção: conserte o parser,
não o número.
