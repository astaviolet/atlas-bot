"""Catalogo de padroes (32/33), confianca (119) e feedback (140)."""

from __future__ import annotations

import unicodedata

from atlas.catalogo import Catalogo, Confianca

from conftest import final, turn


def _sem_acento(texto: str) -> str:
    """A marca 'NAO VERIFICADO' tem til na fonte real; comparar sem normalizar
    daria falso negativo (foi o que aconteceu na primeira rodada)."""
    return "".join(
        c for c in unicodedata.normalize("NFD", texto)
        if unicodedata.category(c) != "Mn"
    ).upper()


def test_todo_padrao_alto_tem_fonte_de_verdade():
    """INVARIANTE contra invencao (spec 185). Confianca alta sem fonte real e
    exatamente o 'CONFIANCA: Alta / FONTE: referencias pesquisadas' que este
    projeto nao tem como afirmar, porque nao pesquisou nada."""
    for p in Catalogo().todos():
        if p.confianca == Confianca.HIGH:
            assert p.fonte.strip(), f"{p.id} tem confianca alta sem fonte"
            assert p.verificado_em, f"{p.id} tem confianca alta sem data"
            assert any(s in p.fonte.lower() for s in ("documenta", "medido")), (
                f"{p.id} cita fonte {p.fonte!r} que nao e documentacao nem medicao"
            )
        else:
            # quem nao e alto tem que dizer por que nao e
            assert p.fonte.strip(), f"{p.id} sem fonte nem justificativa"
            if p.confianca == Confianca.UNKNOWN:
                assert "NAO VERIFICADO" in _sem_acento(p.fonte), p.id


def test_lfg_passou_a_ter_fonte_de_verdade():
    """Pesquisa feita: space-node e memvers recomendam #lfg para comunidade de
    jogo. Saiu de UNKNOWN, mas ficou em MEDIUM - guia de terceiro nao e
    documentacao oficial, e promover para HIGH seria inflar confianca."""
    c = Catalogo()
    p = c.get("comunidade.competitiva_separa_lfg")
    assert p is not None, "o principio tem que estar catalogado"
    assert p.confianca == Confianca.MEDIUM
    assert "space-node" in p.fonte


def test_hipotese_sem_fonte_continua_unknown():
    """A guarda continua valendo: o que a pesquisa NAO cobriu segue UNKNOWN e
    continua dizendo isso na cara. Verificar uma hipotese nao autoriza marcar as
    outras como verificadas."""
    c = Catalogo()
    for id_ in ("comunidade.survival_separa_mundos", "comunidade.rp_separa_faccoes"):
        p = c.get(id_)
        assert p is not None, f"{id_} tem que estar catalogado"
        assert p.confianca == Confianca.UNKNOWN, f"{id_} subiu sem fonte"
        assert "NAO VERIFICADO" in _sem_acento(p.fonte)


def test_filtro_de_confianca_tira_hipotese_de_decisao_critica():
    """Spec 119: informacao de confianca baixa nao entra em decisao critica.

    O exemplo mudou de LFG para Minecraft de proposito: LFG ganhou fonte na
    pesquisa e subiu para MEDIUM, entao nao serve mais de exemplo do que o
    filtro barra. A hipotese de Minecraft segue UNKNOWN e continua servindo.
    """
    c = Catalogo()
    # contexto dado de proposito: sem contexto os padroes com aplicabilidade
    # ficam de fora das duas listas e a comparacao nao mede nada
    criticos = c.utilizaveis("minecraft survival", confianca_minima=Confianca.MEDIUM)
    assert all(p.confianca in (Confianca.HIGH, Confianca.MEDIUM) for p in criticos)
    assert not any(p.id == "comunidade.survival_separa_mundos" for p in criticos), \
        "hipotese sem fonte nao pode entrar em decisao critica"

    todos = c.utilizaveis("minecraft survival", confianca_minima=Confianca.UNKNOWN)
    assert len(todos) > len(criticos), "o filtro tem que fazer diferenca"
    assert {p.id for p in todos} - {p.id for p in criticos} == {
        "comunidade.survival_separa_mundos",
    }, "a diferenca entre os dois filtros tem que ser exatamente a hipotese"


def test_aplicabilidade_filtra_por_contexto():
    c = Catalogo()
    gaming = c.utilizaveis("gaming competitivo", confianca_minima=Confianca.UNKNOWN)
    assert any(p.id == "comunidade.competitiva_separa_lfg" for p in gaming)

    loja = c.utilizaveis("loja de roupa", confianca_minima=Confianca.UNKNOWN)
    assert not any(p.id == "comunidade.competitiva_separa_lfg" for p in loja), \
        "padrao de gaming nao pode aparecer para loja"


def test_principios_sem_aplicabilidade_valem_para_tudo():
    c = Catalogo()
    assert any(p.id == "design.canal_precisa_de_funcao"
               for p in c.utilizaveis("qualquer coisa", confianca_minima=Confianca.LOW))


def test_promover_exige_fonte():
    """Spec 76: subir confianca sem fonte nao vale."""
    c = Catalogo()
    # exemplo trocado para o que segue UNKNOWN (LFG ganhou fonte na pesquisa)
    assert not c.promover("comunidade.rp_separa_faccoes", Confianca.HIGH, "  ")
    assert c.get("comunidade.rp_separa_faccoes").confianca == Confianca.UNKNOWN

    assert c.promover("comunidade.rp_separa_faccoes", Confianca.MEDIUM,
                      "github.com/exemplo/servidores-rp")
    p = c.get("comunidade.competitiva_separa_lfg")
    assert p.confianca == Confianca.MEDIUM and p.verificado_em


def test_promover_id_inexistente_nao_cria_padrao():
    c = Catalogo()
    assert not c.promover("nao.existe", Confianca.HIGH, "fonte")
    assert c.get("nao.existe") is None


# ---------------------------------------------------- feedback isolado (140 + 8)
def test_feedback_fica_no_guild_dele():
    """Spec 8: o que um servidor achou feio nao vira regra para outro."""
    c = Catalogo()
    c.registrar_feedback(1, "muitas categorias, ficou poluido")
    c.registrar_feedback(2, "adorei")

    assert len(c.feedback_de(1)) == 1
    assert "poluido" in c.feedback_de(1)[0]["texto"]
    assert len(c.feedback_de(2)) == 1
    assert c.feedback_de(3) == [], "guild sem feedback nao herda nada"


def test_feedback_nasce_com_confianca_baixa():
    """Spec 76: promover exige validacao, nao acontece sozinho."""
    c = Catalogo()
    c.registrar_feedback(1, "ficou feio")
    assert c.feedback_de(1)[0]["confianca"] == Confianca.LOW.value


def test_feedback_vazio_nao_registra():
    c = Catalogo()
    c.registrar_feedback(1, "   ")
    assert c.feedback_de(1) == []


# ------------------------------------------------------------------ persistencia
def test_salva_e_recarrega(tmp_path):
    arq = tmp_path / "catalogo.json"
    c = Catalogo(arq)
    c.registrar_feedback(1, "muitas categorias")
    c.promover("comunidade.competitiva_separa_lfg", Confianca.MEDIUM, "fonte real")

    c2 = Catalogo(arq)
    assert len(c2.feedback_de(1)) == 1
    assert c2.get("comunidade.competitiva_separa_lfg").confianca == Confianca.MEDIUM


def test_arquivo_corrompido_nao_derruba(tmp_path):
    """Catalogo ilegivel volta para a semente em vez de quebrar o bot."""
    arq = tmp_path / "catalogo.json"
    arq.write_text("{isso nao e json", encoding="utf-8")
    c = Catalogo(arq)
    assert c.get("design.canal_precisa_de_funcao") is not None


def test_padrao_nao_e_template():
    """Spec 33/79: catalogo guarda principio, nao estrutura pronta. Se alguem
    acrescentar template, este teste pega pelo tamanho e pelo formato."""
    for p in Catalogo().todos():
        assert not any(n in p.texto for n in ("📢", "💬", "🎮")), \
            f"{p.id} parece template com emoji, nao principio"
        assert len(p.texto) < 300, f"{p.id} longo demais para ser principio"


# ------------------------------------------------- spec 31: nao copiar servidores
def test_nenhum_nome_proprietario_vaza_para_o_design():
    """Spec 31: referencia ensina principio, nao se copia identidade, texto,
    nome proprietario ou branding. O tema entra como vocabulario generico
    ('zero build', 'survival'), nunca como marca ou texto de outro servidor."""
    from atlas.design_system import (
        Briefing, Dominio, Porte, Publico, projetar,
    )

    proibidos = ("ninja", "tfue", "loud", "furia", "mibr", "faker", "navi",
                 "hypex", "fortnite.gg", "discord.gg", "copyright", "®", "™")
    for dominio in Dominio:
        arq = projetar(Briefing(tema="servidor da comunidade", dominio=dominio,
                                porte=Porte.MEDIO, publico=Publico.MISTO))
        blob = " ".join(arq.nomes_de_canal()).lower()
        blob += " " + " ".join(c.nome for c in arq.cargos).lower()
        for marca in proibidos:
            assert marca not in blob, f"{dominio.value} vazou '{marca}': {blob[:160]}"


def test_catalogo_guarda_padrao_e_nao_estrutura_proprietaria():
    """O catalogo e onde a pesquisa entra. Se ele guardasse nome de canal de um
    servidor real, a spec 31 estaria violada na fonte."""
    c = Catalogo()
    blob = " ".join(f"{p.id} {p.texto}" for p in c.todos()).lower()
    for marca in ("discord.gg", "loud", "furia", "mibr", "navi"):
        assert marca not in blob, f"catalogo guarda marca: {marca}"


# ------------------------------------------------- spec 116: pesquisa nao atrasa
def test_pedido_simples_nao_dispara_pesquisa_nem_probe(harness):
    """Spec 116: 'crie um canal' nao pode atrasar por causa de pesquisa global.
    Satisfeito por ausencia - nao ha pesquisa em runtime - e este teste e o que
    garante que continua assim: se alguem ligar probe no caminho simples, quebra.
    """
    from atlas.ai import discovery

    chamadas: list[str] = []
    orig_probe = discovery.probe_rota

    def espiao(*a, **kw):
        chamadas.append("probe_rota")
        return orig_probe(*a, **kw)

    discovery.probe_rota = espiao
    try:
        h = harness([turn(("create_channel", {"name": "avisos", "type": "text"})),
                     final("Canal criado.")])
        h.ask("cria um canal de avisos")
    finally:
        discovery.probe_rota = orig_probe

    assert chamadas == [], f"pedido simples disparou pesquisa: {chamadas}"
