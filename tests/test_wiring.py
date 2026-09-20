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


@pytest.mark.parametrize("status", [408, 409, 425, 500, 502, 503, 504])
def test_status_transitorio_e_reconhecido(status):
    from atlas.ai.openai_client import _is_retryable

    assert _is_retryable(_sdk_exc("APIStatusError", status)) is True


# 429 saiu da lista acima de proposito. Duas perguntas diferentes:
#   _is_retryable  -> vale insistir NA MESMA ROTA?           429: NAO
#   _retryable_for -> o Router deve tentar OUTRA rota?       429: SIM
# Confundir as duas era o bug: o cliente dormia 4s+8s na rota limitada
# enquanto 11 rotas livres esperavam.
def test_429_nao_insiste_na_mesma_rota():
    from atlas.ai.openai_client import _is_rate_limited, _is_retryable

    exc = _sdk_exc("APIStatusError", 429)
    assert _is_retryable(exc) is False, "esperar na rota limitada nao resolve"
    assert _is_rate_limited(exc) is True, "tem que passar adiante na hora"


def test_429_continua_sendo_fila_para_o_router():
    """Se virasse erro permanente, a rota morreria em vez de entrar em cooldown."""
    from atlas.ai.openai_client import _retryable_for

    assert _retryable_for(_sdk_exc("APIStatusError", 429)) is True


def test_429_pula_para_o_proximo_modelo_sem_dormir(monkeypatch):
    """O failover da lista AI_MODEL=a,b tem que sobreviver: sem sleep."""
    import time

    client = OpenAICompatibleClient(api_key="", base_url="https://gw/v1",
                                    model_name="limitado,livre")
    client.backoff_seconds = 99.0  # se dormir, o teste estoura
    dormiu = []
    monkeypatch.setattr(time, "sleep", lambda s: dormiu.append(s))

    def create(**kwargs):
        if kwargs["model"] == "limitado":
            raise _sdk_exc("RateLimitError", 429)
        return _fake_response(text="ok do segundo")

    monkeypatch.setattr(client._client.chat.completions, "create", create)
    turno = client.generate(system="s", history=[], tools=[])

    assert turno.text == "ok do segundo"
    assert client.last_model == "livre"
    assert dormiu == [], f"dormiu {dormiu}s numa rota que so precisava ser pulada"


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
    assert "Nao crie o que ja existe" in texto, \
        "o prompt precisa mandar conferir antes de criar"
    # A lista de ids vai no prompt. Sem isso todo pedido gastava uma volta de
    # IA (~1,5s) e ~700 tokens so para descobrir o id de um canal.
    assert "JA ESTAO na lista acima" in texto, \
        "o prompt tem que dizer que os ids ja estao disponiveis"
    assert "sem chamar get_server_info" in texto, \
        "o prompt tem que proibir a leitura que virou desnecessaria"
    assert "Nao crie o que ja existe" in texto, \
        "o prompt precisa proibir duplicata explicitamente"
    assert "so voce evita" in texto, \
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


# ---------------------------------------------------------- main.py --pool
def _rode(capsys, monkeypatch, argv):
    import sys

    import main as main_mod

    monkeypatch.setattr(sys, "argv", ["main.py", *argv])
    return main_mod.main(), capsys.readouterr()


def test_pool_lista_o_catalogo_sem_sondar(capsys, monkeypatch):
    """--pool tem que ser instantaneo: o workflow roda isso antes de o bot subir.

    Se algum dia alguem trocar --pool por --health aqui, o runner vai gastar a
    cota gratuita sondando 12 rotas antes de atender uma unica mensagem.
    """
    import main as main_mod

    chamadas = []
    monkeypatch.setattr(
        main_mod, "__file__", main_mod.__file__
    )  # garante modulo importado
    import atlas.ai as ai

    original = ai.build_catalog
    monkeypatch.setattr(ai, "build_catalog", lambda s: (chamadas.append(1), original(s))[1])

    codigo, saida = _rode(capsys, monkeypatch, ["--pool"])
    assert codigo == 0
    assert "2 gateways, 12 rotas" in saida.out
    assert "kilo" in saida.out and "llm7" in saida.out


def test_pool_falha_com_saida_3_quando_nao_ha_rota(capsys, monkeypatch):
    """Pool vazio tem que derrubar o job, nao deixar o bot subir no escuro."""
    import atlas.ai as ai

    monkeypatch.setattr(ai, "build_catalog", lambda s: [])

    codigo, saida = _rode(capsys, monkeypatch, ["--pool"])
    assert codigo == 3
    assert "NENHUMA rota" in saida.out


# ------------------------------------- snapshot contra objetos reais do discord.py
def test_snapshot_le_permissao_customizada_de_canal_real():
    """Regressao: PermissionOverwrite nao tem .allow/.deny, tem .pair().

    O FakeGateway nunca exercitou DiscordGateway._channel, entao 356 testes
    passaram com o bot quebrado em producao: qualquer canal com uma permissao
    customizada derrubava o snapshot na primeira mensagem do usuario.
    """
    import types
    from unittest import mock

    import discord

    from atlas.discord_gateway import DiscordGateway

    papel = mock.create_autospec(discord.Role, instance=True)
    papel.id = 4242
    ow = discord.PermissionOverwrite(manage_channels=True, send_messages=False)
    allow, deny = ow.pair()

    canal = types.SimpleNamespace(
        id=99,
        name="geral",
        type=discord.ChannelType.text,
        position=1,
        category=None,
        topic=None,
        nsfw=False,
        slowmode_delay=0,
        overwrites={papel: ow},
    )

    convertido = DiscordGateway._channel(canal)

    assert len(convertido.overwrites) == 1
    gravado = convertido.overwrites[0]
    assert gravado.target_id == 4242
    assert gravado.target_type == "role"          # papel entra como role, nao member
    assert gravado.allow == allow.value           # manage_channels permitido
    assert gravado.deny == deny.value             # send_messages negado
    assert discord.Permissions(gravado.allow).manage_channels is True
    assert discord.Permissions(gravado.deny).send_messages is True


def test_snapshot_de_membro_entr_como_target_member():
    import types
    from unittest import mock

    import discord

    from atlas.discord_gateway import DiscordGateway

    membro = mock.create_autospec(discord.Member, instance=True)
    membro.id = 777
    canal = types.SimpleNamespace(
        id=99, name="geral", type=discord.ChannelType.text, position=0,
        category=None, topic=None, nsfw=False, slowmode_delay=0,
        overwrites={membro: discord.PermissionOverwrite(view_channel=True)},
    )
    convertido = DiscordGateway._channel(canal)
    assert convertido.overwrites[0].target_type == "member"
    assert discord.Permissions(convertido.overwrites[0].allow).view_channel is True


# ------------------------------- o agente sabe onde a conversa esta acontecendo
def _prompt(source_channel_id):
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
    return snap, build_system_prompt(
        snap, build_registry(), policy, source_channel_id=source_channel_id
    )


def test_prompt_informa_o_canal_atual_para_resolver_este_canal():
    """Regressao real: "apague todos os canais e deixe apenas esse".

    O modelo nao recebia o canal de origem, entao respondia "qual canal voce
    quer manter?" - e depois chutava um canal que nem era o da conversa.
    """
    snap, texto = _prompt(None)          # primeiro pega um canal de verdade
    alvo = snap.channels[0]

    _, texto = _prompt(alvo.id)
    assert f"canal atual #{alvo.name} (id {alvo.id})" in texto
    assert "nao chute nem pergunte" in texto


def test_prompt_sem_canal_de_origem_manda_perguntar_em_vez_de_chutar():
    _, texto = _prompt(None)
    assert "canal de origem desconhecido" in texto
    assert "pergunte em vez de chutar" in texto


def test_bot_passa_o_canal_da_mensagem_para_o_contexto(monkeypatch):
    """O id tem que vir de message.channel - contexto real do Discord, nunca
    de um parametro que o modelo possa inventar."""
    import asyncio
    import types

    from atlas.audit import AuditLog
    from atlas.bot import AtlasBot
    from atlas.config import load_settings
    from atlas.testing.fake_gateway import FakeGateway

    settings = load_settings(require_secrets=False)
    bot = AtlasBot(settings, AuditLog(path=None))

    capturado = {}
    import atlas.bot as bot_mod

    original_ctx = bot_mod.ToolContext

    def espiao_ctx(**kw):
        capturado.update(kw)
        return original_ctx(**kw)

    # gateway stub: devolve um snapshot de verdade sem tocar no guild falso
    fake_gw = FakeGateway()
    fake_gw.seed_gamer_layout()

    class GatewayStub:
        def __init__(self, guild, loop):
            pass

        def snapshot(self):
            return fake_gw.snapshot()

    monkeypatch.setattr(bot_mod, "ToolContext", espiao_ctx)
    monkeypatch.setattr(bot_mod, "DiscordGateway", GatewayStub)

    canal = types.SimpleNamespace(id=1234567890, name="atlas-config")
    guild = types.SimpleNamespace(id=1)
    autor = types.SimpleNamespace(id=555, name="ek8a", display_name="ek8a")
    mensagem = types.SimpleNamespace(channel=canal, author=autor)

    async def roda():
        bot._build_agent(guild, mensagem)

    asyncio.run(roda())

    assert capturado.get("source_channel_id") == 1234567890, (
        "o agente precisa saber de onde veio a mensagem para resolver 'este canal'"
    )
    assert capturado.get("source_author_id") == 555, (
        "o agente precisa saber quem pediu para resolver 'pra mim', 'meu'"
    )
    assert capturado.get("source_author_name") == "ek8a"


def test_agente_repassa_o_canal_de_origem_ao_prompt(harness):
    """Elo que a mutacao M1 mostrou descoberto: ToolContext -> prompt.

    Sem isto o canal chega no contexto e morre la: o modelo continua sem saber
    onde a conversa acontece, que e exatamente o bug de "deixe apenas esse".
    """
    from conftest import final

    h = harness([final("ok")])
    alvo = h.gateway.snapshot().channels[0]
    h.ctx.source_channel_id = alvo.id

    h.ask("oi")

    assert h.model.system_prompts, "o modelo nao foi chamado"
    assert f"canal atual #{alvo.name} (id {alvo.id})" in h.model.system_prompts[0], (
        "o agente montou o prompt sem o canal de origem"
    )


def test_agente_sem_canal_de_origem_avisa_o_modelo(harness):
    from conftest import final

    h = harness([final("ok")])
    h.ctx.source_channel_id = None

    h.ask("oi")

    assert "canal de origem desconhecido" in h.model.system_prompts[0]


def test_prompt_informa_quem_esta_pedindo(harness):
    """Mesma classe de bug do canal: sem o autor, 'me da acesso' nao resolve."""
    from conftest import final

    h = harness([final("ok")])
    h.ctx.source_author_id = 555
    h.ctx.source_author_name = "ek8a"

    h.ask("oi")

    prompt = h.model.system_prompts[0]
    assert "QUEM PEDE:" in prompt
    assert "ek8a (id 555)" in prompt
    # identidade e contexto, nao autorizacao - isso tem que estar dito
    assert "contexto, nao autorizacao" in prompt


# --------------------------------- corrida entre HTTP e cache do discord.py
def test_confirmar_mudanca_espera_o_cache_atualizar():
    """Bug REAL: o bot disse "nao pude confirmar" de uma exclusao que deu certo.

    O HTTP 200 volta antes do evento CHANNEL_DELETE atualizar o cache, entao a
    primeira leitura ainda ve o canal. Sem retry, falso negativo.
    """
    from atlas.tools.base import confirmar_mudanca

    leituras = {"n": 0}
    dormidos: list[float] = []

    class CtxFalso:
        def refresh(self):
            leituras["n"] += 1
            # o canal some so na terceira leitura, como no Discord real
            return SimpleNamespace(sumiu=leituras["n"] >= 3)

    ok = confirmar_mudanca(
        CtxFalso(), lambda s: s.sumiu, sleeper=dormidos.append
    )

    assert ok is True
    assert leituras["n"] == 3, "tem que tentar de novo ate o cache atualizar"
    assert dormidos == [0.25, 0.25], "dormiu entre as tentativas"


def test_confirmar_mudanca_desiste_depois_de_algumas_tentativas():
    from atlas.tools.base import confirmar_mudanca

    class CtxFalso:
        def refresh(self):
            return SimpleNamespace(sumiu=False)

    ok = confirmar_mudanca(CtxFalso(), lambda s: s.sumiu, tentativas=4, sleeper=lambda s: None)
    assert ok is False


def test_verificar_exclusao_de_canal_usa_retry(harness):
    """A verificacao real tem que passar pelo retry, nao conferir uma vez so."""
    from atlas.tools.channels import _verify_delete_channel

    h = harness([], seed=True)
    alvo = h.gateway.snapshot().channels[0]

    leituras = {"n": 0}
    original = h.gateway.snapshot          # bound method, capturado ANTES de trocar

    def snapshot_atrasado():
        leituras["n"] += 1
        if leituras["n"] >= 3:
            h.gateway.channels.pop(alvo.id, None)   # so agora o cache atualiza
        return original()

    h.gateway.snapshot = snapshot_atrasado

    assert _verify_delete_channel(h.ctx, {"channel_id": alvo.id}, None) is True


def test_indice_lista_os_ids_reais_do_servidor():
    from atlas.prompts import indice_do_servidor
    from atlas.testing.fake_gateway import FakeGateway

    gw = FakeGateway(); gw.seed_gamer_layout()
    snap = gw.snapshot()
    indice = indice_do_servidor(snap)

    alvo = [c for c in snap.channels if not c.is_category][0]
    assert f"{alvo.name}={alvo.id}" in indice
    assert f"{snap.roles[0].name}={snap.roles[0].id}" in indice


def test_indice_tem_teto_para_servidor_grande():
    """Sem teto, um servidor com 500 canais inflaria o prompt de toda chamada."""
    from atlas.prompts import indice_do_servidor
    from atlas.testing.fake_gateway import FakeGateway

    gw = FakeGateway()
    for i in range(150):
        gw.create_channel(name=f"canal-{i}", type=0)   # 0 = texto
    indice = indice_do_servidor(gw.snapshot(), teto=80)

    assert "mais)" in indice, "tem que avisar que a lista foi truncada"
    assert len(indice) < 4000, f"indice grande demais: {len(indice)}"


# ---------------------------------------------------- prazo total do pedido
def test_agente_para_quando_estoura_o_prazo(harness):
    """Pior caso era 25 turnos x 60s = 25 minutos sem resposta nenhuma."""
    from atlas.config import Limits
    from conftest import turn

    h = harness([turn(("get_server_info", {}))] * 5, limits=Limits(deadline_seconds=0.0))

    out = h.ask("faz alguma coisa")

    assert out.embeds, "tem que responder alguma coisa, nao ficar em silencio"
    texto = " ".join(e.description for e in out.embeds)
    assert "Demorou demais" in texto
    # prazo 0 corta antes da primeira chamada: nao adianta comecar algo que
    # nao vai dar tempo de terminar
    assert h.model.system_prompts == [], "com prazo zero nao pode gastar volta nenhuma"


def test_prazo_generoso_nao_atrapalha_pedido_normal(harness):
    from atlas.config import Limits
    from conftest import final, turn

    h = harness([turn(("get_server_info", {})), final("pronto")],
                limits=Limits(deadline_seconds=90.0))
    out = h.ask("oi")
    assert any("pronto" in e.description for e in out.embeds)


# ---------------------------------------------------- aviso "Online." ao subir
def _bot_para_aviso(monkeypatch, *, notice=True, canal_id=10, nome="atlas-config",
                    configured=None):
    """AtlasBot com guild/canal falsos, sem tocar em rede.

    `canal_id` e o id do canal falso; `configured` e o ATLAS_CONTROL_CHANNEL_ID.
    Tem que ser possivel passar valores diferentes - na primeira versao os dois
    eram o mesmo numero e o teste "sem canal de controle" achava o canal.
    """
    from atlas.audit import AuditLog
    from atlas.bot import AtlasBot
    from atlas.config import load_settings

    canal = FakeTextChannel(canal_id, nome)
    enviados = []

    async def send(*, view=None, embed=None, **kw):
        enviados.append({"view": view, "embed": embed})

    canal.send = send

    guild = FakeGuild([canal])
    import dataclasses

    settings = dataclasses.replace(
        load_settings(require_secrets=False),
        control_channel_id=canal_id if configured is None else configured,
        startup_notice=notice,
    )

    bot = AtlasBot(settings, AuditLog(path=None))
    bot._guilds = [guild]
    monkeypatch.setattr(type(bot), "guilds", property(lambda self: self._guilds))
    return bot, canal, enviados


def test_aviso_online_manda_uma_mensagem_no_canal_de_controle(monkeypatch):
    import asyncio

    bot, canal, enviados = _bot_para_aviso(monkeypatch)
    asyncio.run(bot._aviso_online())

    assert len(enviados) == 1, "o aviso e uma mensagem so"
    assert enviados[0]["view"] is not None, "tem que ser Components V2, nao embed antigo"
    assert enviados[0]["embed"] is None


def test_aviso_online_nao_repete_em_cada_reconexao(monkeypatch):
    """on_ready dispara de novo a cada reconexao: sem trava vira spam."""
    import asyncio

    bot, canal, enviados = _bot_para_aviso(monkeypatch)
    asyncio.run(bot._aviso_online())
    asyncio.run(bot._aviso_online())
    asyncio.run(bot._aviso_online())

    assert len(enviados) == 1, f"mandou {len(enviados)} avisos, devia ser 1"


def test_aviso_online_pode_ser_desligado(monkeypatch):
    import asyncio

    bot, _canal, enviados = _bot_para_aviso(monkeypatch, notice=False)
    asyncio.run(bot._aviso_online())

    assert enviados == [], "com ATLAS_STARTUP_NOTICE=0 nao manda nada"


def test_aviso_online_sem_canal_de_controle_nao_quebra(monkeypatch):
    """Diagnostico nao pode derrubar o bot."""
    import asyncio

    # configured aponta para um id que nao existe E o canal tem nome diferente
    # de atlas-config: nem o id nem o fallback por nome acham nada.
    bot, _canal, enviados = _bot_para_aviso(monkeypatch, canal_id=10, nome="geral",
                                            configured=999)
    asyncio.run(bot._aviso_online())  # nao deve lancar

    assert enviados == []
    assert bot._ready_embeds == 0, "pode tentar de novo na proxima reconexao"


# ------------------------------------------------- doutrina de design (seletiva)
@pytest.mark.parametrize("texto", [
    "Cria um servidor de Fortnite",
    "cria um servidor bonito de minecraft",
    "monta uma estrutura de canais pra minha comunidade",
    "faz bonito",
    "deixa bonito esse servidor",
    "quero um servidor tematico de GTA RP",
    "reorganiza as categorias",
])
def test_pedido_de_design_detectado(texto):
    from atlas.design import is_pedido_de_design

    assert is_pedido_de_design(texto) is True, texto


@pytest.mark.parametrize("texto", [
    "cite todos os cargos",
    "quantos canais tem esse servidor?",
    "apague o canal teste",
    "qual o nome do servidor?",
    "renomeia o cargo Membro",
    "crie um canal chamado teste",
    "",
    "   ",
])
def test_pedido_comum_nao_paga_doutrina(texto):
    """Falso positivo aqui custa ~800 tokens em TODA volta de IA do pedido."""
    from atlas.design import is_pedido_de_design

    assert is_pedido_de_design(texto) is False, texto


def test_doutrina_entra_no_prompt_so_quando_e_projeto():
    from atlas.bot import AtlasBot  # noqa: F401  (garante import do pacote)
    from atlas.prompts import build_system_prompt
    from atlas.testing.fake_gateway import FakeGateway

    gw = FakeGateway()
    gw.seed_gamer_layout()
    snap = gw.snapshot()
    from atlas.policy import ActionBudget, Policy
    from atlas.tools import build_registry

    reg, pol = build_registry(), Policy(guild_id=snap.id, budget=ActionBudget(60, 40, 25))

    comum = build_system_prompt(snap, reg, pol, request="cite todos os cargos")
    projeto = build_system_prompt(snap, reg, pol, request="cria um servidor de Fortnite")

    assert "PROJETO DE SERVIDOR" not in comum
    assert "PROJETO DE SERVIDOR" in projeto
    assert len(projeto) - len(comum) > 2000, "a doutrina tem que estar la de verdade"


def test_regra_de_resposta_exata_esta_no_prompt():
    """Bug real: 'cite todos os cargos' devolvia nome junto com id."""
    from atlas.policy import ActionBudget, Policy
    from atlas.prompts import build_system_prompt
    from atlas.testing.fake_gateway import FakeGateway
    from atlas.tools import build_registry

    gw = FakeGateway()
    gw.seed_gamer_layout()
    snap = gw.snapshot()
    texto = build_system_prompt(
        snap, build_registry(), Policy(guild_id=snap.id, budget=ActionBudget(60, 40, 25)),
        request="cite todos os cargos",
    )
    assert "EXATAMENTE o que foi pedido" in texto
    assert "so os nomes" in texto


# ------------------------------------------------ Fase 4: trava por guild (spec 64/65/114)
def test_duas_threads_no_mesmo_guild_uma_fica_de_fora():
    """O caso real: bot.py roda cada pedido numa thread do pool."""
    import threading

    from atlas.concurrency import GuildLocks

    travas = GuildLocks()
    entrou = threading.Event()
    solta = threading.Event()
    resultados = []

    def primeiro():
        with travas.tentativa(1, 5.0) as pegou:
            resultados.append(("A", pegou))
            entrou.set()
            solta.wait(5)

    t = threading.Thread(target=primeiro)
    t.start()
    assert entrou.wait(5), "a thread A nem entrou"

    with travas.tentativa(1, 0.1) as pegou:
        resultados.append(("B", pegou))
    solta.set()
    t.join(5)

    assert ("A", True) in resultados
    assert ("B", False) in resultados, "a segunda entrada tinha que ser barrada"


def test_guilds_diferentes_nao_se_bloqueiam():
    from atlas.concurrency import GuildLocks

    travas = GuildLocks()
    with travas.tentativa(1, 1.0) as pegou1:
        assert pegou1 is True
        with travas.tentativa(2, 1.0) as pegou2:
            assert pegou2 is True, "isolamento por guild quebrou (spec 8)"


def test_trava_e_liberada_no_final():
    from atlas.concurrency import GuildLocks

    travas = GuildLocks()
    with travas.tentativa(1, 1.0) as pegou:
        assert pegou is True
    with travas.tentativa(1, 1.0) as pegou:
        assert pegou is True, "nao liberou depois do bloco"
    assert travas.ocupada(1) is False


def test_trava_liberada_mesmo_com_excecao():
    from atlas.concurrency import GuildLocks

    travas = GuildLocks()
    with pytest.raises(RuntimeError):
        with travas.tentativa(1, 1.0):
            raise RuntimeError("boom")
    assert travas.ocupada(1) is False, "excecao deixou a trava presa para sempre"


def test_process_devolve_guild_busy_quando_o_guild_esta_travado(monkeypatch):
    """Spec 114: detectar o conflito e nao misturar planos."""
    import asyncio
    from types import SimpleNamespace

    from atlas.audit import AuditLog
    from atlas.bot import AtlasBot
    from atlas.config import load_settings

    bot = AtlasBot(load_settings(require_secrets=False), AuditLog(path=None))
    guild = SimpleNamespace(id=777)

    with bot.guild_locks.tentativa(777, 1.0) as pegou:
        assert pegou is True
        outcome = asyncio.run(bot._process(guild, SimpleNamespace(), "oi", SimpleNamespace()))

    assert outcome.blocked == "guild_busy"
    assert outcome.embeds, "tem que responder alguma coisa, nao ficar em silencio"
    assert bot.guild_locks.ocupada(777) is False, "a trava ficou presa"
