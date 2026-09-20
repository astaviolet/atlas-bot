"""Router, health, cache e discovery. Tudo com doubles: nenhum teste toca a rede."""

from __future__ import annotations

from typing import Any

import pytest

from atlas.ai import (
    Capabilities,
    FunctionCall,
    Gateway,
    Health,
    HealthRegistry,
    ModelRoute,
    ModelTurn,
    RequestCache,
    Router,
    chave_pedido,
)
from atlas.ai.discovery import ProbeResult, ProbeStatus, probe_rota, reavaliar, resumo_probes
from atlas.ai import build_ai_client
from atlas.errors import AIError


# --------------------------------------------------------------------- doubles
class FakeClient:
    """Cliente controlado por teste. Registra o que recebeu."""

    def __init__(self, gateway_id: str, comportamento: dict[str, Any]) -> None:
        self.gateway_id = gateway_id
        self.comportamento = comportamento
        self.chamadas: list[str] = []

    def generate(self, *, system, history, tools, model=None, guild_id=None, classe=None):
        self.chamadas.append(model or "?")
        regra = self.comportamento.get(model, "ok")
        if isinstance(regra, Exception):
            raise regra
        if regra == "ok":
            return ModelTurn(calls=[FunctionCall("create_channel", {"name": "x"}, id="c1")])
        if regra == "texto":
            return ModelTurn(text="resposta em texto")
        raise AssertionError(f"regra desconhecida: {regra}")


def catalogo_fake() -> list[Gateway]:
    """Tres gateways independentes, como o pool real."""
    return [
        Gateway(id="A", base_url="https://a/v1", rpm=None, concurrency=2, models=[
            ModelRoute(gateway="A", model="a1", weight=100),
            ModelRoute(gateway="A", model="a2", weight=100),
        ]),
        Gateway(id="B", base_url="https://b/v1", rpm=None, concurrency=2, models=[
            ModelRoute(gateway="B", model="b1", weight=100),
        ]),
        Gateway(id="C", base_url="https://c/v1", rpm=None, concurrency=1, models=[
            ModelRoute(gateway="C", model="c1", weight=100),
        ]),
    ]


def make_router(comportamento: dict[str, Any], **kw) -> tuple[Router, dict[str, FakeClient]]:
    clientes: dict[str, FakeClient] = {}

    def factory(g: Gateway):
        clientes[g.id] = FakeClient(g.id, comportamento)
        return clientes[g.id]

    cat = kw.pop("catalog", None) or catalogo_fake()
    router = Router(cat, client_factory=factory, backoff_seconds=0.0, **kw)
    return router, clientes


TOOLS = [{"type": "function", "function": {"name": "create_channel", "parameters": {}}}]


# ------------------------------------------------------- capability routing
def test_pedido_com_tools_exige_rota_com_tool_calling():
    sem_tool = [Gateway(id="X", base_url="https://x/v1", models=[
        ModelRoute(gateway="X", model="m", caps=Capabilities(tool_calling=False)),
    ])]
    router, _ = make_router({}, catalog=sem_tool)
    with pytest.raises(AIError) as info:
        router.generate(system="s", history=[], tools=TOOLS)
    assert "nenhuma rota" in str(info.value)


def test_pedido_sem_tools_usa_rota_sem_tool_calling():
    so_texto = [Gateway(id="X", base_url="https://x/v1", models=[
        ModelRoute(gateway="X", model="m", caps=Capabilities(tool_calling=False)),
    ])]
    router, _ = make_router({"m": "texto"}, catalog=so_texto)
    turno = router.generate(system="s", history=[], tools=[])
    assert turno.text == "resposta em texto"


def test_rota_sem_tool_calling_nunca_recebe_pedido_de_discord():
    """Regra da missao: nao mandar tarefa de Discord para modelo sem tool calling."""
    cat = [Gateway(id="X", base_url="https://x/v1", models=[
        ModelRoute(gateway="X", model="so-texto", caps=Capabilities(tool_calling=False)),
        ModelRoute(gateway="X", model="com-tool", caps=Capabilities(tool_calling=True)),
    ])]
    router, clientes = make_router({}, catalog=cat)
    router.generate(system="s", history=[], tools=TOOLS)
    assert clientes["X"].chamadas == ["com-tool"]


# ------------------------------------------------------------------ failover
def test_falha_transitoria_vai_para_a_proxima_rota():
    router, clientes = make_router({"a1": AIError("429", user_message="limitou")})
    turno = router.generate(system="s", history=[], tools=TOOLS)
    assert turno.wants_tools
    assert router.last_route != "A/a1"
    assert router.stats.snapshot()["fallbacks"] >= 1


def test_falha_permanente_tira_a_rota_do_pool():
    """Chave recusada nao e fila: a rota morre em vez de gastar tentativa."""
    router, _ = make_router({"a1": AIError("401", user_message="chave recusada", retryable=False)})
    router.generate(system="s", history=[], tools=TOOLS)
    assert router.health.get("A/a1").state is Health.DEAD
    assert not router.health.is_available("A/a1")


def test_pool_inteiro_fora_do_ar_levanta_AIError_com_explicacao():
    erro = AIError("503", user_message="todos ocupados")
    router, _ = make_router({m: erro for m in ("a1", "a2", "b1", "c1")})
    with pytest.raises(AIError) as info:
        router.generate(system="s", history=[], tools=TOOLS)
    assert "Nenhum provedor" in info.value.user_message


def test_nao_repete_a_mesma_rota_no_mesmo_pedido():
    """Se a rota falhou neste pedido, insistir nela so queima tempo."""
    router, clientes = make_router({m: AIError("503", user_message="ocupado") for m in ("a1", "a2", "b1", "c1")})
    with pytest.raises(AIError):
        router.generate(system="s", history=[], tools=TOOLS)
    todas = sum(len(c.chamadas) for c in clientes.values())
    assert todas == 4, f"cada rota deveria ser tentada uma vez, foram {todas} chamadas"


# ------------------------------------------------------------ circuit breaker
def test_falhas_repetidas_colocam_a_rota_em_cooldown():
    agora = [0.0]
    reg = HealthRegistry(failure_threshold=3, base_cooldown=30.0, clock=lambda: agora[0])
    for _ in range(3):
        reg.record_failure("A/a1", reason="503", retryable=True)
    assert reg.get("A/a1").state is Health.COOLDOWN
    assert not reg.is_available("A/a1", now=1.0)


def test_cooldown_acaba_e_rota_volta_em_half_open():
    agora = [0.0]
    reg = HealthRegistry(failure_threshold=1, base_cooldown=30.0, clock=lambda: agora[0])
    reg.record_failure("A/a1", reason="503")
    assert not reg.is_available("A/a1", now=10.0)
    assert reg.snapshot()["A/a1"]["estado"] == "COOLDOWN"
    agora[0] = 31.0
    assert reg.is_available("A/a1", now=31.0)
    assert reg.snapshot()["A/a1"]["estado"] == "HALF_OPEN"


def test_cooldown_cresce_a_cada_queda_seguida():
    """Quem cai toda hora espera mais. Sem revive: a rota volta sozinha e cai de novo."""
    agora = [0.0]
    reg = HealthRegistry(failure_threshold=1, base_cooldown=10.0, max_cooldown=900.0,
                         dead_threshold=100, clock=lambda: agora[0])
    reg.record_failure("r", reason="503")
    primeira = reg.get("r").cooldown_seconds
    agora[0] = primeira + 1          # cooldown venceu, rota disponivel de novo
    reg.record_failure("r", reason="503")
    segunda = reg.get("r").cooldown_seconds
    assert segunda > primeira, "backoff exponencial: quem cai toda hora espera mais"


def test_revive_zera_o_backoff():
    """Reteste explicito da uma chance limpa: e diferente de esperar o cooldown."""
    reg = HealthRegistry(failure_threshold=1, base_cooldown=10.0)
    reg.record_failure("r", reason="503")
    reg.record_failure("r", reason="503")
    assert reg.get("r").trips >= 1
    reg.revive("r")
    assert reg.get("r").trips == 0
    assert reg.get("r").state is Health.HEALTHY


def test_sucesso_zera_o_historico_de_falha():
    reg = HealthRegistry(failure_threshold=5)
    reg.record_failure("r", reason="503")
    reg.record_failure("r", reason="503")
    reg.record_success("r", latency_ms=120)
    assert reg.get("r").consecutive_failures == 0
    assert reg.get("r").state is Health.HEALTHY


# ---------------------------------------------------------- carga e limites
def test_carga_se_distribui_em_vez_de_empilhar_na_primeira_rota():
    router, clientes = make_router({})
    for _ in range(6):
        router.generate(system="s", history=[], tools=TOOLS, guild_id=None)
    usadas = {r for r in router.health.all() if router.health.get(r).total_success}
    assert len(usadas) > 1, f"deveria usar mais de uma rota, usou {usadas}"


def test_peso_maior_recebe_mais_carga():
    cat = [Gateway(id="A", base_url="https://a/v1", models=[
        ModelRoute(gateway="A", model="pesada", weight=100),
        ModelRoute(gateway="A", model="leve", weight=10),
    ])]
    router, _ = make_router({}, catalog=cat)
    for _ in range(22):
        router.generate(system="s", history=[], tools=TOOLS)
    servidas = {r: router.health.get(r).total_success for r in ("A/pesada", "A/leve")}
    assert servidas["A/pesada"] > servidas["A/leve"], servidas


def test_gateway_no_limite_de_rpm_e_pulado():
    """Respeita o limite legitimo do provedor em vez de insistir."""
    agora = [0.0]
    cat = [
        Gateway(id="lento", base_url="https://l/v1", rpm=1, models=[
            ModelRoute(gateway="lento", model="l1")]),
        Gateway(id="rapido", base_url="https://r/v1", rpm=None, models=[
            ModelRoute(gateway="rapido", model="r1")]),
    ]
    router, _ = make_router({}, catalog=cat, clock=lambda: agora[0])
    router.generate(system="s", history=[], tools=TOOLS)
    assert router.last_route == "lento/l1"
    # balde esvaziou e o relogio nao andou: a proxima tem que ir para o outro
    router.cache.clear()
    router.generate(system="s", history=[{"role": "user", "parts": [{"text": "outro"}]}], tools=TOOLS)
    assert router.last_route == "rapido/r1"


def test_limite_de_concorrencia_por_rota():
    reg = HealthRegistry(concurrency_limit=1)
    reg.begin("r")
    assert not reg.is_available("r")
    reg.end("r")
    assert reg.is_available("r")


# --------------------------------------------------------------------- cache
def test_cache_nao_mistura_servidores():
    """Regra dura: mesmo pedido em guilds diferentes nao pode colidir."""
    k1 = chave_pedido(guild_id=1, system="s", history=[], tools=[])
    k2 = chave_pedido(guild_id=2, system="s", history=[], tools=[])
    assert k1 != k2


def test_cache_devolve_a_mesma_resposta_sem_chamar_de_novo():
    router, clientes = make_router({})
    h = [{"role": "user", "parts": [{"text": "mesma frase"}]}]
    router.generate(system="s", history=h, tools=TOOLS, guild_id=7)
    router.generate(system="s", history=h, tools=TOOLS, guild_id=7)
    total = sum(len(c.chamadas) for c in clientes.values())
    assert total == 1, "a segunda chamada deveria vir do cache"
    assert router.stats.snapshot()["cache_hits"] == 1


def test_mesma_frase_em_outro_servidor_nao_usa_cache():
    router, clientes = make_router({})
    h = [{"role": "user", "parts": [{"text": "mesma frase"}]}]
    router.generate(system="s", history=h, tools=TOOLS, guild_id=7)
    router.generate(system="s", history=h, tools=TOOLS, guild_id=8)
    assert sum(len(c.chamadas) for c in clientes.values()) == 2


def test_mutacao_invalida_o_cache_do_guild():
    cache = RequestCache(ttl_seconds=60)
    cache.put(7, "k1", "v1")
    cache.put(8, "k2", "v2")
    removidas = cache.invalidate_guild(7)
    assert removidas == 1
    assert cache.get(7, "k1") is None
    assert cache.get(8, "k2") == "v2", "outro servidor nao pode ser afetado"


def test_cache_expira():
    agora = [0.0]
    cache = RequestCache(ttl_seconds=5, clock=lambda: agora[0])
    cache.put(1, "k", "v")
    assert cache.get(1, "k") == "v"
    agora[0] = 6.0
    assert cache.get(1, "k") is None


def test_agente_invalida_cache_depois_de_mutacao(harness):
    """Mudou o servidor, cache velho nao serve mais - e o agente e quem avisa."""
    import asyncio

    from conftest import final, turn

    h = harness([turn(("create_role", {"name": "Novo"})), final("ok")])

    # Router de verdade como cliente do agente, mas com um cliente por gateway
    # que responde o roteiro: assim o cache em jogo e o do Router.
    roteador = Router([], backoff_seconds=0.0)
    invalidados: list[int] = []
    roteador.invalidar_guild = lambda gid: invalidados.append(gid)
    h.agent.model = roteador
    roteador.generate = lambda **kw: (
        h.model.generate(**kw)
    )

    asyncio.run(h.agent.handle("cria um cargo Novo", h.session))
    assert invalidados == [h.gateway.guild_id], \
        "o agente tem que invalidar o cache do guild depois de mutacao"


def test_so_leitura_nao_invalida_cache(harness):
    """Consultar o servidor nao muda nada; descartar cache ai seria desperdicio."""
    import asyncio

    from conftest import final, turn

    h = harness([turn(("get_server_info", {})), final("ok")])
    roteador = Router([], backoff_seconds=0.0)
    invalidados: list[int] = []
    roteador.invalidar_guild = lambda gid: invalidados.append(gid)
    roteador.generate = lambda **kw: h.model.generate(**kw)
    h.agent.model = roteador

    asyncio.run(h.agent.handle("como esta o servidor?", h.session))
    assert invalidados == [], "leitura nao pode invalidar cache"


# ------------------------------------------------------------------ metricas
def test_metricas_contam_sucesso_falha_e_fallback():
    router, _ = make_router({"a1": AIError("503", user_message="ocupado")})
    router.generate(system="s", history=[], tools=TOOLS)
    s = router.stats.snapshot()
    assert s["requests"] == 1
    assert s["sucessos"] == 1
    assert s["falhas"] == 1
    assert s["fallbacks"] >= 1
    assert s["latencia_p50_ms"] is not None


def test_painel_tem_os_numeros_pedidos():
    from atlas.ai.providers import catalog_summary
    from atlas.ai.stats import formatar_painel

    router, _ = make_router({})
    router.generate(system="s", history=[], tools=TOOLS)
    texto = formatar_painel(router.stats, router.health.snapshot(), catalog_summary(router.catalog))
    for esperado in ("POOL DE IA", "requests", "taxa de erro", "SAUDE DAS ROTAS", "latencia"):
        assert esperado in texto


# ----------------------------------------------------------------- discovery
def test_probe_classifica_rota_que_funciona():
    class OkClient:
        def generate(self, **kw):
            return ModelTurn(calls=[FunctionCall("ping", {"v": "1"}, id="x")])

    g = Gateway(id="g", base_url="https://g/v1")
    r = probe_rota(g, ModelRoute(gateway="g", model="m"), client=OkClient())
    assert r.status == ProbeStatus.OK and r.tool_calling and r.utilizavel


def test_probe_detecta_modelo_sem_tool_calling():
    class SemTool:
        def generate(self, **kw):
            return ModelTurn(text="so texto")

    g = Gateway(id="g", base_url="https://g/v1")
    r = probe_rota(g, ModelRoute(gateway="g", model="m"), client=SemTool())
    assert r.status == ProbeStatus.NO_TOOL_CALLING
    assert not r.utilizavel, "sem tool calling a rota nao serve para este agente"


def test_probe_classifica_429_como_fila():
    class Fila:
        def generate(self, **kw):
            raise AIError("429 rate limit", user_message="limitou")

    g = Gateway(id="g", base_url="https://g/v1")
    r = probe_rota(g, ModelRoute(gateway="g", model="m"), client=Fila())
    assert r.status == ProbeStatus.RATE_LIMITED
    assert not r.ok


def test_probe_classifica_chave_exigida():
    class Auth:
        def generate(self, **kw):
            raise AIError("authentication", user_message="chave recusada", retryable=False)

    g = Gateway(id="g", base_url="https://g/v1")
    r = probe_rota(g, ModelRoute(gateway="g", model="m"), client=Auth())
    assert r.status == ProbeStatus.AUTH_REQUIRED


def test_reavaliar_revive_rota_boa_e_afasta_rota_ruim():
    class Alterna:
        def __init__(self):
            self.vistos = []

        def generate(self, *, model=None, **kw):
            self.vistos.append(model)
            if model == "ruim":
                raise AIError("authentication", user_message="precisa de chave", retryable=False)
            return ModelTurn(calls=[FunctionCall("ping", {}, id="x")])

    g = Gateway(id="g", base_url="https://g/v1", models=[
        ModelRoute(gateway="g", model="bom"),
        ModelRoute(gateway="g", model="ruim"),
    ])
    reg = HealthRegistry()
    reg.record_failure("g/bom", reason="falhou antes")

    _, resultados = reavaliar(
        [g], health=reg, pausa=0, on_result=None,
        client_factory=lambda gw, rota: Alterna(),
    )
    assert reg.get("g/bom").state is Health.HEALTHY
    assert reg.get("g/ruim").state is Health.DEAD
    assert resumo_probes(resultados)["testadas"] == 2


def test_resumo_probes_conta_por_status():
    rs = [
        ProbeResult("a", ProbeStatus.OK, True, tool_calling=True),
        ProbeResult("b", ProbeStatus.RATE_LIMITED, False),
        ProbeResult("c", ProbeStatus.RATE_LIMITED, False),
    ]
    r = resumo_probes(rs)
    assert r["testadas"] == 3
    assert r["utilizaveis"] == 1
    assert r["por_status"][ProbeStatus.RATE_LIMITED] == 2


# ------------------------------------------------------------- isolamento
def test_guild_id_do_modelo_nao_vira_autorizacao():
    """O router recebe guild_id so para cache/metrica. Execucao continua no contexto."""
    router, _ = make_router({})
    # guild_id absurdo: nao pode criar rota nem cache de outro servidor
    router.generate(system="s", history=[], tools=TOOLS, guild_id=999_999)
    assert router.cache.get(123, chave_pedido(guild_id=123, system="s", history=[], tools=TOOLS)) is None


# ------------------------------------------------- concorrencia / multiusuario
def test_muitos_usuarios_simultaneos_nao_se_misturam():
    """Cada guild com seu cache; nenhuma resposta atravessa de servidor."""
    import threading

    router, clientes = make_router({})
    erros: list[str] = []
    barreia = threading.Barrier(12)

    def pedido(guild: int):
        try:
            barreia.wait(timeout=5)          # todos disparam juntos
            h = [{"role": "user", "parts": [{"text": f"pedido do guild {guild}"}]}]
            router.generate(system="s", history=h, tools=TOOLS, guild_id=guild)
        except Exception as exc:            # noqa: BLE001
            erros.append(f"guild {guild}: {exc}")

    threads = [threading.Thread(target=pedido, args=(g,)) for g in range(1, 13)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20)

    assert erros == []
    # 12 pedidos distintos = 12 chamadas reais, nenhuma servida por cache alheio
    assert sum(len(c.chamadas) for c in clientes.values()) == 12
    assert router.stats.snapshot()["requests"] == 12


def test_concorrencia_respeita_o_limite_por_gateway():
    """Duas em voo no maximo: a terceira espera a vaga, nao estoura o provedor."""
    reg = HealthRegistry(concurrency_limit=2)
    reg.begin("r"); reg.begin("r")
    assert not reg.is_available("r")
    reg.end("r")
    assert reg.is_available("r")
    assert reg.get("r").in_flight == 1


def test_cache_deduplica_pedido_repetido_do_mesmo_usuario():
    """Usuario que manda a mesma frase duas vezes nao paga duas chamadas."""
    router, clientes = make_router({})
    h = [{"role": "user", "parts": [{"text": "cria um canal geral"}]}]
    for _ in range(5):
        router.generate(system="s", history=h, tools=TOOLS, guild_id=42)
    assert sum(len(c.chamadas) for c in clientes.values()) == 1
    assert router.stats.snapshot()["cache_hits"] == 4


def test_pool_continua_funcionando_quando_um_gateway_cai_inteiro():
    """Gateway A inteiro fora: o pedido ainda sai por B ou C."""
    cat = catalogo_fake()
    router, _ = make_router({
        "a1": AIError("503", user_message="A caiu"),
        "a2": AIError("503", user_message="A caiu"),
    }, catalog=cat)
    turno = router.generate(system="s", history=[], tools=TOOLS)
    assert turno.wants_tools
    assert router.last_route.split("/")[0] in ("B", "C")


# ------------------- lacunas que a mutacao revelou (regressao obrigatoria)
def test_router_nao_escolhe_rota_em_cooldown():
    """O circuit breaker so vale se o ROUTER respeitar, nao so o registro."""
    agora = [0.0]
    reg = HealthRegistry(failure_threshold=1, base_cooldown=60.0, clock=lambda: agora[0])
    reg.record_failure("A/a1", reason="503")
    assert reg.get("A/a1").state is Health.COOLDOWN

    cat = [Gateway(id="A", base_url="https://a/v1", models=[
        ModelRoute(gateway="A", model="a1", weight=1000),   # preferida, mas em cooldown
        ModelRoute(gateway="A", model="a2", weight=1),
    ])]
    router, clientes = make_router({}, catalog=cat, health=reg, clock=lambda: agora[0])
    router.generate(system="s", history=[], tools=TOOLS)

    assert clientes["A"].chamadas == ["a2"], "a rota em cooldown nao podia ser chamada"
    assert router.last_route == "A/a2"


def test_router_pula_gateway_no_limite_mesmo_quando_ele_seria_o_preferido():
    """Isola o rpm: sem o balde, o round robin sozinho escolheria a mesma rota."""
    agora = [0.0]
    cat = [Gateway(id="apertado", base_url="https://a/v1", rpm=1, models=[
        ModelRoute(gateway="apertado", model="m1", weight=1000),
    ])]
    router, clientes = make_router({}, catalog=cat, clock=lambda: agora[0])

    router.generate(system="s", history=[], tools=TOOLS)
    assert clientes["apertado"].chamadas == ["m1"]

    # balde vazio e relogio parado: nao ha outra rota, entao tem que recusar
    # em vez de estourar o limite do provedor
    with pytest.raises(AIError):
        router.generate(
            system="s",
            history=[{"role": "user", "parts": [{"text": "outro pedido"}]}],
            tools=TOOLS,
        )
    assert clientes["apertado"].chamadas == ["m1"], "nao pode ter chamado de novo"


def test_prompt_do_probe_exige_a_ferramenta():
    """Regressao: 'responda apenas ok' fazia o modelo obedecer e a rota boa
    era descartada como 'sem tool calling' - falso negativo em 13 rotas."""
    from atlas.ai.discovery import PROMPT_PROBE

    baixo = PROMPT_PROBE.lower()
    assert "ping" in baixo, "o probe precisa nomear a ferramenta"
    assert "nao responda em texto" in baixo or "não responda em texto" in baixo


def test_catalogo_nao_tem_gateway_vazio():
    """Sem AI_* preenchido nao pode aparecer gateway 'configurado' sem rotas."""
    from atlas.config import Settings

    catalogo = build_ai_client(Settings(discord_token="t")).catalog
    vazios = [g.id for g in catalogo if not g.models]
    assert vazios == [], f"gateways sem rota no catalogo: {vazios}"
    assert all(g.id != "configurado" for g in catalogo)


# ------------------------------------- regressao: gateway limitado come o orcamento
def _catalogo_um_gateway_gordo() -> list[Gateway]:
    """Reproduz o pool real: 9 rotas no mesmo gateway (kilo) + rotas em outros.
    O limite do pool gratuito e por IP no GATEWAY, entao as 9 caem juntas."""
    gordas = [ModelRoute(gateway="G", model=f"g{i}", weight=100 - i) for i in range(9)]
    return [
        Gateway(id="G", base_url="https://g/v1", rpm=None, concurrency=2, models=gordas),
        Gateway(id="S", base_url="https://s/v1", rpm=None, concurrency=1, models=[
            ModelRoute(gateway="S", model="s1", weight=40),
        ]),
    ]


def test_gateway_limitado_nao_consome_o_orcamento_inteiro():
    """BUG REAL, medido em producao: 12,3s e 'Nenhum provedor respondeu' com 2
    rotas boas disponiveis. As 9 primeiras rotas do catalogo eram do mesmo
    gateway, que rate-limita por IP - o laco queimava max_attempts=8 ali e nunca
    chegava no outro gateway, que estava saudavel."""
    comportamento = {f"g{i}": AIError("429", user_message="limitou") for i in range(9)}
    comportamento["s1"] = "ok"

    router, _ = make_router(comportamento, catalog=_catalogo_um_gateway_gordo(),
                            max_attempts=8)
    turno = router.generate(system="s", history=[], tools=TOOLS)

    assert turno.wants_tools, "tinha que ter chegado na rota saudavel"
    assert router.last_route == "S/s1", f"parou em {router.last_route}"


def test_gateway_limitado_nao_paga_latencia_por_irma_que_vai_falhar():
    """As irmas do gateway limitado nao podem ser tentadas uma a uma: a resposta
    ja se sabe qual e. Aqui nenhuma delas deve ter sido chamada."""
    comportamento = {f"g{i}": AIError("429", user_message="limitou") for i in range(9)}
    comportamento["s1"] = "ok"

    router, clientes = make_router(comportamento, catalog=_catalogo_um_gateway_gordo(),
                                   max_attempts=8)
    router.generate(system="s", history=[], tools=TOOLS)

    chamadas_no_gordo = sum(len(c.chamadas) for c in clientes.values() if c.gateway_id == "G")
    assert chamadas_no_gordo == 1, \
        f"pagou {chamadas_no_gordo} chamadas num gateway que ja tinha dito 429"


def test_pool_de_um_gateway_unico_ainda_tenta_as_irmas():
    """Adiar nao pode virar desistir. Se o unico gateway limitou, tentar as
    irmas e melhor do que devolver erro - foi o que a primeira versao da correcao
    quebrava."""
    cat = [Gateway(id="U", base_url="https://u/v1", rpm=None, concurrency=2, models=[
        ModelRoute(gateway="U", model="u1", weight=100),
        ModelRoute(gateway="U", model="u2", weight=90),
    ])]
    router, _ = make_router({"u1": AIError("429", user_message="limitou"), "u2": "ok"},
                            catalog=cat, max_attempts=8)
    turno = router.generate(system="s", history=[], tools=TOOLS)

    assert turno.wants_tools
    assert router.last_route == "U/u2"
