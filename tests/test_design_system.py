"""Sistema de design (spec 26-47, 78, 135-138)."""

from __future__ import annotations

from atlas.design_system import (
    Briefing,
    Dominio,
    EstiloVisual,
    Porte,
    Publico,
    design_score,
    inferir_dominio,
    inferir_estilo,
    inferir_porte,
    precisa_refazer,
    projetar,
)


# ------------------------------------------------------- spec 27: nao-generico
def test_dominios_diferentes_dao_estruturas_diferentes():
    a = projetar(Briefing(dominio=Dominio.GAMING_COMPETITIVO))
    b = projetar(Briefing(dominio=Dominio.LOJA))
    c = projetar(Briefing(dominio=Dominio.RP))
    assert a.nomes_de_canal() != b.nomes_de_canal()
    assert b.nomes_de_canal() != c.nomes_de_canal()
    assert "recrutamento" in a.nomes_de_canal() and "recrutamento" not in b.nomes_de_canal()
    assert "personagem" in " ".join(cat.nome for cat in c.categorias).lower()


def test_loja_tem_suporte_e_gaming_nao_tem_do_mesmo_jeito():
    loja = projetar(Briefing(dominio=Dominio.LOJA))
    assert any(c.nome for c in loja.categorias if "atendimento" in c.nome.lower())
    game = projetar(Briefing(dominio=Dominio.GAMING_COMPETITIVO))
    assert any("competitivo" in c.nome.lower() for c in game.categorias)


# ------------------------------------------- spec 78/79: nao existe template fixo
def test_tema_sozinho_nao_muda_a_estrutura():
    """O ponto da spec 78: nao existe 'template Fortnite'. Fortnite e Valorant
    com o mesmo porte/publico/estilo tem a mesma FORMA - o tema entra so no
    vocabulario. E isso esta certo: os dois sao gaming casual."""
    a = projetar(Briefing(tema="fortnite", dominio=Dominio.GAMING_CASUAL))
    b = projetar(Briefing(tema="valorant", dominio=Dominio.GAMING_CASUAL))
    assert a.briefing.assinatura() == b.briefing.assinatura(), "mesmo briefing estrutural"
    assert [(c.proposito, len(c.canais)) for c in a.categorias] == \
           [(c.proposito, len(c.canais)) for c in b.categorias]


def test_publico_muda_a_estrutura():
    """Mesmo tema, publico diferente -> arquitetura diferente. E aqui que o
    design deixa de ser template: 'Fortnite competitivo' nao e 'Fortnite casual'."""
    comp = projetar(Briefing(tema="fortnite", dominio=Dominio.GAMING_COMPETITIVO,
                             publico=Publico.COMPETITIVO))
    cas = projetar(Briefing(tema="fortnite", dominio=Dominio.GAMING_CASUAL,
                            publico=Publico.CASUAL))
    assert comp.total_canais != cas.total_canais
    assert any("lfg" in n for n in comp.nomes_de_canal())
    assert not any("lfg" in n for n in cas.nomes_de_canal())


# ----------------------------------------------------------------- spec 44: escala
def test_porte_pequeno_tem_menos_canal():
    """Spec 44: nao criar 100 canais para 20 membros."""
    p = projetar(Briefing(dominio=Dominio.COMUNIDADE, porte=Porte.PEQUENO))
    m = projetar(Briefing(dominio=Dominio.COMUNIDADE, porte=Porte.MEDIO))
    g = projetar(Briefing(dominio=Dominio.COMUNIDADE, porte=Porte.GRANDE))
    assert p.total_canais < m.total_canais < g.total_canais


def test_porte_pequeno_nao_deixa_categoria_vazia():
    """Cortar canal nao pode deixar categoria oca - isso viraria o defeito que o
    QA pos-execucao passou a apontar."""
    p = projetar(Briefing(dominio=Dominio.GAMING_COMPETITIVO, porte=Porte.PEQUENO))
    assert all(c.canais for c in p.categorias), [c.nome for c in p.categorias if not c.canais]


def test_porte_grande_ganha_area_de_equipe():
    g = projetar(Briefing(dominio=Dominio.COMUNIDADE, porte=Porte.GRANDE))
    assert any("equipe" in c.nome.lower() for c in g.categorias)
    privados = [c for cat in g.categorias for c in cat.canais if c.privado]
    assert privados, "area de staff tem que ser privada"


def test_hierarquia_cresce_com_o_porte():
    """Spec 41: hierarquia completa so quando faz sentido."""
    p = projetar(Briefing(porte=Porte.PEQUENO))
    g = projetar(Briefing(porte=Porte.GRANDE))
    nomes_p = [c.nome for c in p.cargos if c.tipo == "funcional"]
    nomes_g = [c.nome for c in g.cargos if c.tipo == "funcional"]
    assert len(nomes_g) > len(nomes_p)
    assert "ajudante" in nomes_g and "ajudante" not in nomes_p


def test_inferir_porte_por_numero_de_membros():
    assert inferir_porte(20) == Porte.PEQUENO
    assert inferir_porte(150) == Porte.MEDIO
    assert inferir_porte(5000) == Porte.GRANDE
    assert inferir_porte(None) == Porte.MEDIO, "sem dado, nao inventa: medio"


# ------------------------------------------------------- spec 36: nomenclatura
def test_estilo_aplica_uma_nomenclatura_so():
    """Spec 36: nao misturar estilo. Este e o defeito mais visivel de servidor
    montado por template."""
    arq = projetar(Briefing(dominio=Dominio.COMUNIDADE, estilo=EstiloVisual.COMPETITIVO))
    nomes = arq.nomes_de_canal()
    com_colchete = [n for n in nomes if "「" in n]
    assert com_colchete, nomes
    assert len(com_colchete) == len(nomes), "misturou: nem todo canal seguiu o estilo"


def test_estilo_minimalista_nao_tem_emoji():
    arq = projetar(Briefing(dominio=Dominio.COMUNIDADE, estilo=EstiloVisual.MINIMALISTA))
    for n in arq.nomes_de_canal():
        assert not any(ch in n for ch in "・「」"), n


def test_estilos_diferentes_dao_nomes_diferentes():
    a = projetar(Briefing(dominio=Dominio.COMUNIDADE, estilo=EstiloVisual.CLEAN))
    b = projetar(Briefing(dominio=Dominio.COMUNIDADE, estilo=EstiloVisual.GAMER))
    assert a.nomes_de_canal() != b.nomes_de_canal()


# --------------------------------------------------- spec 38/40/42: qualidade
def test_todo_canal_tem_proposito():
    """Spec 38: canal sem funcao clara nao deveria existir."""
    for dominio in Dominio:
        arq = projetar(Briefing(dominio=dominio))
        sem = [c.nome for cat in arq.categorias for c in cat.canais if not c.tem_funcao()]
        assert not sem, (dominio, sem)


def test_nenhum_canal_duplicado():
    for dominio in Dominio:
        arq = projetar(Briefing(dominio=dominio))
        nomes = [n.lower() for n in arq.nomes_de_canal()]
        assert len(nomes) == len(set(nomes)), dominio


def test_nenhum_cargo_funcional_nasce_com_admin():
    """Spec 42: menor privilegio. E a Fase 5 ja recusa isso em codigo."""
    for dominio in Dominio:
        for porte in Porte:
            arq = projetar(Briefing(dominio=dominio, porte=porte))
            com_admin = [c.nome for c in arq.cargos if "administrator" in c.permissoes]
            assert not com_admin, (dominio, porte, com_admin)


def test_funcional_e_identidade_separados():
    """Spec 40."""
    arq = projetar(Briefing(dominio=Dominio.GAMING_COMPETITIVO))
    assert any(c.tipo == "funcional" for c in arq.cargos)
    assert any(c.tipo == "identidade" for c in arq.cargos)
    for c in arq.cargos:
        if c.tipo == "identidade":
            assert c.permissoes == [], "cargo de identidade nao carrega permissao"


def test_todo_dominio_tem_onboarding():
    """Spec 43."""
    for dominio in Dominio:
        assert projetar(Briefing(dominio=dominio)).onboarding, dominio


# ---------------------------------------------------------------- spec 136: score
def test_score_aponta_problema_real():
    arq = projetar(Briefing(dominio=Dominio.COMUNIDADE))
    bom = design_score(arq)
    assert bom["geral"] >= 8, bom

    # estraga de proposito: canal sem proposito e nome duplicado
    arq.categorias[0].canais[0].proposito = ""
    arq.categorias[0].canais.append(arq.categorias[0].canais[0])
    ruim = design_score(arq)
    assert ruim["geral"] < bom["geral"]
    assert ruim["criterios"]["clareza"][0] < 10
    assert ruim["criterios"]["redundancia"][0] == 0
    assert precisa_refazer(arq), "arquitetura estragada tem que pedir refacao (spec 137)"


def test_score_cobre_os_criterios_da_spec():
    arq = projetar(Briefing(dominio=Dominio.COMUNIDADE))
    criterios = design_score(arq)["criterios"]
    for esperado in ("coerencia", "navegacao", "clareza", "redundancia",
                     "cargos", "onboarding", "escalabilidade"):
        assert esperado in criterios, esperado
        pontos, motivo = criterios[esperado]
        assert 0 <= pontos <= 10 and motivo, (esperado, motivo)


def test_score_aponta_escala_fora_da_faixa():
    arq = projetar(Briefing(dominio=Dominio.COMUNIDADE, porte=Porte.PEQUENO))
    # infla de proposito: porte pequeno com canal de porte grande
    from atlas.design_system import ProjetoCanal
    for _ in range(20):
        arq.categorias[0].canais.append(
            ProjetoCanal(nome=f"extra-{_}", tipo="text", proposito="enchendo")
        )
    pontos, motivo = design_score(arq)["criterios"]["escalabilidade"]
    assert pontos < 10 and "fora da faixa" in motivo, motivo


# ---------------------------------------------------------- spec 169: personalidade
def test_tirando_o_nome_do_jogo_ainda_da_para_distinguir():
    """Spec 169 ao pe da letra: comparar pelo PROPOSITO das areas, nunca pelo
    nome. Se dois dominios tem as mesmas areas com o mesmo proposito, o design
    e generico demais."""
    vistos: dict[tuple, Dominio] = {}
    for dominio in Dominio:
        arq = projetar(Briefing(dominio=dominio))
        forma = tuple((c.proposito, len(c.canais)) for c in arq.categorias)
        if forma in vistos:
            raise AssertionError(
                f"{dominio.value} tem a mesma forma que {vistos[forma].value}: "
                "tirando o nome, nao da para distinguir"
            )
        vistos[forma] = dominio


def test_onboarding_e_diferente_por_dominio():
    vistos = {}
    for dominio in Dominio:
        jornada = tuple(projetar(Briefing(dominio=dominio)).onboarding)
        if jornada in vistos:
            raise AssertionError(f"{dominio} repete a jornada de {vistos[jornada]}")
        vistos[jornada] = dominio


# ------------------------------------------------------------------ inferencia
def test_inferir_dominio_pelo_pedido():
    assert inferir_dominio("faz um servidor de Fortnite competitivo") == Dominio.GAMING_COMPETITIVO
    assert inferir_dominio("quero um servidor de GTA RP") == Dominio.RP
    assert inferir_dominio("servidor da minha loja") == Dominio.LOJA
    assert inferir_dominio("comunidade do meu saas") == Dominio.SAAS
    assert inferir_dominio("servidor do meu cla") == Dominio.CLA


def test_inferir_dominio_sem_chute():
    """Spec 132: nao assumir demais. Sem sinal, fica no generico."""
    assert inferir_dominio("faz um servidor") == Dominio.COMUNIDADE
    assert inferir_dominio("") == Dominio.COMUNIDADE


def test_inferir_estilo_pelo_pedido():
    assert inferir_estilo("faz premium") == EstiloVisual.PREMIUM
    assert inferir_estilo("quero cyberpunk") == EstiloVisual.CYBERPUNK
    assert inferir_estilo("competitivo") == EstiloVisual.COMPETITIVO
    assert inferir_estilo("tanto faz") == EstiloVisual.CLEAN


# ---------------------------------------------- Fase 22: a proposta chega ao prompt
def test_proposta_de_design_e_gerada_para_pedido_de_design():
    from atlas.design import proposta_de_design

    t = proposta_de_design("crie um servidor de Fortnite competitivo", n_membros=120)
    assert t, "pedido de design tem que gerar proposta"
    # conteudo concreto, nao principio: nome de categoria e canal de verdade
    assert "anuncios" in t and "lfg" in t
    assert "Cargos funcionais" in t and "Jornada de entrada" in t
    # porte pequeno entra na conta
    pequeno = proposta_de_design("crie um servidor de Fortnite", n_membros=20)
    assert "porte: pequeno" in pequeno.replace("Porte considerado: ", "porte: ")


def test_proposta_nao_aparece_em_pedido_comum():
    """Spec 11/185: nao encher o prompt de projeto em pedido simples. Custaria
    ~290 tokens a toa em cada volta do agente."""
    from atlas.design import proposta_de_design

    assert proposta_de_design("cria um canal chamado geral") == ""
    assert proposta_de_design("") == ""


def test_proposta_chega_ao_prompt_de_sistema():
    """A ligacao de verdade: sem isto o sistema de design seria codigo morto."""
    from atlas.config import Limits
    from atlas.policy import ActionBudget, Policy
    from atlas.prompts import build_system_prompt
    from atlas.testing.fake_gateway import FakeGateway
    from atlas.tools import build_registry
    from atlas.tools.base import ToolContext

    L = Limits()
    gw = FakeGateway()
    pol = Policy(
        guild_id=gw.guild_id,
        budget=ActionBudget(
            max_actions=L.max_actions_per_plan,
            max_creates=L.max_creates_per_plan,
            max_deletes=L.max_deletes_per_plan,
        ),
        destructive_confirm_threshold=L.destructive_confirm_threshold,
    )
    ctx = ToolContext(guild_id=gw.guild_id, gateway=gw, policy=pol, limits=L,
                      snapshot=gw.snapshot())
    reg = build_registry()

    com_pedido = build_system_prompt(ctx.snapshot, reg, pol, request="monta um servidor de xadrez")
    sem_pedido = build_system_prompt(ctx.snapshot, reg, pol, request="cria um canal chamado geral")
    assert "PROPOSTA DE ARQUITETURA" in com_pedido
    assert "PROPOSTA DE ARQUITETURA" not in sem_pedido


# ------------------------------------------------- spec 39: nem tudo é texto
def test_nem_tudo_e_canal_de_texto():
    """Spec 39: 'nao assumir que tudo deve ser texto'. Se todo canal do projeto
    sair como texto, o design nao escolheu tipo nenhum."""
    for dominio in Dominio:
        arq = projetar(Briefing(dominio=dominio))
        tipos = {c.tipo for cat in arq.categorias for c in cat.canais}
        assert tipos != {"text"}, f"{dominio.value}: tudo virou texto"


def test_forum_vai_para_onde_a_conversa_e_por_topico():
    """Forum e para pergunta/suporte/ideia - cada topico vira uma thread.
    Nao e decoracao: colocar forum em 'clipes' seria pior que texto."""
    arq = projetar(Briefing(dominio=Dominio.SAAS))
    por_nome = {c.nome: c.tipo for cat in arq.categorias for c in cat.canais}
    assert any(t == "forum" for t in por_nome.values()), por_nome


def test_forum_nao_vira_para_canal_de_conversa_corrida():
    arq = projetar(Briefing(dominio=Dominio.COMUNIDADE))
    por_nome = {c.nome: c.tipo for cat in arq.categorias for c in cat.canais}
    for nome, tipo in por_nome.items():
        if "bate-papo" in nome:
            assert tipo == "text", "bate-papo em forum atrapalha conversa corrida"


def test_tipos_usados_estao_no_schema_da_tool():
    """Se o design inventar um tipo que a tool recusa, o plano falha na execução.
    Este teste compara com o enum real de src/atlas/tools/channels.py."""
    import re
    from pathlib import Path

    fonte = (Path(__file__).resolve().parent.parent / "src" / "atlas" / "tools"
             / "channels.py").read_text(encoding="utf-8")
    m = re.search(r'"enum": \[([^\]]+)\]', fonte)
    assert m, "enum de tipo de canal sumiu do schema"
    aceitos = {x.strip().strip('"') for x in m.group(1).split(",")}
    usados = set()
    for dominio in Dominio:
        for cat in projetar(Briefing(dominio=dominio)).categorias:
            usados.update(c.tipo for c in cat.canais)
    assert usados <= aceitos, f"design usa tipo que a tool recusa: {usados - aceitos}"
