"""Wiring do Discord e da camada de IA: canal de controle e conversao de historico.

Sao os dois pontos onde o codigo toca bibliotecas externas. Sem esses testes o
bot podia subir e falhar so na primeira mensagem real.
"""

from __future__ import annotations

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import discord
import pytest

from atlas.bot import CONTROL_CHANNEL_NAME, CONTROL_TOPIC_MARK, ensure_control_channel, resolve_control_channel
from atlas.ai import FailingModelClient, build_ai_client
from atlas.embeds import EmbedKind
from atlas.ai.openai_client import OpenAICompatibleClient, _parse
from atlas.ai.schema import parse_tool_arguments, to_openai_tools
from atlas.tools import build_registry


# ------------------------------------------------------------------ stubs
class FakeTextChannel:
    def __init__(self, id, name, topic=None):
        self.id = id
        self.name = name
        self.topic = topic
        self.created = None

    def __hash__(self):
        return hash(("channel", self.id))

    def __eq__(self, other):
        return isinstance(other, FakeTextChannel) and other.id == self.id


class FakeRoleTarget:
    """Fica no lugar de Role/Member como chave de overwrite (precisa ser hashable)."""

    def __init__(self, id):
        self.id = id

    def __hash__(self):
        return hash(("role", self.id))

    def __eq__(self, other):
        return isinstance(other, FakeRoleTarget) and other.id == self.id


class FakeGuild:
    def __init__(self, channels, by_id=None):
        self.text_channels = channels
        self._by_id = by_id or {c.id: c for c in channels}
        self.me = FakeRoleTarget(2)
        self.me.guild_permissions = SimpleNamespace(manage_channels=True)
        self.default_role = FakeRoleTarget(1)
        self.created_with = None

    def get_channel(self, id):
        return self._by_id.get(id)

    async def create_text_channel(self, *, name, topic, overwrites, reason):
        self.created_with = {"name": name, "topic": topic, "overwrites": overwrites, "reason": reason}
        channel = FakeTextChannel(777, name, topic)
        self.text_channels.append(channel)
        self._by_id[777] = channel
        return channel


# ------------------------------------------------------- canal de controle
def test_canal_de_controle_por_configuracao_explicita():
    alvo = FakeTextChannel(10, "qualquer-nome")
    guild = FakeGuild([alvo, FakeTextChannel(11, "geral")])
    found = resolve_control_channel(guild, configured_id=10)
    assert found is alvo


def test_canal_de_controle_por_nome_padrao():
    alvo = FakeTextChannel(10, CONTROL_CHANNEL_NAME)
    guild = FakeGuild([FakeTextChannel(11, "geral"), alvo])
    assert resolve_control_channel(guild) is alvo


def test_canal_de_controle_por_marcacao_no_topico():
    alvo = FakeTextChannel(10, "sala-da-equipe", topic=f"{CONTROL_TOPIC_MARK} configuracao")
    guild = FakeGuild([FakeTextChannel(11, "geral"), alvo])
    assert resolve_control_channel(guild) is alvo


def test_canal_comum_nao_vira_canal_de_controle():
    guild = FakeGuild([FakeTextChannel(11, "geral"), FakeTextChannel(12, "bate-papo")])
    assert resolve_control_channel(guild) is None


def test_mensagem_fora_do_canal_de_controle_nao_e_atendida():
    controle = FakeTextChannel(10, CONTROL_CHANNEL_NAME)
    outro = FakeTextChannel(12, "geral")
    guild = FakeGuild([controle, outro])
    resolved = resolve_control_channel(guild, message_channel=outro)
    assert resolved is controle
    assert resolved.id != outro.id, "mensagem em canal comum nao deveria ser processada"


def test_configuracao_explicita_inexistente_cai_no_fallback():
    alvo = FakeTextChannel(11, CONTROL_CHANNEL_NAME)
    guild = FakeGuild([alvo])
    # id configurado nao resolve; o bot deve achar o canal pelo nome em vez de desistir
    assert resolve_control_channel(guild, configured_id=999) is alvo


def test_membro_precisa_ser_hashable_para_virar_chave_de_overwrite():
    """Garante que o stub reflete o contrato real do discord.py."""
    guild = FakeGuild([FakeTextChannel(11, "geral")])
    membro = SimpleNamespace(top_role=FakeRoleTarget(55))
    asyncio.run(ensure_control_channel(guild, member=membro))
    assert guild.created_with["overwrites"][membro.top_role].view_channel is True


def test_ensure_cria_canal_privado_quando_nao_existe():
    guild = FakeGuild([FakeTextChannel(11, "geral")])
    membro = SimpleNamespace(top_role=FakeRoleTarget(55))

    channel = asyncio.run(ensure_control_channel(guild, member=membro))

    assert guild.created_with is not None, "deveria ter criado o canal"
    assert CONTROL_TOPIC_MARK in guild.created_with["topic"]
    overwrites = guild.created_with["overwrites"]
    assert overwrites[guild.default_role].view_channel is False, "@everyone nao pode ver o canal"
    assert overwrites[guild.me].view_channel is True
    assert overwrites[membro.top_role].view_channel is True
    assert channel.id == 777


def test_ensure_nao_cria_se_ja_existe():
    alvo = FakeTextChannel(10, CONTROL_CHANNEL_NAME)
    guild = FakeGuild([alvo])
    channel = asyncio.run(ensure_control_channel(guild, member=None))
    assert channel is alvo
    assert guild.created_with is None


def test_ensure_falha_sem_permissao_de_gerenciar_canais():
    from atlas.bot import ControlChannelError

    guild = FakeGuild([FakeTextChannel(11, "geral")])
    guild.me.guild_permissions.manage_channels = False
    with pytest.raises(ControlChannelError):
        asyncio.run(ensure_control_channel(guild, member=None))


# ------------------------------- set_permissions nao aceita kwargs misturados
class StrictChannel:
    """Imita o discord.py 2.7: misturar overwrite= com allow=/deny= e TypeError."""

    def __init__(self, id=1, name="geral"):
        self.id = id
        self.name = name
        self.type = discord.ChannelType.text
        self.position = 0
        self.category = None
        self.topic = None
        self.nsfw = False
        self.slowmode_delay = 0
        self.overwrites = {}
        self.calls = []

    async def set_permissions(self, target, overwrite=None, **kwargs):
        if overwrite is not None and kwargs:
            raise TypeError("Cannot mix overwrite and keyword arguments.")
        if overwrite is None and not kwargs:
            raise TypeError("Nothing to set.")
        self.calls.append({"target": target, "overwrite": overwrite, "kwargs": kwargs})
        return self


def _with_running_loop(fn):
    """Roda `fn(gateway_factory)` com o loop ativo em outra thread.

    Replica a arquitetura real: o loop do gateway roda sozinho e o nucleo
    sincrono chama de volta via run_coroutine_threadsafe.
    """
    import threading

    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    try:
        return fn(loop)
    finally:
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=5)
        loop.close()


def test_set_channel_overwrites_usa_permission_overwrite():
    """Regressao: overwrite=True + allow=/deny= quebrava com TypeError real."""
    from atlas.discord_gateway import DiscordGateway
    from atlas.models import Overwrite, Perm

    canal = StrictChannel()
    role = SimpleNamespace(id=42, name="Mod", position=1, managed=False,
                           colour=SimpleNamespace(value=0), hoist=False, mentionable=False,
                           permissions=SimpleNamespace(value=0))
    guild = SimpleNamespace(id=999, get_channel=lambda cid: canal, get_role=lambda rid: role)

    def rodar(loop):
        return DiscordGateway(guild, loop).set_channel_overwrites(
            1,
            [Overwrite(target_id=42, target_type="role",
                       allow=int(Perm.VIEW_CHANNEL), deny=int(Perm.SEND_MESSAGES))],
        )

    resultado = _with_running_loop(rodar)

    assert len(canal.calls) == 1, "deveria ter aplicado exatamente uma sobrescrita"
    chamada = canal.calls[0]
    assert chamada["kwargs"] == {}, "nenhum kwarg solto deve ser passado junto com overwrite"
    pair = chamada["overwrite"]
    assert isinstance(pair, discord.PermissionOverwrite)
    assert pair.view_channel is True
    assert pair.send_messages is False
    assert resultado.id == 1


def test_set_channel_overwrites_recusa_alvo_membro():
    from atlas.discord_gateway import DiscordGateway
    from atlas.errors import ToolError
    from atlas.models import Overwrite

    canal = StrictChannel()
    guild = SimpleNamespace(id=999, get_channel=lambda cid: canal, get_role=lambda rid: None)

    def rodar(loop):
        with pytest.raises(ToolError):
            DiscordGateway(guild, loop).set_channel_overwrites(
                1, [Overwrite(target_id=7, target_type="member")]
            )

    _with_running_loop(rodar)
    assert canal.calls == [], "nada deveria ter sido aplicado"


# ------------------------------------- discord.ChannelType nao e IntEnum (2.x)
def test_channel_type_enum_do_discord_e_convertido():
    """Regressao: discord.py 2.x usa Enum, e int() direto quebrava o snapshot."""
    from atlas.discord_gateway import DiscordGateway

    canal = SimpleNamespace(
        id=1, name="geral", type=discord.ChannelType.text, position=0,
        category=None, topic=None, nsfw=False, slowmode_delay=0, overwrites={},
    )
    convertido = DiscordGateway._channel(canal)
    assert convertido.type == 0
    assert convertido.name == "geral"


def test_channel_type_de_categoria_e_voz():
    from atlas.discord_gateway import DiscordGateway

    categoria = SimpleNamespace(
        id=2, name="INFO", type=discord.ChannelType.category, position=1,
        category=None, topic=None, nsfw=False, slowmode_delay=0, overwrites={},
    )
    voz = SimpleNamespace(
        id=3, name="Sala", type=discord.ChannelType.voice, position=0,
        category=categoria, topic=None, nsfw=False, slowmode_delay=0, overwrites={},
    )
    assert DiscordGateway._channel(categoria, is_category=True).is_category is True
    convertido_voz = DiscordGateway._channel(voz)
    assert convertido_voz.type == 2
    assert convertido_voz.parent_id == 2


@pytest.mark.parametrize(
    "valor,esperado",
    [
        (discord.ChannelType.text, 0),
        (discord.ChannelType.voice, 2),
        (discord.ChannelType.category, 4),
        (discord.ChannelType.news, 5),
        (discord.ChannelType.forum, 15),
        (0, 0),
        (15, 15),
        (None, 0),
        ("lixo", 0),
    ],
)
def test_conversao_de_tipo_de_canal_e_tolerante(valor, esperado):
    from atlas.discord_gateway import DiscordGateway

    assert DiscordGateway._channel_type_value(valor) == esperado


def test_snapshot_do_gateway_real_com_objetos_discord():
    """Exercita DiscordGateway.snapshot com o tipo real de Enum do discord.py."""
    import asyncio as _asyncio

    from atlas.discord_gateway import DiscordGateway

    categoria = SimpleNamespace(
        id=100, name="INFO", type=discord.ChannelType.category, position=0,
        category=None, topic=None, nsfw=False, slowmode_delay=0, overwrites={},
    )
    texto = SimpleNamespace(
        id=101, name="geral", type=discord.ChannelType.text, position=0,
        category=categoria, topic="topico", nsfw=False, slowmode_delay=5, overwrites={},
    )
    bot_role = SimpleNamespace(id=9, name="Atlas", position=4, managed=True,
                               colour=SimpleNamespace(value=0), hoist=False, mentionable=False,
                               permissions=SimpleNamespace(value=268435488))
    everyone = SimpleNamespace(id=1, name="@everyone", position=0, managed=False,
                               colour=SimpleNamespace(value=0), hoist=False, mentionable=False,
                               permissions=SimpleNamespace(value=1024))
    guild = SimpleNamespace(
        id=555, name="Servidor Real", owner_id=7, description="desc",
        text_channels=[texto], voice_channels=[], categories=[categoria],
        channels=[categoria, texto], roles=[bot_role, everyone],
        me=SimpleNamespace(top_role=bot_role, guild_permissions=SimpleNamespace(value=268435488)),
    )
    loop = _asyncio.new_event_loop()
    try:
        snap = DiscordGateway(guild, loop).snapshot()
    finally:
        loop.close()

    assert snap.id == 555
    assert snap.bot_role_id == 9
    assert len(snap.channels) == 2
    assert snap.find_channel(101).type == 0
    assert snap.find_channel(101).slowmode_delay == 5
    assert snap.category_channels()[0].name == "INFO"
    assert len(snap.roles) == 2


# --------------------------------------------------------- camada de IA (nova)
def _fake_response(*, text=None, tool_calls=None):
    """Monta um objeto com a mesma forma de uma resposta OpenAI."""
    calls = []
    for tc in tool_calls or []:
        calls.append(
            SimpleNamespace(
                id=tc.get("id"),
                function=SimpleNamespace(name=tc["name"], arguments=tc.get("arguments")),
            )
        )
    message = SimpleNamespace(content=text, tool_calls=calls or None)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def test_tools_sao_convertidas_para_formato_openai():
    registry = build_registry()
    tools = to_openai_tools(registry.declarations())

    assert len(tools) == len(registry.names)
    for tool in tools:
        assert tool["type"] == "function"
        assert set(tool["function"]) == {"name", "description", "parameters"}
        assert tool["function"]["parameters"]["type"] == "object"
        assert "properties" in tool["function"]["parameters"]


def test_schema_aninhado_sobrevive_a_conversao():
    registry = build_registry()
    declaration = next(d for d in registry.declarations() if d["name"] == "reorder_channels")
    tool = to_openai_tools([declaration])[0]["function"]

    items = tool["parameters"]["properties"]["items"]
    assert items["type"] == "array"
    assert items["items"]["type"] == "object"
    assert sorted(items["items"]["properties"]) == ["id", "position"]
    assert items["items"]["required"] == ["id", "position"]


def test_schema_nao_usa_tipos_maiusculos_de_outro_provedor():
    import json

    registry = build_registry()
    dumped = json.dumps(to_openai_tools(registry.declarations()))
    for tipo in ('"OBJECT"', '"STRING"', '"INTEGER"', '"BOOLEAN"', '"ARRAY"'):
        assert tipo not in dumped, f"schema ainda usa {tipo}, que nao e JSON Schema padrao"


def test_argumentos_vem_como_string_json():
    assert parse_tool_arguments('{"name": "geral"}') == {"name": "geral"}
    assert parse_tool_arguments("") == {}
    assert parse_tool_arguments(None) == {}
    assert parse_tool_arguments("nao e json") == {}
    assert parse_tool_arguments({"ja": "dict"}) == {"ja": "dict"}
    assert parse_tool_arguments("[1,2]") == {}, "lista nao e um objeto de argumentos"


def test_historico_vira_mensagens_openai_com_ids_casados():
    history = [
        {"role": "user", "parts": [{"text": "cria um canal"}]},
        {"role": "model", "parts": [{"function_call": {"id": "c1", "name": "create_channel", "args": {"name": "geral"}}}]},
        {"role": "user", "parts": [{"function_response": {"id": "c1", "name": "create_channel", "response": {"status": "ok"}}}]},
        {"role": "model", "parts": [{"text": "Pronto."}]},
    ]
    msgs = OpenAICompatibleClient.to_messages(history, system="voce e o Atlas")

    assert msgs[0] == {"role": "system", "content": "voce e o Atlas"}
    assert msgs[1] == {"role": "user", "content": "cria um canal"}

    assistant = msgs[2]
    assert assistant["role"] == "assistant"
    assert assistant["tool_calls"][0]["id"] == "c1"
    assert assistant["tool_calls"][0]["function"]["name"] == "create_channel"
    assert '"name": "geral"' in assistant["tool_calls"][0]["function"]["arguments"]

    tool_msg = msgs[3]
    assert tool_msg["role"] == "tool"
    assert tool_msg["tool_call_id"] == "c1", "resposta tem que casar com a chamada pelo id"
    assert msgs[4] == {"role": "assistant", "content": "Pronto."}


def test_historico_sem_parte_util_e_descartado():
    msgs = OpenAICompatibleClient.to_messages(
        [{"role": "user", "parts": [{"desconhecido": 1}]}], system="s"
    )
    assert msgs == [{"role": "system", "content": "s"}]


def test_parse_de_resposta_com_tool_call():
    resposta = _fake_response(tool_calls=[{"id": "x1", "name": "create_category", "arguments": '{"name": "EVENTOS"}'}])
    turn = _parse(resposta)

    assert turn.wants_tools is True
    assert turn.calls[0].name == "create_category"
    assert turn.calls[0].args == {"name": "EVENTOS"}
    assert turn.calls[0].id == "x1"


def test_parse_de_resposta_so_com_texto():
    turn = _parse(_fake_response(text="Feito."))
    assert turn.wants_tools is False
    assert turn.text == "Feito."


def test_parse_de_resposta_vazia_levanta():
    from atlas.errors import AIError

    with pytest.raises(AIError):
        _parse(_fake_response())


def test_parse_sem_choices_levanta():
    from atlas.errors import AIError

    with pytest.raises(AIError):
        _parse(SimpleNamespace(choices=[]))


def test_cliente_aceita_endpoint_anonimo():
    """Chave vazia e valida: o endpoint publico ignora o header de auth."""
    from atlas.config import NO_KEY_PLACEHOLDER

    anon = OpenAICompatibleClient(api_key="", base_url="https://x", model_name="m")
    assert anon.anonymous is True
    # o SDK nao instancia com chave vazia, entao entra um marcador de protocolo
    assert anon._client.api_key == NO_KEY_PLACEHOLDER

    com_chave = OpenAICompatibleClient(api_key="k", base_url="https://x", model_name="m")
    assert com_chave.anonymous is False
    assert com_chave._client.api_key == "k"


def test_cliente_ainda_exige_endereco_e_modelo():
    """Anonimo vale para a chave, nao para o resto."""
    from atlas.errors import AIError

    with pytest.raises(AIError):
        OpenAICompatibleClient(api_key="", base_url="", model_name="m")
    with pytest.raises(AIError):
        OpenAICompatibleClient(api_key="", base_url="https://x", model_name="")


def test_build_ai_client_sem_chave_devolve_pool_anonimo():
    """Sem nenhuma credencial o bot ainda tem uma camada de IA funcional."""
    from atlas.ai import Router
    from atlas.config import Settings

    client = build_ai_client(Settings(discord_token="t"))
    assert isinstance(client, Router)
    assert client.total_routes > 0, "o pool nao pode nascer vazio"
    # todo gateway do pool padrao e anonimo
    assert all(not g.api_key for g in client.catalog)


def test_configuracao_padrao_nao_exige_nenhuma_credencial_de_ia():
    from atlas.config import Settings

    s = Settings(discord_token="t")
    assert s.missing() == [], "so o token do Discord e obrigatorio"
    # sem default unico de proposito: quem decide e o pool anonimo
    assert s.ai_base_url == "" and s.ai_model == ""


def test_default_nao_finge_ser_configuracao_do_usuario():
    """Sem isso as rotas anonimas entrariam duas vezes no pool."""
    from atlas.config import Settings

    s = Settings(discord_token="t")
    assert s.usuario_configurou_ia is False
    assert s.ai_base_url == "", "o campo cru tem que continuar vazio"

    explicita = Settings(discord_token="t", ai_base_url="https://x/v1", ai_model="m")
    assert explicita.usuario_configurou_ia is True


def test_env_vazio_deixa_o_pool_anonimo_decidir(monkeypatch):
    """Sem AI_* preenchido, o bot nao fica sem IA: o pool assume."""
    from atlas.ai import Router
    from atlas.config import load_settings

    for k in ("AI_BASE_URL", "AI_API_KEY", "AI_MODEL"):
        monkeypatch.delenv(k, raising=False)
    s = load_settings(env_file=None, require_secrets=False)
    assert s.ai_api_key == "" and s.ai_base_url == "" and s.ai_model == ""
    assert s.usuario_configurou_ia is False

    cliente = build_ai_client(s)
    assert isinstance(cliente, Router)
    assert cliente.total_routes > 0, "pool vazio deixaria o bot sem IA"


def test_env_preenchido_vence_o_padrao(monkeypatch):
    """Quem quiser outro gateway troca tres variaveis, sem tocar no codigo."""
    from atlas.config import load_settings

    monkeypatch.setenv("AI_BASE_URL", "https://outro.gateway/v1/")
    monkeypatch.setenv("AI_API_KEY", "outra-chave")
    monkeypatch.setenv("AI_MODEL", "outro-modelo")
    s = load_settings(env_file=None, require_secrets=False)
    assert (s.ai_base_url, s.ai_model, s.ai_api_key) == (
        "https://outro.gateway/v1", "outro-modelo", "outra-chave",
    )
    c = build_ai_client(s)
    assert c.catalog[0].id == "configurado"
    assert c.catalog[0].models[0].model == "outro-modelo"
    assert c.catalog[0].api_key == "outra-chave"


def test_gateway_configurado_entra_na_frente_do_pool():
    """Preencher AI_* nao desliga o pool anonimo: vira prioridade + reserva."""
    from atlas.ai import build_catalog
    from atlas.config import Settings

    s = Settings(discord_token="t", ai_api_key="k", ai_base_url="https://gw.local/v1/", ai_model="m1,m2")
    catalogo = build_catalog(s)

    assert catalogo[0].id == "configurado"
    assert [m.model for m in catalogo[0].models] == ["m1", "m2"]
    assert catalogo[0].api_key == "k"
    assert len(catalogo) > 1, "o pool anonimo tem que continuar atras como reserva"
    assert catalogo[0].models[0].weight > catalogo[1].models[0].weight


def test_base_url_perde_a_barra_final():
    from atlas.config import load_settings

    import os

    os.environ["AI_BASE_URL"] = "https://gw.local/v1/"
    os.environ["AI_API_KEY"] = "k"
    os.environ["AI_MODEL"] = "m"
    try:
        s = load_settings(env_file=None, require_secrets=False)
        assert s.ai_base_url == "https://gw.local/v1"
    finally:
        for k in ("AI_BASE_URL", "AI_API_KEY", "AI_MODEL"):
            os.environ.pop(k, None)


def test_ensure_call_ids_sintetiza_id_faltante():
    from atlas.ai import FunctionCall, ModelTurn, ensure_call_ids

    turn = ModelTurn(calls=[FunctionCall("a", {}), FunctionCall("b", {}, id="ja-tem")])
    fixed = ensure_call_ids(turn, turn_index=2)

    assert fixed.calls[0].id == "call_t2_0"
    assert fixed.calls[1].id == "ja-tem", "id vindo do provedor nao pode ser sobrescrito"


def test_nenhum_provedor_esta_hardcoded_na_camada_de_ia():
    """O bot nao pode voltar a depender de um provedor especifico."""
    import json
    from pathlib import Path

    raiz = Path(__file__).resolve().parent.parent / "src" / "atlas"
    proibidos = ("gemini", "google-genai", "generativelanguage", "generativeai")
    achados = []
    for arquivo in raiz.rglob("*.py"):
        conteudo = arquivo.read_text(encoding="utf-8").lower()
        for termo in proibidos:
            if termo in conteudo:
                achados.append(f"{arquivo.relative_to(raiz)}: {termo}")
    assert achados == [], f"referencia a provedor antigo: {achados}"
    _ = json  # mantido para deixar explicito que a checagem e textual


def test_falha_da_camada_de_ia_vira_embed_sem_tocar_a_rede(harness):
    """Erro do provedor publico (limite, fora do ar) chega ao usuario como embed."""
    h = harness([], seed=False)
    h.agent.model = FailingModelClient("endpoint anonimo indisponivel")

    outcome = h.ask("cria um canal chamado geral")

    assert outcome.results == [], "nada pode ser executado sem o modelo planejar"
    assert len(outcome.embeds) == 1
    assert outcome.embeds[0].kind is EmbedKind.ERROR
# ------------------------------------- traducao de erro da fronteira OpenAI
def _sdk_exc(cls, status=500):
    import httpx2
    import openai

    req = httpx2.Request("POST", "https://gw/v1/chat/completions")
    res = httpx2.Response(status, request=req)
    if cls in ("APITimeoutError", "APIConnectionError"):
        return getattr(openai, cls)(request=req)
    return getattr(openai, cls)("boom", response=res, body={"error": {"message": "boom"}})


def _mensagem(exc):
    from atlas.ai.openai_client import _translate

    return _translate(exc, "meu-modelo").user_message


@pytest.mark.parametrize(
    "cls, status, esperado",
    [
        ("AuthenticationError", 401, "AI_API_KEY"),
        ("RateLimitError", 429, "limitou"),
        ("APITimeoutError", 0, "demorou"),
        ("APIConnectionError", 0, "AI_BASE_URL"),
        ("NotFoundError", 404, "meu-modelo"),
    ],
)
def test_erro_do_sdk_vira_mensagem_util(cls, status, esperado):

    assert esperado in _mensagem(_sdk_exc(cls, status))


def test_erro_http_generico_inclui_o_status():

    assert "503" in _mensagem(_sdk_exc("APIStatusError", 503))


def test_excecao_desconhecida_ainda_vira_AIError():
    from atlas.ai.openai_client import _translate
    from atlas.errors import AIError

    err = _translate(ValueError("qualquer"), "m")
    assert isinstance(err, AIError)
    assert err.user_message  # usuario nunca recebe mensagem vazia


def test_generate_envolve_falha_do_sdk_em_AIError(monkeypatch):
    """O SDK nunca vaza para fora da camada de IA."""
    from atlas.errors import AIError

    client = OpenAICompatibleClient(api_key="k", base_url="https://gw/v1", model_name="m")
    client.backoff_seconds = 0.0  # teste nao deve dormir no backoff

    def boom(**kwargs):
        raise _sdk_exc("RateLimitError", 429)

    monkeypatch.setattr(client._client.chat.completions, "create", boom)
    with pytest.raises(AIError):
        client.generate(system="s", history=[], tools=[])


def test_erro_permanente_nao_perde_tempo_tentando_de_novo(monkeypatch):
    """Chave recusada nao e fila: falha na hora, sem retry nem failover."""
    from atlas.errors import AIError

    client = OpenAICompatibleClient(api_key="k", base_url="https://gw/v1", model_name="a,b,c")
    client.backoff_seconds = 0.0
    chamadas = []

    def boom(**kwargs):
        chamadas.append(kwargs["model"])
        raise _sdk_exc("AuthenticationError", 401)

    monkeypatch.setattr(client._client.chat.completions, "create", boom)
    with pytest.raises(AIError):
        client.generate(system="s", history=[], tools=[])
    assert chamadas == ["a"], "401 nao deve passar para o proximo modelo"


def test_failover_passa_para_o_proximo_modelo_quando_o_primeiro_esta_ocupado(monkeypatch):
    """429/503 e fila, nao defeito: o proximo modelo da lista assume."""

    client = OpenAICompatibleClient(api_key="", base_url="https://gw/v1", model_name="ocupado,bom")
    client.backoff_seconds = 0.0
    vistos = []

    def create(**kwargs):
        vistos.append(kwargs["model"])
        if kwargs["model"] == "ocupado":
            raise _sdk_exc("RateLimitError", 429)
        return _fake_response(text="respondeu o segundo")

    monkeypatch.setattr(client._client.chat.completions, "create", create)
    turno = client.generate(system="s", history=[], tools=[])

    assert turno.text == "respondeu o segundo"
    assert client.last_model == "bom"
    assert vistos[0] == "ocupado" and "bom" in vistos


def test_lista_de_modelos_vem_da_configuracao():
    c = OpenAICompatibleClient(api_key="", base_url="https://gw/v1", model_name=" um , dois ,tres ")
    assert c.models == ["um", "dois", "tres"]
    assert c.model_name == "um"


def test_lista_de_modelos_vazia_levanta():
    from atlas.errors import AIError

    with pytest.raises(AIError):
        OpenAICompatibleClient(api_key="", base_url="https://gw/v1", model_name=" , , ")


def test_pool_tem_rotas_em_mais_de_um_gateway_para_failover():
    """Depender de um gateway so derruba o bot quando ele oscila."""
    from atlas.config import Settings

    catalogo = build_ai_client(Settings(discord_token="t")).catalog
    gateways = {g.id for g in catalogo}
    assert len(gateways) >= 2, f"precisa de ao menos dois gateways, ha {gateways}"
    assert sum(len(g.models) for g in catalogo) >= 4, "poucas rotas = pouco failover"


# --------------------------------------------------------- ponta a ponta HTTP
class _StubOpenAIHandler(BaseHTTPRequestHandler):
    """Gateway OpenAI-compativel minimo, roda de verdade em HTTP local."""

    recebido = None

    def do_POST(self):  # noqa: N802 - nome exigido pelo BaseHTTPRequestHandler
        corpo = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        type(self).recebido = {
            "path": self.path,
            "auth": self.headers.get("Authorization"),
            "body": json.loads(corpo),
        }
        payload = {
            "id": "chatcmpl-1",
            "object": "chat.completion",
            "model": self.recebido["body"].get("model"),
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "tool_calls",
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_srv_1",
                                "type": "function",
                                "function": {
                                    "name": "create_channel",
                                    "arguments": '{"name": "geral", "type": "text"}',
                                },
                            }
                        ],
                    },
                }
            ],
        }
        bruto = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(bruto)))
        self.end_headers()
        self.wfile.write(bruto)

    def log_message(self, *args):  # silencia o log do servidor
        pass


def test_ponta_a_ponta_payload_real_no_fio():
    """O cliente realmente fala o protocolo OpenAI por HTTP."""
    servidor = ThreadingHTTPServer(("127.0.0.1", 0), _StubOpenAIHandler)
    porta = servidor.server_address[1]
    linha = threading.Thread(target=servidor.serve_forever, daemon=True)
    linha.start()
    try:
        client = OpenAICompatibleClient(
            api_key="chave-de-teste",
            base_url=f"http://127.0.0.1:{porta}/v1",
            model_name="modelo-teste",
            timeout=10,
        )
        historico = [
            {"role": "user", "parts": [{"text": "cria um canal chamado geral"}]},
        ]
        turno = client.generate(
            system="Voce e o Atlas.",
            history=historico,
            tools=build_registry().declarations(),
        )
    finally:
        servidor.shutdown()
        servidor.server_close()

    req = _StubOpenAIHandler.recebido
    assert req is not None, "o servidor nao recebeu nada"
    assert req["path"] == "/v1/chat/completions"
    assert req["auth"] == "Bearer chave-de-teste"

    corpo = req["body"]
    assert corpo["model"] == "modelo-teste"
    assert corpo["messages"][0]["role"] == "system"
    assert corpo["messages"][1]["content"] == "cria um canal chamado geral"
    assert corpo["tools"][0]["type"] == "function"
    assert corpo["tools"][0]["function"]["name"] == "get_server_info"
    assert len(corpo["tools"]) == 21, "todas as ferramentas tem que ir no request"

    assert turno.calls[0].name == "create_channel"
    assert turno.calls[0].args == {"name": "geral", "type": "text"}
    assert turno.calls[0].id == "call_srv_1", "id vindo do gateway tem que ser preservado"


def test_ponta_a_ponta_resposta_de_texto():
    """Segunda rodada: o gateway responde texto puro e o agente encerra."""
    class _TextoHandler(_StubOpenAIHandler):
        def do_POST(self):  # noqa: N802
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            bruto = json.dumps(
                {
                    "choices": [
                        {
                            "index": 0,
                            "finish_reason": "stop",
                            "message": {"role": "assistant", "content": "Pronto, canal criado."},
                        }
                    ]
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(bruto)))
            self.end_headers()
            self.wfile.write(bruto)

    servidor = ThreadingHTTPServer(("127.0.0.1", 0), _TextoHandler)
    porta = servidor.server_address[1]
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    try:
        client = OpenAICompatibleClient(
            api_key="k", base_url=f"http://127.0.0.1:{porta}/v1", model_name="m"
        )
        turno = client.generate(system="s", history=[], tools=[])
    finally:
        servidor.shutdown()
        servidor.server_close()

    assert turno.wants_tools is False
    assert turno.text == "Pronto, canal criado."


def test_ponta_a_ponta_erro_http_vira_AIError():
    """Gateway devolvendo 401 tem que virar AIError com orientacao, nao traceback."""
    from atlas.errors import AIError

    class _Erro401Handler(_StubOpenAIHandler):
        def do_POST(self):  # noqa: N802
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            bruto = b'{"error":{"message":"chave invalida"}}'
            self.send_response(401)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(bruto)))
            self.end_headers()
            self.wfile.write(bruto)

    servidor = ThreadingHTTPServer(("127.0.0.1", 0), _Erro401Handler)
    porta = servidor.server_address[1]
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    try:
        client = OpenAICompatibleClient(
            api_key="errada", base_url=f"http://127.0.0.1:{porta}/v1", model_name="m"
        )
        with pytest.raises(AIError) as info:
            client.generate(system="s", history=[], tools=[])
    finally:
        servidor.shutdown()
        servidor.server_close()

    assert "AI_API_KEY" in info.value.user_message


def test_descricao_das_ferramentas_chega_ao_modelo():
    """O modelo escolhe a ferramenta pela descricao; se ela for vazia, ele chuta."""
    registry = build_registry()
    tools = {t["function"]["name"]: t["function"] for t in to_openai_tools(registry.declarations())}

    assert set(tools) == set(registry.names)
    vazias = [nome for nome, f in tools.items() if not f["description"].strip()]
    assert vazias == [], f"ferramentas sem descricao: {vazias}"

    # a descricao tem que ser a do registro, nao algo gerico
    original = {d["name"]: d.get("description", "") for d in registry.declarations()}
    divergentes = [n for n in tools if tools[n]["description"] != original[n]]
    assert divergentes == [], f"descricao alterada na conversao: {divergentes}"


def test_nome_das_ferramentas_e_preservado_na_conversao():
    registry = build_registry()
    convertidos = {t["function"]["name"] for t in to_openai_tools(registry.declarations())}
    assert convertidos == set(registry.names)


# ------------------------------------------------- retry/failover por status
def test_503_e_transitorio_e_vai_para_o_proximo_modelo(monkeypatch):
    """'Model temporarily busy' e 503 - o caso mais comum em endpoint gratuito."""
    client = OpenAICompatibleClient(api_key="", base_url="https://gw/v1", model_name="ocupado,livre")
    client.backoff_seconds = 0.0
    vistos = []

    def create(**kwargs):
        vistos.append(kwargs["model"])
        if kwargs["model"] == "ocupado":
            raise _sdk_exc("APIStatusError", 503)
        return _fake_response(text="ok do segundo")

    monkeypatch.setattr(client._client.chat.completions, "create", create)
    turno = client.generate(system="s", history=[], tools=[])

    assert turno.text == "ok do segundo"
    assert client.last_model == "livre"


@pytest.mark.parametrize("status", [408, 409, 425, 429, 500, 502, 503, 504])
def test_status_transitorio_e_reconhecido(status):
    from atlas.ai.openai_client import _is_retryable

    assert _is_retryable(_sdk_exc("APIStatusError", status)) is True


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
def test_status_permanente_nao_e_retentado(status):
    """Chave ruim, modelo inexistente ou payload invalido nao se resolvem insistindo."""
    from atlas.ai.openai_client import _is_retryable

    exc = _sdk_exc("NotFoundError" if status == 404 else "APIStatusError", status)
    assert _is_retryable(exc) is False


def test_esgota_todos_os_modelos_antes_de_desistir(monkeypatch):
    """Se nenhum modelo responde, o usuario recebe AIError - nao silencio."""
    from atlas.errors import AIError

    client = OpenAICompatibleClient(api_key="", base_url="https://gw/v1", model_name="a,b")
    client.backoff_seconds = 0.0
    client.max_attempts_per_model = 2
    vistos = []

    def create(**kwargs):
        vistos.append(kwargs["model"])
        raise _sdk_exc("APIStatusError", 503)

    monkeypatch.setattr(client._client.chat.completions, "create", create)
    with pytest.raises(AIError):
        client.generate(system="s", history=[], tools=[])
    assert vistos == ["a", "a", "b", "b"], "deve esgotar as tentativas de cada modelo"


def test_prompt_orienta_a_nao_duplicar_o_que_ja_existe():
    """Modelo pequeno duplica categoria se o prompt nao mandar olhar antes."""
    from atlas.policy import ActionBudget, Policy
    from atlas.prompts import build_system_prompt
    from atlas.testing.fake_gateway import FakeGateway
    from atlas.tools import build_registry

    gw = FakeGateway()
    gw.seed_gamer_layout()
    snap = gw.snapshot()
    policy = Policy(
        guild_id=gw.guild_id,
        budget=ActionBudget(max_actions=60, max_creates=40, max_deletes=25),
    )
    texto = build_system_prompt(snap, build_registry(), policy)

    # Frases exatas: as palavras soltas tambem aparecem em outras partes do
    # prompt (lista de ferramentas, por exemplo), entao so a frase completa
    # garante que a orientacao esta mesmo ali.
    assert "chame get_categories e get_channels" in texto, \
        "o prompt precisa mandar listar categorias antes de criar"
    assert "Nao crie o que ja existe." in texto, \
        "o prompt precisa proibir duplicata explicitamente"
    assert "so voce evita a duplicata" in texto, \
        "o prompt precisa explicar que o Discord nao impede nome repetido"


# ------------------------------------------------- autorizacao por mencao
def test_mencao_autoriza_canal_fora_do_controle():
    """Chamar o bot em outro canal tem que funcionar, nao ficar em silencio."""
    from atlas.bot import mensagem_autorizada

    controle = FakeTextChannel(10, "atlas-config")
    outro = FakeTextChannel(11, "bate-papo")
    assert mensagem_autorizada(control=controle, message_channel=outro, mencionado=True) is True


def test_sem_mencao_fora_do_controle_e_ignorada():
    from atlas.bot import mensagem_autorizada

    controle = FakeTextChannel(10, "atlas-config")
    outro = FakeTextChannel(11, "bate-papo")
    assert mensagem_autorizada(control=controle, message_channel=outro, mencionado=False) is False


def test_dentro_do_controle_nao_precisa_de_mencao():
    from atlas.bot import mensagem_autorizada

    controle = FakeTextChannel(10, "atlas-config")
    assert mensagem_autorizada(control=controle, message_channel=controle, mencionado=False) is True


def test_sem_canal_de_controle_mencao_ainda_funciona():
    """Servidor novo sem canal configurado: mencionar o bot tem que atender."""
    from atlas.bot import mensagem_autorizada

    canal = FakeTextChannel(11, "geral")
    assert mensagem_autorizada(control=None, message_channel=canal, mencionado=True) is True
    assert mensagem_autorizada(control=None, message_channel=canal, mencionado=False) is False
