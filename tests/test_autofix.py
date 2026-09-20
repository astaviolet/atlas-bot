"""Auto-correcao pos-verificacao (spec 25)."""

from __future__ import annotations

from conftest import final, turn

from atlas.autofix import corrigir, diferenca


# ------------------------------------------------------- o que pode ser corrigido
def test_nome_longo_e_cortado():
    novo = corrigir("nome longo", {"name": "a" * 150}, max_name_len=100)
    assert novo is not None
    assert len(novo["name"]) == 100
    assert novo["name"].endswith("…"), "o usuario tem que ver que foi cortado"


def test_topico_longo_e_cortado():
    novo = corrigir("topico longo", {"topic": "t" * 2000}, max_topic_len=1024)
    assert novo is not None and len(novo["topic"]) == 1024


def test_slowmode_fora_da_faixa_e_limitado():
    assert corrigir("slowmode fora da faixa", {"slowmode": 99999})["slowmode"] == 21600
    assert corrigir("slowmode fora da faixa", {"slowmode": -5})["slowmode"] == 0


def test_tipo_em_portugues_e_traduzido():
    assert corrigir("tipo de canal invalido", {"type": "voz"})["type"] == "voice"
    assert corrigir("tipo de canal invalido", {"type": "Texto"})["type"] == "text"
    assert corrigir("tipo de canal invalido", {"type": "anúncio"})["type"] == "announcement"


def test_nsfw_em_canal_de_voz_e_removido():
    novo = corrigir("voz nao aceita nsfw", {"name": "voz", "type": "voice", "nsfw": True})
    assert novo is not None and "nsfw" not in novo


def test_tipo_desconhecido_nao_vira_chute():
    """Se nao e sinonimo inequivoco, falha. Escolher por ele seria inventar."""
    assert corrigir("tipo de canal invalido", {"type": "telepatia"}) is None


# ------------------------------------------------- o que NAO pode ser corrigido
def test_nome_vazio_nao_e_inventado():
    """Spec 185: correcao corrige, nao inventa. Nao existe nome certo a deduzir."""
    assert corrigir("nome vazio", {"name": ""}) is None
    assert corrigir("nome vazio", {}) is None


def test_erro_desconhecido_nao_dispara_nada():
    assert corrigir("categoria nao existe", {"category_id": "1"}) is None
    assert corrigir("", {"name": "ok"}) is None


def test_correcao_nao_muta_o_original():
    """Quem chama precisa do 'antes' para auditar."""
    original = {"name": "a" * 150}
    corrigir("nome longo", original, max_name_len=100)
    assert len(original["name"]) == 150


def test_diferenca_mostra_so_o_que_mudou():
    d = diferenca({"name": "a" * 150, "type": "text"},
                  {"name": "a" * 99 + "…", "type": "text"})
    assert list(d) == ["name"]
    assert d["name"]["depois"].endswith("…")


# ---------------------------------------------------------------- ponta a ponta
def test_nome_longo_de_verdade_e_corrigido_e_criado(harness):
    """O caminho inteiro: tool recusa, autofix corta, tool aceita."""
    nome = "canal-com-um-nome-absurdamente-longo-" + "x" * 200
    h = harness([turn(("create_channel", {"name": nome, "type": "text"})), final("ok")],
                seed=False)
    out = h.ask("cria esse canal")

    assert len([r for r in out.results if r.ok]) == 1, "tinha que ter sido criado"
    esperado = corrigir("nome longo", {"name": nome}, max_name_len=h.limits.max_name_len)["name"]
    criado = h.find_channel_id(esperado)
    assert criado is not None, f"o canal cortado ({esperado!r}) tem que existir no gateway"
    assert len(esperado) == h.limits.max_name_len


def test_autofix_tenta_uma_vez_so(harness):
    """Sem laco: se a correcao tambem falhar, o erro vai pro usuario."""
    from atlas.autofix import corrigir as original

    h = harness([turn(("create_channel", {"name": "y" * 150, "type": "text"})), final("ok")],
                seed=False)
    chamadas = []

    def contando(motivo, params, **kw):
        chamadas.append(motivo)
        return original(motivo, params, **kw)

    import atlas.queue as fila
    fila.corrigir = contando
    try:
        out = h.ask("cria esse canal")
    finally:
        fila.corrigir = original

    assert chamadas == ["nome longo"], f"uma tentativa so, veio {chamadas}"
    assert len([r for r in out.results if r.ok]) == 1


def test_autofix_fica_no_audit(harness):
    """Correcao silenciosa e indistinguivel de bug: tem que estar no log."""
    h = harness([turn(("create_channel", {"name": "z" * 150, "type": "text"})), final("ok")],
                seed=False)
    h.ask("cria esse canal")

    eventos = [r for r in h.audit.records if r["action"] == "autofix.retry"]
    assert eventos, "o autofix tem que aparecer na auditoria"
    assert eventos[0]["params"]["motivo"] == "nome longo"
    assert "name" in eventos[0]["params"]["mudanca"]
