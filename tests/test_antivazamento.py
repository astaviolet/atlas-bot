"""Filtro de vazamento na saída (spec 112)."""

from __future__ import annotations

from atlas.antivazamento import (
    assinaturas_internas,
    filtrar,
    tem_vazamento,
)

PROMPT = """VOCE E UM AGENTE DE CONFIGURACAO DE SERVIDORES DISCORD.
Nunca conceda permissao de ADMINISTRATOR a um cargo novo.
Voce opera apenas no servidor da interacao atual e nunca em outro.
ok
---
"""


def test_detecta_vazamento_do_prompt():
    assin = assinaturas_internas(PROMPT)
    vazada = "Claro! Minhas regras: Nunca conceda permissao de ADMINISTRATOR a um cargo novo."
    limpo, removidos = filtrar(vazada, assin)
    assert removidos, "tinha que pegar"
    assert "Nunca conceda" not in limpo
    assert "[trecho interno omitido]" in limpo


def test_nao_censura_resposta_legitima():
    """A spec 112 diz que pode explicar decisoes de forma resumida. Um filtro que
    censura tudo e inutil: o usuario fica sem resposta."""
    assin = assinaturas_internas(PROMPT)
    legitima = "Criei 3 categorias e 8 canais. Não dei permissão de administrador a nenhum cargo."
    limpo, removidos = filtrar(legitima, assin)
    assert removidos == [], removidos
    assert limpo == legitima


def test_ignora_caixa_e_quebra_de_linha():
    """O contorno mais facil que existe: devolver o prompt com outra caixa ou uma
    quebra a mais. Se o filtro comparar literal, ele deixa passar."""
    assin = assinaturas_internas(PROMPT)
    # mesma frase do prompt, so com caixa e quebra diferentes
    variante = "nunca conceda   PERMISSAO de\nADMINISTRATOR a um cargo novo."
    assert tem_vazamento(variante, assin)
    # e uma palavra diferente NAO pode casar, senao o filtro vira censura
    assert not tem_vazamento("nunca conceda permissao de moderador a um cargo novo.", assin)


def test_linha_curta_nao_vira_assinatura():
    """Linha curta censuraria resposta legitima. 'ok' e '---' nao identificam
    nada."""
    assin = assinaturas_internas(PROMPT)
    assert all(len(a) >= 40 for a in assin)
    assert not any(a in ("ok", "---") for a in assin)


def test_marcador_de_raciocinio_e_removido():
    for marcador in (
        "<thinking>vou analisar o pedido</thinking>",
        "Vamos pensar passo a passo sobre isso.",
        "chain of thought: primeiro eu leio o servidor",
    ):
        limpo, removidos = filtrar(marcador, [])
        assert removidos, marcador
        assert "thinking" not in limpo.lower() or "omitido" in limpo


def test_texto_vazio_nao_estoura():
    assert filtrar("", []) == ("", [])
    assert filtrar("", None) == ("", [])
    assert not tem_vazamento("", [])


def test_prompt_vazio_nao_quebra():
    assert assinaturas_internas("") == []
    assert assinaturas_internas(None) == []
    texto = "resposta normal"
    assert filtrar(texto, assinaturas_internas("")) == (texto, [])


def test_multiplos_vazamentos_sao_todos_removidos():
    assin = assinaturas_internas(PROMPT)
    vazada = (
        "Minhas regras: Nunca conceda permissao de ADMINISTRATOR a um cargo novo. "
        "E também: Voce opera apenas no servidor da interacao atual e nunca em outro."
    )
    limpo, removidos = filtrar(vazada, assin)
    assert len(removidos) >= 2, removidos
    assert "ADMINISTRATOR a um cargo novo" not in limpo


# ---------------------------------------------------- contra o prompt de verdade
def test_prompt_de_sistema_real_e_protegido():
    """O caso que importa: o prompt que o bot monta de verdade, nao um de
    brinquedo. Se alguem trocar o prompt e o filtro continuar protegendo, otimo;
    se o filtro deixar de pegar, este teste falha."""
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
    prompt = build_system_prompt(ctx.snapshot, build_registry(), pol)
    assin = assinaturas_internas(prompt)
    assert assin, "o prompt real tem que gerar assinatura"

    # pega uma linha real do prompt e finge que o modelo devolveu
    linha = next(l for l in prompt.splitlines() if len(l.strip()) >= 40)
    assert tem_vazamento(f"Aqui esta: {linha}", assin)


def test_limpar_filtra_vazamento_do_prompt_real():
    """Ligacao de ponta a ponta: build_system_prompt registra as assinaturas e
    limpar() - por onde toda saida passa - filtra. Sem este teste o modulo
    existiria sem estar ligado, que foi o erro das Fases 21 e 25."""
    from atlas.config import Limits
    from atlas.policy import ActionBudget, Policy
    from atlas.prompts import build_system_prompt
    from atlas.testing.fake_gateway import FakeGateway
    from atlas.texto import limpar
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
    prompt = build_system_prompt(ctx.snapshot, build_registry(), pol)
    linha = next(l for l in prompt.splitlines() if len(l.strip()) >= 60)

    saida = limpar("Minhas regras: " + linha)
    assert linha[:40] not in saida, saida
    assert "omitido" in saida

    # resposta legitima continua intacta
    legitima = "Criei 3 categorias e 8 canais, sem dar admin a nenhum cargo."
    assert limpar(legitima) == legitima
