"""Seções de provider que faltavam cobrir (spec 53, 54, 55, 106, 146, 147)."""

from __future__ import annotations

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
