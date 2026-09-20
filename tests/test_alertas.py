"""Alertas (spec 122)."""

from __future__ import annotations

from atlas.alertas import (
    Alerta,
    ControladorDeAlerta,
    LimitesDeAlerta,
    Severidade,
    avaliar,
)


def _resumo(ok: int, falha: int) -> dict:
    return {"por_resultado": {"ok": ok, "error": falha}}


# ------------------------------------------------------- os seis gatilhos da spec
def test_erro_elevado_avisa():
    a = avaliar(resumo=_resumo(ok=70, falha=30))
    assert len(a) == 1 and a[0].codigo == "erro_elevado"
    assert a[0].severidade == Severidade.AVISO
    assert a[0].valor == 0.3


def test_erro_muito_alto_e_critico():
    a = avaliar(resumo=_resumo(ok=20, falha=80))
    assert a[0].severidade == Severidade.CRITICO


def test_amostra_pequena_nao_vira_alerta():
    """1 erro em 2 acoes e 50% e nao significa nada. Alerta falso treina todo
    mundo a ignorar o sistema."""
    assert avaliar(resumo=_resumo(ok=1, falha=1)) == []


def test_pool_degradado_e_fora_do_ar():
    degr = avaliar(ai={"rotas_fora": 2, "total_rotas": 12})
    assert degr[0].codigo == "pool_degradado" and degr[0].severidade == Severidade.AVISO
    morto = avaliar(ai={"rotas_fora": 11, "total_rotas": 12})
    assert morto[0].codigo == "pool_fora" and morto[0].severidade == Severidade.CRITICO


def test_fila_acumulada():
    assert avaliar(fila=30)[0].codigo == "fila_acumulada"
    assert avaliar(fila=3) == []


def test_tarefas_presas_e_critico():
    a = avaliar(tarefas_presas=2)
    assert a[0].codigo == "tarefas_presas" and a[0].severidade == Severidade.CRITICO


def test_rate_limited():
    assert avaliar(rate_limited=5)[0].codigo == "rate_limited"
    assert avaliar(rate_limited=1) == [], "um 429 isolado e rotina de provedor gratuito"


# ------------------------------------------------------------------- honestidade
def test_ausencia_de_dado_nao_vira_alerta():
    """Inventar alerta a partir de dado ausente seria falso positivo."""
    assert avaliar() == []
    assert avaliar(resumo=None, ai=None, fila=None, tarefas_presas=None) == []


def test_dado_mal_formado_nao_estoura():
    assert avaliar(resumo={"por_resultado": "lixo"}) == []
    assert avaliar(resumo={"por_resultado": {"ok": "x"}}) == []
    assert avaliar(ai={"rotas_fora": "?", "total_rotas": None}) == []
    assert avaliar(fila="muita") == []


def test_divisao_por_zero_nao_acontece():
    assert avaliar(resumo={"por_resultado": {}}) == []
    assert avaliar(ai={"rotas_fora": 5, "total_rotas": 0}) == []


def test_ordenacao_do_mais_grave_para_o_mais_leve():
    a = avaliar(
        resumo=_resumo(ok=10, falha=90),
        ai={"rotas_fora": 1, "total_rotas": 12},
        fila=40,
        tarefas_presas=1,
    )
    ordem = [x.severidade for x in a]
    assert ordem == sorted(ordem, key=lambda s: -{"info": 0, "aviso": 1, "critico": 2}[s.value])
    assert a[0].severidade == Severidade.CRITICO


def test_alerta_carrega_o_numero_que_o_disparou():
    """Sem o numero bruto o alerta e opiniao, nao medicao."""
    a = avaliar(resumo=_resumo(ok=70, falha=30))[0]
    assert a.valor == 0.3 and a.limite == 0.20


# ---------------------------------------------------------------------- cooldown
class _Relogio:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def test_mesmo_alerta_nao_repete_dentro_do_cooldown():
    """Spec 17 proibe spam. Alerta que dispara toda avaliacao vira ruido."""
    rel = _Relogio()
    ctrl = ControladorDeAlerta(cooldown_segundos=300.0, clock=rel)
    alerta = [Alerta("erro_elevado", Severidade.AVISO, "x")]
    assert ctrl.novos(alerta) == alerta
    ctrl.registrar_envio(alerta)
    assert ctrl.novos(alerta) == [], "segunda vez dentro da janela: silêncio"
    rel.t = 301.0
    assert ctrl.novos(alerta) == alerta, "passou a janela: volta a alertar"


def test_codigos_diferentes_nao_se_bloqueiam():
    rel = _Relogio()
    ctrl = ControladorDeAlerta(clock=rel)
    a = [Alerta("erro_elevado", Severidade.AVISO, "x")]
    b = [Alerta("fila_acumulada", Severidade.AVISO, "y")]
    ctrl.registrar_envio(a)
    assert ctrl.novos(a) == [] and ctrl.novos(b) == b


def test_rearmar_deixa_alertar_de_novo():
    """Problema que some e volta merece alerta, mesmo dentro da janela."""
    rel = _Relogio()
    ctrl = ControladorDeAlerta(clock=rel)
    alerta = [Alerta("pool_fora", Severidade.CRITICO, "x")]
    ctrl.registrar_envio(alerta)
    assert ctrl.novos(alerta) == []
    ctrl.rearmar("pool_fora")
    assert ctrl.novos(alerta) == alerta


def test_envio_que_falha_nao_silencia_o_alerta():
    """O caso que justifica separar as duas chamadas: se entregar falhar, o
    alerta nao foi entregue e nao pode entrar em cooldown - senao o problema
    some sem ninguem ter sido avisado."""
    rel = _Relogio()
    ctrl = ControladorDeAlerta(clock=rel)
    alerta = [Alerta("tarefas_presas", Severidade.CRITICO, "x")]
    assert ctrl.novos(alerta) == alerta
    # envio falhou: registrar_envio NAO foi chamado
    assert ctrl.novos(alerta) == alerta, "ainda tem que alertar"
    # agora entregou
    ctrl.registrar_envio(alerta)
    assert ctrl.novos(alerta) == []


def test_limites_sao_injetaveis():
    lim = LimitesDeAlerta(taxa_erro_aviso=0.05, minimo_para_taxa=2)
    assert avaliar(resumo=_resumo(ok=9, falha=1), limites=lim) != []
    assert avaliar(resumo=_resumo(ok=9, falha=1)) == [], "com default nao dispara"
