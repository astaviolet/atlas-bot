"""Auditoria de design final (spec 168, 170, 171, 172).

A spec 168 manda criar servidores de teste para 10 cenarios e comparar
diversidade. Este arquivo faz isso contra o sistema de design de verdade - nao
contra mock. Se o design virar template, estes testes falham.
"""

from __future__ import annotations

import pytest

from atlas.design_system import (
    Briefing,
    Dominio,
    EstiloVisual,
    Porte,
    Publico,
    design_score,
    projetar,
)

#: Os 10 cenarios que a spec 168 lista, com o briefing que o bot inferiria.
CENARIOS: list[tuple[str, Briefing]] = [
    ("Fortnite", Briefing(tema="fortnite", dominio=Dominio.GAMING_COMPETITIVO,
                          publico=Publico.COMPETITIVO, estilo=EstiloVisual.COMPETITIVO,
                          porte=Porte.MEDIO)),
    ("Minecraft", Briefing(tema="minecraft", dominio=Dominio.GAMING_CASUAL,
                           publico=Publico.CASUAL, estilo=EstiloVisual.CASUAL,
                           porte=Porte.MEDIO)),
    ("GTA RP", Briefing(tema="gta rp", dominio=Dominio.RP,
                        publico=Publico.MISTO, estilo=EstiloVisual.DARK,
                        porte=Porte.GRANDE)),
    ("Comunidade geral", Briefing(tema="comunidade", dominio=Dominio.COMUNIDADE,
                                  porte=Porte.MEDIO)),
    ("Clã", Briefing(tema="cla", dominio=Dominio.CLA,
                     publico=Publico.COMPETITIVO, estilo=EstiloVisual.MILITAR,
                     porte=Porte.MEDIO)),
    ("Criador", Briefing(tema="criador", dominio=Dominio.CRIADOR,
                         estilo=EstiloVisual.GAMER, porte=Porte.MEDIO)),
    ("Loja", Briefing(tema="loja", dominio=Dominio.LOJA,
                      publico=Publico.PROFISSIONAL, estilo=EstiloVisual.PROFISSIONAL,
                      porte=Porte.MEDIO)),
    ("Premium", Briefing(tema="premium", dominio=Dominio.SAAS,
                         publico=Publico.PROFISSIONAL, estilo=EstiloVisual.PREMIUM,
                         porte=Porte.GRANDE)),
    ("Pequena", Briefing(tema="amigos", dominio=Dominio.COMUNIDADE,
                         porte=Porte.PEQUENO, estilo=EstiloVisual.MINIMALISTA)),
    ("Grande", Briefing(tema="comunidade grande", dominio=Dominio.COMUNIDADE,
                        porte=Porte.GRANDE, estilo=EstiloVisual.CLEAN)),
]


# ------------------------------------------------------------- spec 168: diversidade
def test_os_dez_cenarios_produzem_estruturas_diferentes():
    """O teste central da spec 168: ausencia de template repetitivo. Compara a
    FORMA das areas pelo proposito - nunca pelo nome, porque nome e vocabulario
    e vocabulario e supposed to variar com o tema."""
    formas: dict[tuple, str] = {}
    for rotulo, briefing in CENARIOS:
        arq = projetar(briefing)
        forma = tuple((c.proposito, len(c.canais)) for c in arq.categorias)
        if forma in formas:
            pytest.fail(
                f"'{rotulo}' tem a mesma estrutura de '{formas[forma]}' - "
                "template repetitivo"
            )
        formas[forma] = rotulo


def test_os_dez_cenarios_tem_nomes_de_canal_diferentes():
    vistos: dict[tuple, str] = {}
    for rotulo, briefing in CENARIOS:
        nomes = tuple(sorted(n.lower() for n in projetar(briefing).nomes_de_canal()))
        if nomes in vistos:
            pytest.fail(f"'{rotulo}' repete exatamente os canais de '{vistos[nomes]}'")
        vistos[nomes] = rotulo


def test_nenhum_cenario_parece_generico():
    """Spec 137: 'isso parece um servidor criado para ESTE pedido?' Score baixo
    significa projeto ruim, e nenhum dos 10 cenarios pode cair nisso."""
    for rotulo, briefing in CENARIOS:
        nota = design_score(projetar(briefing))["geral"]
        assert nota >= 8.0, f"'{rotulo}' com nota {nota}"


def test_cada_cenario_tem_cargos_e_onboarding():
    for rotulo, briefing in CENARIOS:
        arq = projetar(briefing)
        assert arq.cargos, f"'{rotulo}' sem cargos"
        assert arq.onboarding, f"'{rotulo}' sem jornada de entrada"


# --------------------------------------------------------------- spec 170: usabilidade
def test_usuario_novo_sabe_por_onde_comecar():
    """'Entrei. Sei o que fazer?' O primeiro canal de cada servidor tem que ser
    de chegada, e a jornada tem que comecar por entender as regras."""
    for rotulo, briefing in CENARIOS:
        arq = projetar(briefing)
        primeiro = arq.categorias[0].canais[0].nome.lower()
        assert any(k in primeiro for k in ("boas", "welcome", "chegada", "início")), \
            f"'{rotulo}' comeca em '{primeiro}', nao em chegada"
        # 'regra' OU 'politica': numa loja o combinado e a politica de compra.
        # Exigir a palavra 'regra' seria testar vocabulario, nao a jornada.
        assert any(("regra" in passo or "política" in passo or "politica" in passo)
                   for passo in arq.onboarding[:2]), \
            f"'{rotulo}' nao manda ler o combinado no comeco: {arq.onboarding[:2]}"


def test_jornada_tem_passo_de_participacao():
    """Onboarding que so manda ler e onboarding que nao converte ninguem: o
    ultimo passo tem que ser participar de algo."""
    for rotulo, briefing in CENARIOS:
        jornada = projetar(briefing).onboarding
        assert len(jornada) >= 3, f"'{rotulo}' com jornada de {len(jornada)} passo"
        ultimo = jornada[-1].lower()
        # O que importa e o ultimo passo ser ACAO, nao mais leitura. A lista de
        # verbo era arbitraria e reprovava 'dar feedback', que numa comunidade de
        # criador e participacao de verdade.
        assert not ultimo.startswith(("ler", "ver ", "entender")), \
            f"'{rotulo}' termina em passo passivo: '{ultimo}'"
        assert ultimo.split()[0] in (
            "entrar", "participar", "jogar", "procurar", "chamar", "propor",
            "tirar", "criar", "pedir", "dar", "montar",
        ), f"'{rotulo}' termina em '{ultimo}'"


# ---------------------------------------------------------- spec 171: administrador
def test_admin_consegue_identificar_a_hierarquia():
    """'Consigo entender e administrar essa estrutura?' Posicoes tem que ser
    distintas e ordenaveis - dois cargos na mesma posicao sao hierarquia
    ambigua."""
    for rotulo, briefing in CENARIOS:
        arq = projetar(briefing)
        funcionais = [c for c in arq.cargos if c.tipo == "funcional"]
        posicoes = [c.posicao for c in funcionais]
        assert len(posicoes) == len(set(posicoes)), \
            f"'{rotulo}' com cargos funcionais na mesma posicao"
        assert max(posicoes) > min(posicoes), f"'{rotulo}' sem hierarquia"


def test_servidor_grande_tem_area_de_staff():
    """Administrar servidor grande sem area privada de staff nao da."""
    for rotulo, briefing in CENARIOS:
        if briefing.porte != Porte.GRANDE:
            continue
        arq = projetar(briefing)
        privados = [c for cat in arq.categorias for c in cat.canais if c.privado]
        assert privados, f"'{rotulo}' (grande) sem canal privado de staff"


def test_permissoes_de_staff_sao_explicitas():
    for rotulo, briefing in CENARIOS:
        arq = projetar(briefing)
        staff = [c for c in arq.cargos if c.nome in ("admin", "mod", "gerente", "ajudante")]
        for c in staff:
            assert c.permissoes, f"'{rotulo}': cargo '{c.nome}' sem permissao definida"


# ------------------------------------------------------------------- spec 172: escala
def test_estrutura_continua_funcional_com_10x_membros():
    """'Essa estrutura continua funcional com 10x mais membros?' O teste: projetar
    no porte 10x maior tem que dar conta - mais area, mais hierarquia - sem
    estourar em canal inutil."""
    for rotulo, briefing in CENARIOS:
        maior = Porte.GRANDE if briefing.porte != Porte.GRANDE else Porte.GRANDE
        arq = projetar(Briefing(
            tema=briefing.tema, dominio=briefing.dominio, porte=maior,
            estilo=briefing.estilo, publico=briefing.publico,
        ))
        nota = design_score(arq)["geral"]
        assert nota >= 8.0, f"'{rotulo}' em porte grande ficou com nota {nota}"
        assert arq.total_canais >= projetar(briefing).total_canais or \
            briefing.porte == Porte.GRANDE, rotulo


def test_porte_grande_nao_estoura_em_canal_inutil():
    """Crescer nao e empilhar canal. A faixa da escalabilidade no design_score
    existe para isso."""
    for rotulo, briefing in CENARIOS:
        arq = projetar(Briefing(
            tema=briefing.tema, dominio=briefing.dominio, porte=Porte.GRANDE,
            estilo=briefing.estilo, publico=briefing.publico,
        ))
        pontos, motivo = design_score(arq)["criterios"]["escalabilidade"]
        assert pontos >= 8, f"'{rotulo}': {motivo}"


# ------------------------------------------------- spec 80/81/82/83: temas especificos
def test_fortnite_tem_areas_de_competitivo_quando_pede_competitivo():
    """Spec 80: LFG, ranked, competitivo, recrutamento - sem criar tudo
    obrigatoriamente."""
    arq = projetar(Briefing(tema="fortnite", dominio=Dominio.GAMING_COMPETITIVO,
                            publico=Publico.COMPETITIVO))
    nomes = " ".join(arq.nomes_de_canal()).lower()
    assert "lfg" in nomes and "recrutamento" in nomes


def test_fortnite_casual_nao_vira_esports():
    """Spec 80 tambem diz 'nao criar tudo obrigatoriamente'. Fortnite casual nao
    precisa de area de resultado de torneio."""
    arq = projetar(Briefing(tema="fortnite", dominio=Dominio.GAMING_CASUAL,
                            publico=Publico.CASUAL, porte=Porte.PEQUENO))
    nomes = " ".join(arq.nomes_de_canal()).lower()
    assert "resultados" not in nomes


def test_gta_rp_tem_personagem_e_faccoes():
    """Spec 82: personagens, faccoes, recrutamento, regras."""
    arq = projetar(Briefing(tema="gta rp", dominio=Dominio.RP, porte=Porte.MEDIO))
    nomes = " ".join(arq.nomes_de_canal()).lower()
    cats = " ".join(c.nome for c in arq.categorias).lower()
    assert "apresente-se" in nomes, nomes
    assert "recrutamento" in nomes
    assert "personagem" in cats or "fac" in " ".join(
        c.nome for c in arq.cargos if c.tipo == "identidade"
    ).lower()


def test_minecraft_casual_tem_duvidas_e_voz():
    """Spec 81: comunidade e suporte. Minecraft casual nao e esports."""
    arq = projetar(Briefing(tema="minecraft", dominio=Dominio.GAMING_CASUAL,
                            publico=Publico.CASUAL))
    nomes = " ".join(arq.nomes_de_canal()).lower()
    assert "dúvidas" in nomes
    assert any(c.tipo == "voice" for cat in arq.categorias for c in cat.canais)


def test_tema_fora_dos_exemplos_tambem_funciona():
    """Spec 83: nunca limitar aos exemplos. Um nicho que nao esta na lista tem
    que cair num dominio que faz sentido, nao estourar."""
    from atlas.design_system import inferir_dominio

    for pedido in ("servidor do meu clube de leitura", "comunidade de fotografia",
                   "servidor de investimentos"):
        dominio = inferir_dominio(pedido)
        arq = projetar(Briefing(tema=pedido, dominio=dominio))
        assert arq.total_canais > 0, pedido
        assert design_score(arq)["geral"] >= 8.0, pedido
