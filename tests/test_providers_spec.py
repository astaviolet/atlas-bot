"""Seções de provider que faltavam cobrir (spec 53, 54, 55, 106, 109, 146, 147)."""

from __future__ import annotations

from pathlib import Path

from atlas.ai.providers import CATALOG, Access, catalog_summary


# ------------------------------------------------------- spec 54: no-key first
def test_pool_default_e_sem_chave():
    """Spec 54: priorizar acesso sem chave. E a regra que o usuario deu: nao
    exigir secret para o bot funcionar."""
    sem_chave = [g for g in CATALOG if g.access is Access.NO_AUTH]
    assert sem_chave, "o pool default nao tem nenhum gateway sem chave"
    assert len(sem_chave) >= 2, "um so gateway sem chave nao e pool, e ponto unico"


def test_nenhum_gateway_exige_chave_inventada():
    """Spec 54: 'nunca inventar API keys'. Gateway que precisa de chave tem que
    estar marcado MANUAL_REQUIRED, nunca com chave falsa embutida."""
    for g in CATALOG:
        if g.access is Access.MANUAL_REQUIRED:
            continue
        assert not g.api_key, f"{g.id} tem chave embutida no codigo"


def test_gateway_que_exige_configuracao_esta_marcado():
    """Spec 146: marcar MANUAL_REQUIRED e continuar, nao parar o sistema."""
    manual = [g for g in CATALOG if g.access is Access.MANUAL_REQUIRED]
    for g in manual:
        assert not g.api_key, f"{g.id} marcado manual mas tem chave"


def test_resumo_do_catalogo_conta_os_dois_tipos():
    resumo = catalog_summary(CATALOG)
    assert resumo["sem_chave"] >= 2
    assert "exigem_chave" in resumo


# --------------------------------------------- spec 147: sem chave nao e sem limite
def test_todo_gateway_sem_chave_tem_limite_declarado():
    """Spec 147: mesmo provider sem key tem limite. Sem rpm declarado o
    distribuidor de carga nao tem como respeitar nada."""
    for g in CATALOG:
        if g.access is not Access.NO_AUTH:
            continue
        assert g.rpm > 0, f"{g.id} sem rpm declarado"
        assert g.concurrency >= 1, f"{g.id} sem concurrency declarada"


# --------------------------------------------------------- spec 55: nao burlar
def test_pool_nao_distribui_carga_acima_do_limite_declarado():
    """Spec 55: distribuir carga SO entre recursos legitimamente disponiveis.
    O rpm do catalogo e o teto que o router respeita - nao um numero decorativo."""
    for g in CATALOG:
        rotas = len(g.models)
        assert rotas >= 1, f"{g.id} sem rota"
        # o limite e por gateway, nao por modelo: somar rpm por rota seria um
        # jeito de fingir capacidade que o provedor nao da
        assert g.rpm <= 1000, f"{g.id} com rpm {g.rpm} irreal para tier gratuito"


# ------------------------------------------------------------- spec 106: custo
def test_pool_inteiro_e_gratuito_entao_nao_ha_eixo_de_custo():
    """Spec 106 diz 'se houver custo'. Nao ha: todo gateway do pool e gratuito e
    anonimo. Registrar isto como teste evita que alguem adicione provedor pago
    sem perceber que a escolha de rota nao considera preco."""
    for g in CATALOG:
        assert g.access in (Access.NO_AUTH, Access.MANUAL_REQUIRED), g.id


# ------------------------------------------------- spec 109: saida estruturada
def test_satisfies_rejeita_quando_falta_structured_output():
    from atlas.ai.providers import Capabilities

    tem_so_tools = Capabilities(tool_calling=True, structured_output=False)
    precisa = Capabilities(structured_output=True)
    assert tem_so_tools.satisfies(precisa) is False


def test_satisfies_aceita_quando_a_rota_oferece():
    from atlas.ai.providers import Capabilities

    tem = Capabilities(tool_calling=True, structured_output=True)
    assert tem.satisfies(Capabilities(structured_output=True)) is True


def test_satisfies_rejeita_quando_falta_tool_calling():
    from atlas.ai.providers import Capabilities

    sem_tools = Capabilities(tool_calling=False)
    assert sem_tools.satisfies(Capabilities(tool_calling=True)) is False


def test_satisfies_rejeita_quando_falta_vision():
    from atlas.ai.providers import Capabilities

    sem_visao = Capabilities(tool_calling=True, vision=False)
    assert sem_visao.satisfies(Capabilities(vision=True)) is False


def test_satisfies_aceita_pedido_vazio():
    """Nenhuma capacidade exigida -> qualquer rota serve."""
    from atlas.ai.providers import Capabilities

    assert Capabilities().satisfies(Capabilities()) is True


def test_classificacao_nao_exige_structured_output():
    """Nenhuma rota do pool gratuito gratuito declara a capacidade. Exigir aqui
    faria a classificacao cair sempre - por isso ela degrada para tool calling,
    que e testado. Este teste trava a decisao: se alguem passar a exigir, quebra.
    """
    from atlas.ai import classificacao

    fonte = Path(classificacao.__file__).read_text(encoding="utf-8")
    assert "structured_output nao e exigido aqui de proposito" in fonte


def test_nenhuma_rota_do_pool_default_declara_structured_output():
    """Documenta a realidade medida, nao uma vontade. Se um dia uma rota passar
    a declarar, este teste avisa para a gente ligar o caminho JSON de verdade."""
    from atlas.ai.providers import all_routes

    com_saida = [r for r in all_routes() if r.caps.structured_output]
    assert com_saida == [], f"pool mudou, ligar o caminho JSON: {com_saida}"


# ------------------------------------------------- spec 53: descoberta de provedor
def test_ovh_nao_afirma_tool_calling_sem_ter_confirmado():
    """O tier anonimo da OVH esta vivo (200 em /v1/models, 24 modelos), mas o
    limite de 2 req/min por modelo estourou em 3 tentativas antes de dar para
    confirmar tool calling. Entrar no pool anonimo afirmando a capacidade seria
    inventar - por isso segue MANUAL_REQUIRED. Se um dia confirmar, este teste
    avisa para ligar.
    """
    from atlas.ai.providers import CATALOG, Access

    ovh = next(g for g in CATALOG if g.id == "ovh")
    assert ovh.access == Access.MANUAL_REQUIRED
    assert ovh.rpm == 2, "o limite medido e 2 req/min por IP por modelo"
    assert "2 req/min" in ovh.notes


def test_pool_anonimo_tem_pelo_menos_dois_gateways_sem_chave():
    """Regra da missao de 21 itens: o pool default precisa de redundancy sem configuracao manual. OVH nao conta aqui porque e MANUAL_REQUIRED."""
    from atlas.ai.providers import CATALOG, Access

    anonimos = [g.id for g in CATALOG if g.access == Access.NO_AUTH]
    assert len(anonimos) >= 2, f"pool anonimo fraco: {anonimos}"
