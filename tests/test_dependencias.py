"""Dependencias de execucao (spec 21)."""

from __future__ import annotations

from conftest import final, turn

from atlas.dependencias import nivel, ordenar_por_dependencia, violacoes
from atlas.queue import PlannedAction


def _a(tool, **params):
    return PlannedAction(tool=tool, params=params)


# ------------------------------------------------------------------- ordenacao
def test_categoria_vem_antes_de_canal():
    """Spec 21: nao tentar criar canal dentro de categoria que ainda nao existe."""
    ordenado = ordenar_por_dependencia([
        _a("create_channel", name="geral", category_name="Comunidade"),
        _a("create_category", name="Comunidade"),
    ])
    assert [a.tool for a in ordenado] == ["create_category", "create_channel"]


def test_exclusao_vem_antes_de_criacao():
    """Se delete vier depois, a idempotencia reusa o antigo e o delete apaga o
    que acabou de ser reaproveitado - o pedido inteiro se desfaz."""
    ordenado = ordenar_por_dependencia([
        _a("create_channel", name="antigo"),
        _a("delete_channel", channel_id="1"),
    ])
    assert [a.tool for a in ordenado] == ["delete_channel", "create_channel"]


def test_permissao_vem_por_ultimo():
    """Precisa do canal E do cargo ja criados."""
    ordenado = ordenar_por_dependencia([
        _a("set_channel_permissions", channel_id="9"),
        _a("create_channel", name="staff"),
        _a("create_role", name="Mod"),
        _a("create_category", name="Staff"),
    ])
    assert [a.tool for a in ordenado] == [
        "create_category", "create_channel", "create_role", "set_channel_permissions",
    ]


def test_leitura_vem_primeiro():
    ordenado = ordenar_por_dependencia([
        _a("create_channel", name="x"), _a("get_channels"),
    ])
    assert [a.tool for a in ordenado] == ["get_channels", "create_channel"]


def test_ordenacao_e_estavel_dentro_do_nivel():
    """A ordem do modelo define a posicao na barra lateral. Reordenar isso seria
    mudar o design sem avisar."""
    ordenado = ordenar_por_dependencia([
        _a("create_channel", name="regras"),
        _a("create_channel", name="anuncios"),
        _a("create_channel", name="bate-papo"),
    ])
    assert [a.params["name"] for a in ordenado] == ["regras", "anuncios", "bate-papo"]


def test_nada_e_descartado():
    acoes = [_a("create_channel", name=str(i)) for i in range(7)]
    acoes.append(_a("delete_role", role_id="3"))
    assert len(ordenar_por_dependencia(acoes)) == 8


def test_tool_desconhecida_vai_para_o_fim():
    """Extensibilidade (spec 126): tool nova nao fura a fila das conhecidas."""
    assert nivel("tool_do_futuro") == 7
    ordenado = ordenar_por_dependencia([
        _a("tool_do_futuro"), _a("create_channel", name="x"),
    ])
    assert [a.tool for a in ordenado] == ["create_channel", "tool_do_futuro"]


def test_violacoes_aponta_alvo_que_nao_existe():
    problemas = violacoes([
        _a("move_channel", name="fantasma"),
        _a("create_channel", name="real"),
    ])
    assert problemas and "fantasma" in problemas[0]
    assert violacoes([_a("create_channel", name="real"),
                      _a("move_channel", name="real")]) == []


# ----------------------------------------------------------------- ponta a ponta
def test_categoria_e_canal_no_mesmo_pedido_funciona(harness):
    """O caso que a spec 21 descreve: criar os dois de uma vez."""
    h = harness([
        turn(("create_channel", {"name": "bate-papo", "type": "text",
                                 "category_name": "Comunidade"}),
             ("create_category", {"name": "Comunidade"})),
        final("ok"),
    ], seed=False)
    out = h.ask("cria a categoria Comunidade com um bate-papo dentro")

    assert len([r for r in out.results if r.ok]) == 2, [
        (r.action.tool, r.error) for r in out.results
    ]
    cid = h.find_channel_id("bate-papo")
    assert cid is not None
    canal = next(c for c in h.gateway.snapshot().channels if c.id == cid)
    assert canal.parent_id is not None, "o canal tem que estar dentro da categoria"


def test_category_name_inexistente_da_erro_claro(harness):
    """Resolver por nome nao pode virar canal orfao silencioso."""
    h = harness([
        turn(("create_channel", {"name": "x", "type": "text",
                                 "category_name": "NaoExiste"})),
        final("ok"),
    ], seed=False)
    out = h.ask("cria um canal dentro de NaoExiste")

    assert len([r for r in out.results if r.ok]) == 0
    assert "NaoExiste" in (out.results[0].user_message or "")
    assert h.find_channel_id("x") is None, "nao pode ter criado orfao"


def test_category_id_continua_funcionando(harness):
    """Nao regredir o caminho antigo (spec 3): id explicito segue valendo."""
    h = harness([turn(("create_category", {"name": "Geral"})), final("ok")], seed=False)
    h.ask("cria a categoria Geral")
    # o Discord grava nome de categoria em CAIXA ALTA, entao a busca aqui tem
    # que ser case-insensitive. A resolucao por category_name ja usa casefold()
    # na tool - este teste so nao pode ser mais rigido que o codigo.
    cat_id = next((c.id for c in h.gateway.snapshot().channels
                   if c.is_category and c.name.casefold() == "geral"), None)
    assert cat_id is not None, "a categoria tinha que ter sido criada"

    # o id so existe depois da primeira execucao, entao o segundo turno entra agora
    h.agent.model._script.append(  # noqa: SLF001 - roteiro do fake, por definicao
        turn(("create_channel", {"name": "y", "type": "text",
                                 "category_id": str(cat_id)}))
    )
    h.agent.model._script.append(final("ok"))

    out = h.ask("agora cria y dentro dela pelo id")
    assert len([r for r in out.results if r.ok]) == 1, [r.error for r in out.results]
    y = next(c for c in h.gateway.snapshot().channels if c.name == "y")
    assert y.parent_id == cat_id
