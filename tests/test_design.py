

# ------------------------------------------------- spec 11: planner estruturado
def _briefing(tema="servidor de fortnite"):
    from atlas.design_system import (
        Briefing, Dominio, Porte, Publico,
    )

    return Briefing(tema=tema, dominio=Dominio.GAMING_COMPETITIVO,
                    porte=Porte.MEDIO, publico=Publico.MISTO)


def test_plano_tem_todos_os_campos_da_spec_11():
    from atlas.design import CAMPOS_DO_PLANO, plano_estruturado
    from atlas.design_system import projetar

    b = _briefing()
    plano = plano_estruturado(b, projetar(b))
    for campo in CAMPOS_DO_PLANO:
        assert f"{campo}:" in plano, f"faltou o campo {campo}"


def test_plano_nao_imprime_repr_de_lista():
    """`onboarding` é lista; sair "['ler as regras']" é repr de Python na cara
    do usuário."""
    from atlas.design import plano_estruturado
    from atlas.design_system import projetar

    b = _briefing()
    assert projetar(b).onboarding, "o teste precisa de onboarding para valer"
    plano = plano_estruturado(b, projetar(b))
    assert "['" not in plano and '"]' not in plano


def test_plano_nao_imprime_valor_cru_de_enum():
    """'gaming_competitivo' é identificador de código, não texto de gente."""
    from atlas.design import plano_estruturado
    from atlas.design_system import projetar

    plano = plano_estruturado(_briefing(), projetar(_briefing()))
    assert "gaming_competitivo" not in plano
    assert "gaming competitivo" in plano


def test_plano_avisa_quando_ha_exclusao():
    from atlas.design import plano_estruturado
    from atlas.design_system import projetar

    b = _briefing()
    plano = plano_estruturado(b, projetar(b), destruicoes=3)
    assert "3 canal(is) marcado(s) para exclusao" in plano
    assert "sim - ha exclusao" in plano


def test_plano_sem_exclusao_diz_que_nao_ha():
    from atlas.design import plano_estruturado
    from atlas.design_system import projetar

    plano = plano_estruturado(_briefing(), projetar(_briefing()))
    assert "nenhuma - nada sera excluido" in plano


def test_plano_nao_executa_nada():
    """Spec 11: 'Plano ≠ execução'. A função devolve texto, não ação."""
    from atlas.design import plano_estruturado
    from atlas.design_system import projetar

    b = _briefing()
    assert isinstance(plano_estruturado(b, projetar(b)), str)


def test_proposta_de_design_leva_o_plano_junto():
    from atlas.design import proposta_de_design

    texto = proposta_de_design("crie um servidor tematico de xadrez, comunidade pequena")
    assert "PLANO (nao execute ainda" in texto
    assert "OBJETIVO:" in texto
