# Razão da MASTER SPECIFICATION

Gerado por `scripts/spec_ledger.py`. **Não editar à mão** — o script
confronta cada evidência com o repositório e falha se ela não existir.
Default é `ABERTA`: seção só sai de aberta com evidência verificada.

Seções na spec: **188**

| # | Seção | Estado | Evidência | Obs. |
|---|---|---|---|---|
| 0 | MISSÃO DO SISTEMA | PROCESSO | `README.md` | missão registrada; o produto é arquiteto de servidor, não bot de comando |
| 1 | REGRA ABSOLUTA: AUDITAR ANTES DE ALTERAR | PROCESSO | `docs/AUDITORIA.md` | auditoria antes de alterar — o próprio documento é a prática |
| 2 | EXECUÇÃO POR FASES | PROCESSO | `docs/ROADMAP.md` | execução por fases, uma por vez, com teste entre elas |
| 3 | NÃO PERDER FUNCIONALIDADES EXISTENTES | PROCESSO | `docs/ROADMAP.md` | implementar novo → testar → migrar → verificar → remover antigo |
| 4 | PROIBIÇÃO DE MERGE | PROCESSO | `docs/AUDITORIA.md` | zero merge: verificável por git log --merges |
| 5 | ARQUITETURA GERAL | PROCESSO | `README.md` | camadas da arquitetura documentadas |
| 6 | DISCORD.JS É A CAMADA REAL DE EXECUÇÃO | PROCESSO | `README.md` | discord.py é a camada real; nenhum placeholder de execução |
| 7 | CONTEXTO REAL DO DISCORD | PRONTA | `tests/test_security.py` | guild_id estranho é ignorado e não autoriza |
| 8 | ISOLAMENTO POR GUILD | PRONTA | `tests/test_security.py` | bind_guild recusa outro servidor; chaves de guild removidas em massa |
| 9 | MODELO MENTAL DO AGENTE | PROCESSO | `README.md` | entender → planejar → validar → executar → verificar → corrigir → responder |
| 10 | INTENÇÃO DO USUÁRIO | PROCESSO | `README.md` | linguagem natural como entrada |
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
| 34 | IDENTIDADE TEMÁTICA | PARCIAL | `src/atlas/design.py` | tema influencia vocabulário via proposta no prompt, mas não muda estrutura em código - a spec pede mais que isso |
| 35 | DIREÇÃO VISUAL | PRONTA | `tests/test_design_system.py` | 13 estilos visuais |
| 36 | NOMENCLATURA | PRONTA | `tests/test_design_system.py` | nomenclatura uniforme, sem misturar |
| 37 | CATEGORIAS | PRONTA | `tests/test_design_system.py` | áreas conceituais com propósito |
| 38 | CANAIS | PRONTA | `tests/test_design_system.py` | todo canal tem propósito declarado |
| 39 | TIPOS DE CANAL | PRONTA | `tests/test_design_system.py` | texto, voz, anúncio e fórum; tem teste que compara com o enum real da tool |
| 40 | CARGOS | PRONTA | `tests/test_design_system.py` | funcional x identidade separados |
| 41 | HIERARQUIA DE CARGOS | PRONTA | `tests/test_design_system.py` | hierarquia cresce com o porte |
| 42 | PERMISSÕES | PRONTA | `tests/test_design_system.py` | nenhum funcional nasce com administrator |
| 43 | ONBOARDING | PRONTA | `tests/test_design_system.py` | jornada de onboarding por domínio |
| 44 | ESCALA | PRONTA | `tests/test_design_system.py` | porte corta a arquitetura |
| 45 | RECONSTRUÇÃO DE SERVIDORES | PRONTA | `tests/test_reforma.py` | audita nomenclatura mista, categoria demais, admin demais + os defeitos que design_check já achava |
| 46 | PRESERVAÇÃO | PRONTA | `tests/test_reforma.py` | nada é excluído: sobra vira suspeita para decisão humana; canal padrão é preservado |
| 47 | SERVER DESIGN QA | PRONTA | `tests/test_design_check.py` | QA interno: categoria vazia, canal duplicado, cargo com admin, canal órfão |
| 48 | MEMÓRIA | PRONTA | `tests/test_batch.py` | memória de contexto entre mensagens, separada por guild |
| 49 | CONTEXTO | PRONTA | `tests/test_wiring.py` | _trim() limita a janela; histórico vira mensagens OpenAI com ids casados e parte inútil é descartada |
| 50 | PROMPT INJECTION | PRONTA | `tests/test_security.py` | prompt injection bloqueado; unicode invisível detectado |
| 51 | AI ROUTER | PRONTA | `tests/test_router.py` | camada abstrata: base_url/modelo por gateway, sem provider fixo |
| 52 | MULTI-PROVIDER | PRONTA | `tests/test_router.py` | catálogo com gateway/modelo/capacidade/limite; pool sobrevive a gateway inteiro caindo |
| 53 | DESCOBERTA DE PROVIDERS | PARCIAL | `src/atlas/ai/discovery.py` | reavalia o pool continuamente (probe/reavaliar); descobrir provedor novo na web está fora de escopo |
| 54 | NO-KEY / FREE-FIRST | PRONTA | `tests/test_providers_spec.py` | pool default sem chave, nenhuma chave embutida, quem exige está MANUAL_REQUIRED |
| 55 | NÃO BYPASSAR LIMITES | PRONTA | `tests/test_providers_spec.py` | rpm declarado por gateway é o teto; nada acima do que o tier gratuito dá |
| 56 | HEALTH CHECK | PRONTA | `tests/test_router.py` | falhas repetidas colocam a rota em cooldown |
| 57 | FALLBACK | PRONTA | `tests/test_router.py` | falha transitória vai para a próxima rota |
| 58 | CAPABILITY ROUTING | PRONTA | `tests/test_router.py` | pedido com tools exige rota com tool calling |
| 59 | REGRA "NÃO CONSIGO" | PRONTA | `tests/test_router.py` | só informa limitação depois de esgotar o pool |
| 60 | LOAD BALANCING | PRONTA | `tests/test_router.py` | carga se distribui em vez de empilhar na primeira rota |
| 61 | CIRCUIT BREAKER | PRONTA | `tests/test_router.py` | cooldown acaba e a rota volta em half-open |
| 62 | RETRIES | PRONTA | `tests/test_router.py` | cooldown cresce a cada queda seguida |
| 63 | FILAS | PRONTA | `tests/test_wiring.py` | fila em série com rate limit, auditoria e isolamento por guild; 429 não insiste na mesma rota |
| 64 | CONCORRÊNCIA | PRONTA | `tests/test_flow_control.py` | concorrência controlada |
| 65 | LOCK POR GUILD | PRONTA | `tests/test_flow_control.py` | trava por guild |
| 66 | RATE LIMIT DISCORD | PRONTA | `tests/test_security.py` | rate limit por servidor |
| 67 | CACHE | PRONTA | `tests/test_router.py` | cache expira e é invalidado por mutação |
| 68 | OBSERVABILIDADE | PRONTA | `tests/test_observability.py` | resumo conta ok e falha, separa guilds, aguenta linha corrompida |
| 69 | LOGS | PRONTA | `tests/test_audit.py` | segredo mascarado; parâmetros sensíveis não são auditados |
| 70 | AUDITORIA | PRONTA | `tests/test_audit.py` | registro de auditoria tem os campos exigidos |
| 71 | COMPONENTS V2 | PRONTA | `tests/test_embeds.py` | embed vira cartão Components V2 (flags 32768) |
| 72 | UI CONTROLADA PELO CÓDIGO | PRONTA | `tests/test_embeds.py` | cartão V2 também passa pela limpeza; o modelo dá o texto, o código monta |
| 73 | BOTÕES | PRONTA | `tests/test_botoes.py` | as sete barreiras do clique |
| 74 | ERROS | PRONTA | `tests/test_errors.py` | erro de permissão e erro da API viram mensagem útil |
| 75 | PESQUISA CONTÍNUA | FORA DE ESCOPO | `decisão` | pesquisa na web |
| 76 | APRENDIZADO | PRONTA | `tests/test_catalogo.py` | padrão é classificado por confiança e revisado por feedback; nada entra como verdade automática |
| 77 | LICENÇAS | FORA DE ESCOPO | `decisão` | nenhum código externo foi incorporado; dependências são discord.py e openai, ambas Apache/MIT |
| 78 | SISTEMA DE TEMPLATES | PRONTA | `tests/test_design_system.py` | tema sozinho não muda a estrutura |
| 79 | REGRAS DE DESIGN | PRONTA | `tests/test_design_system.py` | público muda a estrutura |
| 80 | FORTNITE | PRONTA | `tests/test_design_final.py` | Fortnite competitivo tem LFG e recrutamento; casual não vira esports |
| 81 | MINECRAFT | PRONTA | `tests/test_design_final.py` | Minecraft casual tem dúvidas e voz, não área de torneio |
| 82 | GTA RP | PRONTA | `tests/test_design_final.py` | GTA RP tem personagem, facções e recrutamento |
| 83 | OUTROS TEMAS | PRONTA | `tests/test_design_final.py` | clube de leitura, fotografia e investimentos caem em domínio válido |
| 84 | SERVER REBUILD | PRONTA | `tests/test_reforma.py` | AUDITAR → MAPEAR → PLANEJAR → MOSTRAR IMPACTO; não executa |
| 85 | MIGRAÇÃO | PRONTA | `tests/test_reforma.py` | mapeia old→new e preserva id: renomeia e move em vez de excluir e recriar |
| 86 | BACKUP LÓGICO | PRONTA | `1991c78` | backup lógico |
| 87 | ROLLBACK | PARCIAL | `1991c78` | rollback só inverte criações |
| 88 | CONFIGURATION VERSIONING | PRONTA | `tests/test_snapshot.py` | versionamento JSONL por guild (Fase 13 `9797e35`) |
| 89 | TASK SYSTEM | PRONTA | `3cadac1` | task system com estados |
| 90 | CANCELAMENTO | PRONTA | `76ae5c1` | cancelamento de tarefa |
| 91 | TIMEOUTS | PRONTA | `tests/test_wiring.py` | deadline por pedido e timeout por chamada; prazo 0 corta antes da primeira chamada |
| 92 | RESILIÊNCIA | PRONTA | `tests/test_errors.py` | provider offline, erro da IA, erro da API Discord, timeout — o agente responde em todos |
| 93 | RECUPERAÇÃO APÓS RESTART | PRONTA | `tests/test_recuperacao.py` | classifica pós-restart, não executa |
| 94 | SEGURANÇA DE SEGREDOS | PRONTA | `tests/test_audit.py` | segredo mascarado antes do handler de log |
| 95 | CONFIGURAÇÃO | PROCESSO | `README.md` | configuração centralizada em config.py |
| 96 | DOCUMENTAÇÃO | PROCESSO | `README.md` | documentação de arquitetura, tools, providers, env, execução, segurança |
| 97 | TESTES UNITÁRIOS | PRONTA | `tests/` | suíte de testes unitários: planners, validadores, schemas, routing, permissões, parsers, tools |
| 98 | TESTES DE INTEGRAÇÃO | PRONTA | `tests/test_wiring.py` | agente → tool → executor → gateway em ambiente controlado |
| 99 | TESTES E2E | PRONTA | `tests/test_wiring.py` | fluxo completo: pedido → plano → tools → verificação → resposta |
| 100 | TESTES DE SEGURANÇA | PRONTA | `tests/test_security.py` | injection, guild spoofing, escalada, ID manipulado, stale confirmation, cross-guild, segredo |
| 101 | TESTES DE CONCORRÊNCIA | PRONTA | `tests/test_router.py` | muitos usuários, várias guilds, provider falhando, rate limit |
| 102 | TESTES DE FALHA | PRONTA | `tests/test_errors.py` | provider offline, Discord indisponível, tool error, timeout, sucesso parcial, restart |
| 103 | LOAD TESTING | PRONTA | `tests/test_flow_control.py` | carga com simulação: cota, backpressure, teto de guilds — sem bombardear API real |
| 104 | PERFORMANCE | PRONTA | `tests/test_router.py` | cache por guild com TTL e invalidação por mutação; leitura não invalida |
| 105 | CUSTO | PRONTA | `tests/test_providers_spec.py` | pool inteiro gratuito; cache evita chamada redundante |
| 106 | PROVIDER COST-AWARE ROUTING | PRONTA | `tests/test_providers_spec.py` | pool inteiro gratuito e anônimo — não há eixo de custo; teste impede entrar provedor pago sem notar |
| 107 | MODEL SELECTION | PRONTA | `tests/test_classificacao.py` | classe da tarefa influencia a rota |
| 108 | TOOL-CALLING | PRONTA | `tests/test_router.py` | pedido com tools exige rota com tool calling; sem tools usa rota sem |
| 109 | STRUCTURED OUTPUT | PARCIAL | `src/atlas/ai/providers.py` | nenhuma rota do pool gratuito declara structured_output; a saída estruturada vem de tool calling, que é testado |
| 110 | STREAMING | FORA DE ESCOPO | `decisão` | streaming deliberadamente ausente: a spec 110 diz para não usar quando prejudicar consistência, e a resposta é uma mensagem só |
| 111 | CONVERSAÇÃO NATURAL | PRONTA | `tests/test_embeds.py` | STYLE no prompt + limpar() em código: tira tabela, cabeçalho, markdown pesado e caractere exótico |
| 112 | NÃO EXPOR RACIOCÍNIO INTERNO | PRONTA | `tests/test_antivazamento.py` | filtro na saída derivado do prompt real; pega caixa/quebra diferente e não censura resposta legítima |
| 113 | ESTADO DO AGENTE | PRONTA | `tests/test_estados.py` | estados do agente |
| 114 | CANCELAMENTO E CONFLITOS | PRONTA | `tests/test_wiring.py` | guild travado devolve guild_busy em vez de misturar planos; trava liberada mesmo com exceção |
| 115 | PRIORIDADE | PRONTA | `tests/test_classificacao.py` | prioridade de rota |
| 116 | BACKGROUND DISCOVERY | FORA DE ESCOPO | `decisão` | verificada como satisfeita por ausência: nada atrasa pedido simples |
| 117 | CACHE DE PESQUISA | FORA DE ESCOPO | `decisão` | cache de pesquisa: não há pesquisa na web — 21 tools fixas, todas de Discord |
| 118 | QUALIDADE DAS FONTES | FORA DE ESCOPO | `decisão` | qualidade das fontes: não há fonte externa sendo consumida |
| 119 | SISTEMA DE CONFIANÇA | PRONTA | `tests/test_catalogo.py` | filtro por confiança mínima |
| 120 | AUTO-DIAGNÓSTICO | PRONTA | `tests/test_observability.py` | as três perguntas apontam a falha |
| 121 | HEALTH DASHBOARD INTERNO | PRONTA | `tests/test_observability.py` | painel avisa IA morta, pool degradado, e diz quando está bem |
| 122 | ALERTAS | PRONTA | `tests/test_alertas.py` | os seis gatilhos da spec: erro elevado, pool fora, fila acumulada, 429, falhas repetidas, tarefas presas |
| 123 | LIMPEZA DE CÓDIGO | PROCESSO | `docs/AUDITORIA.md` | limpeza só depois de estável; Gemini antigo já removido |
| 124 | COMPATIBILIDADE | PROCESSO | `docs/AUDITORIA.md` | dependências pinadas; discord.py 2.7.1 medido, não atualizado às cegas |
| 125 | DISCORD API CHANGES | PROCESSO | `docs/AUDITORIA.md` | mudanças da API acompanhadas na auditoria |
| 126 | EXTENSIBILIDADE | PROCESSO | `README.md` | tools, providers e domínios são dados, não código fixo |
| 127 | PLUGIN-STYLE TOOLS | PRONTA | `tests/test_policy.py` | tools modulares: channels.py, roles.py, server.py, read.py — registry recusa ferramenta proibida |
| 128 | NÃO CRIAR COMPLEXIDADE SEM NECESSIDADE | PROCESSO | `docs/AUDITORIA.md` | cada camada tem propósito registrado |
| 129 | PRINCÍPIO DE SIMPLICIDADE | PROCESSO | `README.md` | complexo por dentro, simples para o usuário |
| 130 | EXPERIÊNCIA DO USUÁRIO | PRONTA | `tests/test_perguntas.py` | pergunta só o que não dá para inferir (sobra de reforma); tema/porte/estilo são inferidos e reversíveis |
| 131 | INTERPRETAÇÃO DE PEDIDOS CURTOS | PRONTA | `tests/test_reforma.py` | "arruma", "organiza", "refaz" viram auditoria + plano de reforma; alvo pontual não |
| 132 | NÃO ASSUMIR DEMAIS | PRONTA | `tests/test_batch.py` | exclusão múltipla exige confirmação; inferência reversível pode, destrutiva não |
| 133 | EXPLICAÇÃO DE AÇÕES | PRONTA | `tests/test_embeds.py` | resumo do que foi feito e do que não pôde; sem despejo de log técnico |
| 134 | LOGS TÉCNICOS | PRONTA | `tests/test_observability.py` | log completo fica no painel; o usuário recebe resumo |
| 135 | SISTEMA DE DESIGN ADAPTATIVO | PRONTA | `tests/test_design_system.py` | briefing antes de qualquer canal |
| 136 | DESIGN SCORE INTERNO | PRONTA | `tests/test_design_system.py` | 7 critérios com pontos e motivo |
| 137 | REVISÃO ANTES DE EXECUTAR | PRONTA | `tests/test_design_system.py` | precisa_refazer, limiar 8.0 |
| 138 | REVISÃO DEPOIS DE EXECUTAR | PRONTA | `tests/test_design_check.py` | conferir_contra_design compara estado real com o projetado; roda na conclusão normal, não só no limite de turnos |
| 139 | APRENDIZADO POR FEEDBACK | PRONTA | `tests/test_catalogo.py` | registrar_feedback por guild; promover exige fonte não vazia |
| 140 | NÃO REPETIR ERROS | PRONTA | `tests/test_catalogo.py` | feedback por guild, promover exige fonte |
| 141 | PESQUISA CONTÍNUA DE DESIGN | FORA DE ESCOPO | `decisão` | pesquisa contínua de design: fora de escopo (sem busca na web) |
| 142 | PESQUISA CONTÍNUA DE TECNOLOGIA | FORA DE ESCOPO | `decisão` | pesquisa contínua de tecnologia: fora de escopo |
| 143 | PESQUISA CONTÍNUA DE IA | FORA DE ESCOPO | `decisão` | pesquisa contínua de IA: o pool é reavaliado por probe, mas descobrir provedor novo na web está fora |
| 144 | FILTRO DE PROVIDERS | PRONTA | `tests/test_router.py` | probe classifica rota e reavaliar afasta a ruim / revive a boa |
| 145 | POOL DINÂMICO | PRONTA | `tests/test_router.py` | pool com gateway/modelo/capacidade/saúde/latência/limite/peso |
| 146 | MANUAL REQUIRED | PRONTA | `tests/test_providers_spec.py` | MANUAL_REQUIRED marcado e sem chave; o sistema continua |
| 147 | SEM CHAVE NÃO SIGNIFICA SEM RESTRIÇÃO | PRONTA | `tests/test_providers_spec.py` | todo gateway sem chave tem rpm e concorrência declarados |
| 148 | ESCALABILIDADE | PRONTA | `tests/test_flow_control.py` | backpressure e fila |
| 149 | BACKPRESSURE | PRONTA | `tests/test_flow_control.py` | backpressure |
| 150 | FAIRNESS | PRONTA | `tests/test_flow_control.py` | cota por guild em janela |
| 151 | SEGURANÇA DE TOOLS | PRONTA | `tests/test_security.py` | barreiras de schema, auth, policy e contexto |
| 152 | TOOL RESULT | PRONTA | `tests/test_batch.py` | ActionResult: ok=success, status derivado, data, error, metadata real (tool, duração, guild, corrigiu) |
| 153 | OBSERVAÇÃO DO DISCORD | PRONTA | `tests/test_errors.py` | verificação pós-ação compara com o Discord e detecta mudança que não aconteceu |
| 154 | EVENTUAL CONSISTENCY | PRONTA | `tests/test_wiring.py` | verificar exclusão usa retry — o Discord pode não refletir na hora |
| 155 | OPERAÇÕES EM LOTE | PRONTA | `tests/test_batch.py` | lote respeita a cota e reporta falhas |
| 156 | PROGRESSO | PRONTA | `tests/test_progresso.py` | progresso informado |
| 157 | CONCLUSÃO | PRONTA | `tests/test_embeds.py` | contagem Criados/Alterados/Não concluídos em operação grande; pequena fica só na frase |
| 158 | CANCELAMENTO SEGURO | PRONTA | `76ae5c1` | cancelamento cooperativo |
| 159 | AUDITORIA FINAL DO SISTEMA | PROCESSO | `docs/AUDITORIA.md` | re-auditoria do sistema |
| 160 | REGRA DE "DONE" | PROCESSO | `docs/AUDITORIA.md` | regra de DONE: o gerador do razão exige teste para marcar PRONTA |
| 161 | ROADMAP AUTOMÁTICO | PROCESSO | `docs/ROADMAP.md` | roadmap derivado do estado real |
| 162 | NÃO PARAR NO ROADMAP | PROCESSO | `docs/ROADMAP.md` | fases implementadas, não só planejadas |
| 163 | NÃO PULAR DEPENDÊNCIAS | PROCESSO | `docs/ROADMAP.md` | dependência primeiro |
| 164 | CHECKPOINTS | PROCESSO | `docs/ROADMAP.md` | checkpoint por fase, cada uma com commit próprio |
| 165 | REGRA DE RECUPERAÇÃO | PROCESSO | `docs/AUDITORIA.md` | quebrou algo antigo: parar, identificar, corrigir, testar |
| 166 | LIMPEZA FINAL | PROCESSO | `docs/AUDITORIA.md` | limpeza final |
| 167 | AUDITORIA DE SEGURANÇA FINAL | PROCESSO | `docs/AUDITORIA.md` | auditoria de segurança final |
| 168 | AUDITORIA DE DESIGN FINAL | PRONTA | `tests/test_design_final.py` | os 10 cenários da spec comparados por forma: nenhum repete estrutura |
| 169 | TESTE DE PERSONALIDADE | PRONTA | `tests/test_design_system.py` | compara forma pelo propósito, nunca pelo nome |
| 170 | TESTE DE USABILIDADE | PRONTA | `tests/test_design_final.py` | primeiro canal é de chegada e a jornada começa pelo combinado |
| 171 | TESTE DE ADMINISTRADOR | PRONTA | `tests/test_design_final.py` | hierarquia sem posição repetida; servidor grande tem staff privada |
| 172 | TESTE DE ESCALA | PRONTA | `tests/test_design_final.py` | projeção em porte grande mantém nota e não estoura em canal inútil |
| 173 | TESTE DE CONCORRÊNCIA | PRONTA | `tests/test_router.py` | muitos usuários simultâneos não se misturam; concorrência respeita limite por gateway |
| 174 | TESTE DE PROVIDERS | PRONTA | `tests/test_router.py` | gateway caindo inteiro, 429 como fila, chave exigida, pool sem rota compatível |
| 175 | TESTE DE TOOL CAPABILITY | PRONTA | `tests/test_router.py` | probe detecta modelo sem tool calling; router escolhe pela capacidade |
| 176 | TESTE DE SEGURANÇA | PRONTA | `tests/test_security.py` | outra guild, permissão proibida, membro, injection — todos falham |
| 177 | TESTE DE CONFIRMAÇÃO | PRONTA | `tests/test_batch.py` | confirmação vencida não executa |
| 178 | TESTE DE DUPLICAÇÃO | PRONTA | `tests/test_tools_basic.py` | não cria duas categorias |
| 179 | TESTE DE RESTART | PRONTA | `tests/test_recuperacao.py` | tarefa interrompida de verdade é detectada; nada é reexecutado às cegas |
| 180 | TESTE DE PARTIAL FAILURE | PRONTA | `tests/test_batch.py` | falha parcial: estado, logs e resposta |
| 181 | DOCUMENTAÇÃO FINAL | PROCESSO | `README.md` | documentação final |
| 182 | RESULTADO FINAL ESPERADO | PRONTA | `tests/test_wiring.py` | pedido → plano → tools → verificação → resposta, de ponta a ponta |
| 183 | REGRA FINAL DE INTELIGÊNCIA | PROCESSO | `README.md` | princípios fundamentais registrados |
| 184 | REGRA FINAL DE PESQUISA | FORA DE ESCOPO | `decisão` | regra final de pesquisa: depende de acesso legítimo a busca, que não existe neste projeto |
| 185 | REGRA FINAL DE IMPLEMENTAÇÃO | PROCESSO | `docs/AUDITORIA.md` | sem placeholder, mock escondido, sucesso falso |
| 186 | REGRA FINAL DE AUTONOMIA | PROCESSO | `docs/AUDITORIA.md` | limites de autonomia registrados |
| 187 | PRIMEIRA AÇÃO AO RECEBER ESTE DOCUMENTO | PROCESSO | `docs/AUDITORIA.md` | fase 0 foi auditoria, fase 1 foi roadmap real |

## Resumo

- PRONTA: **137**
- PARCIAL: **6**
- ABERTA: **0**
- FORA DE ESCOPO: **14**
- PROCESSO: **31**
- Total: **188**

Se a soma não bater com o total, o parser perdeu seção: conserte o parser,
não o número.
