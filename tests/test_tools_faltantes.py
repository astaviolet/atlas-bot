"""As 4 tools que estavam sem nenhum teste.

Varredura feita sobre as 21 tools permitidas contra `tests/`: get_categories,
get_channel, get_role e edit_category não apareciam em nenhum teste. As outras
17 apareciam. Tool sem teste é tool que quebra em silêncio — e uma delas é de
ESCRITA (edit_category) enquanto as outras alimentam a decisão do modelo.
"""

from __future__ import annotations

from conftest import IDS, final, turn


# --------------------------------------------------------------- get_categories
def test_get_categories_lista_as_categorias(harness):
    h = harness([turn(("get_categories", {})), final("São 4 categorias.")])
    outcome = h.ask("quais categorias tem aqui?")

    assert len(outcome.results) == 1
    r = outcome.results[0]
    assert r.ok is True, f"get_categories falhou: {r.error}"
    nomes = str(r.data).lower()
    assert "informacoes" in nomes or "informações" in nomes


def test_get_categories_e_somente_leitura(harness):
    """Leitura não pode contar como mudança: se contasse, o limite de ações
    puniria o modelo por olhar o servidor antes de agir."""
    from atlas.policy import is_read_only

    assert is_read_only("get_categories") is True


def test_get_categories_nao_muda_nada(harness):
    h = harness([turn(("get_categories", {})), final("Ok.")])
    antes = dict(h.gateway.channels)
    h.ask("lista as categorias")
    assert h.gateway.channels == antes, "leitura mudou o servidor"


# ------------------------------------------------------------------ get_channel
def test_get_channel_devolve_o_canal(harness):
    alvo = IDS["ch_bate_papo"]
    h = harness([turn(("get_channel", {"channel_id": str(alvo)})), final("Achei.")])
    outcome = h.ask("me fala do canal bate-papo")

    r = outcome.results[0]
    assert r.ok is True, f"get_channel falhou: {r.error}"
    assert str(alvo) in str(r.data)


def test_get_channel_inexistente_erro_controlado(harness):
    """ID que não existe tem que virar erro com mensagem de usuário, não exceção
    crua — senão o modelo recebe um traceback e inventa em cima."""
    h = harness([turn(("get_channel", {"channel_id": "999999999999999999"})), final("Não achei.")])
    outcome = h.ask("fala do canal 999999999999999999")

    r = outcome.results[0]
    assert r.ok is False
    assert r.user_message, "erro sem mensagem para o usuário"
    assert "Traceback" not in str(r.user_message)


def test_get_channel_ignora_guild_id_vindo_do_modelo(harness):
    """Isolamento de guild é absoluto.

    O mecanismo real NÃO é "a chamada falha": é `strip_foreign_guild_keys`
    removendo a chave antes de executar. A primeira versão deste teste afirmava
    só `ok is False` e passava pelo motivo errado — o canal 1 não existia, então
    dava NotFound de qualquer jeito. Aqui o canal existe de verdade, e o que se
    afirma é que ele foi lido no servidor CERTO, não no 999.
    """
    alvo = IDS["ch_bate_papo"]
    h = harness([
        turn(("get_channel", {"channel_id": str(alvo), "guild_id": "999"})),
        final("Achei."),
    ])
    outcome = h.ask(f"fala do canal {alvo} do servidor 999")

    r = outcome.results[0]
    assert r.ok is True, f"o canal existe no servidor certo: {r.error}"
    # Se tivesse ido na guild 999, não acharia o canal do servidor real.
    assert str(alvo) in str(r.data)
    assert "999" not in str(r.action.params), \
        f"guild_id do modelo chegou na tool: {r.action.params}"


# --------------------------------------------------------------------- get_role
def test_get_role_devolve_o_cargo(harness):
    alvo = IDS["role_atlas"]
    h = harness([turn(("get_role", {"role_id": str(alvo)})), final("Achei.")])
    outcome = h.ask("me fala do cargo Atlas")

    r = outcome.results[0]
    assert r.ok is True, f"get_role falhou: {r.error}"
    assert str(alvo) in str(r.data)


def test_get_role_diz_se_o_bot_pode_editar(harness):
    """A descrição da tool promete dizer se o bot pode editar o cargo. Sem isso
    o modelo tenta editar cargo acima dele e toma erro do Discord."""
    acima = IDS["role_dono_supremo"]
    h = harness([turn(("get_role", {"role_id": str(acima)})), final("Não posso.")])
    outcome = h.ask("fala do cargo Dono Supremo")

    r = outcome.results[0]
    assert r.ok is True, f"get_role falhou: {r.error}"
    corpo = str(r.data).lower()
    assert "edit" in corpo or "pode" in corpo or "hierarq" in corpo, \
        f"a resposta nao diz se pode editar: {corpo[:200]}"


def test_get_role_inexistente_erro_controlado(harness):
    h = harness([turn(("get_role", {"role_id": "999999999999999999"})), final("Não achei.")])
    outcome = h.ask("fala do cargo 999999999999999999")

    r = outcome.results[0]
    assert r.ok is False
    assert r.user_message


# ---------------------------------------------------------------- edit_category
def test_edit_category_renomeia(harness):
    alvo = IDS["cat_comunidade"]
    h = harness([
        turn(("edit_category", {"category_id": str(alvo), "name": "Pessoal"})),
        final("Renomeei."),
    ])
    outcome = h.ask("renomeia a categoria COMUNIDADE para Pessoal")

    r = outcome.results[0]
    assert r.ok is True, f"edit_category falhou: {r.error}"
    assert r.verified is True, "verificacao pos-acao falhou"
    assert h.gateway.channels[alvo].name.upper() == "PESSOAL"


def test_edit_category_preserva_os_canais_de_dentro(harness):
    """Renomear categoria não pode órfar os canais. Esse é o risco real da
    operação e não estava coberto por nada."""
    alvo = IDS["cat_comunidade"]
    h = harness([
        turn(("edit_category", {"category_id": str(alvo), "name": "Pessoal"})),
        final("Renomeei."),
    ])
    filhos_antes = sorted(
        c.id for c in h.gateway.channels.values() if c.parent_id == alvo
    )
    assert filhos_antes, "o teste precisa de uma categoria com filhos"

    h.ask("renomeia COMUNIDADE para Pessoal")

    filhos_depois = sorted(
        c.id for c in h.gateway.channels.values() if c.parent_id == alvo
    )
    assert filhos_depois == filhos_antes, "renomear a categoria órfou os canais"


def test_edit_category_inexistente_erro_controlado(harness):
    h = harness([
        turn(("edit_category", {"category_id": "999999999999999999", "name": "X"})),
        final("Não achei."),
    ])
    outcome = h.ask("renomeia a categoria 999999999999999999")

    r = outcome.results[0]
    assert r.ok is False
    assert r.user_message


# --------------------------------------- canal de controle nao se apaga (bug real)
def test_nao_apaga_o_canal_de_onde_veio_o_pedido(harness):
    """BUG REAL, medido: o usuario pediu "remova todos os canais e deixe apenas
    esse" e o bot apagou `atlas-config` - o canal onde ele recebe comando. Ficou
    inutilizavel, sem ter para onde responder. O audit log do Discord confirmou
    user_id = o proprio bot.
    """
    from conftest import IDS

    alvo = IDS["ch_bate_papo"]
    h = harness([turn(("delete_channel", {"channel_id": str(alvo)})), final("Apaguei.")])
    # o harness nao define source_channel_id (fica None); no bot real vem de
    # message.channel.id, ou seja, do contexto real do Discord
    h.ctx.source_channel_id = alvo
    outcome = h.ask("apaga esse canal")

    r = outcome.results[0]
    assert r.ok is False, "apagou o canal de onde veio o pedido"
    assert alvo in h.gateway.channels, "o canal sumiu"
    assert "Nao apago" in (r.user_message or "")


def test_apagar_canal_comum_continua_funcionando(harness):
    """A protecao nao pode virar bloqueio geral - senao a tool para de servir."""
    from conftest import IDS

    alvo = IDS["ch_anuncios_610000000000000000"]
    h = harness([turn(("delete_channel", {"channel_id": str(alvo)})), final("Apaguei.")])
    outcome = h.ask("apaga o canal de anuncios")

    r = outcome.results[0]
    assert r.ok is True, f"bloqueou canal comum: {r.error}"
    assert alvo not in h.gateway.channels
