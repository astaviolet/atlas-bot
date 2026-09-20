"""Conferência factual da resposta (spec 185: resposta falsa é proibida).

Origem: medição em produção no servidor real "Pinguim". Pedido "quantos canais e
cargos tem esse servidor?", índice real no prompt (8 canais, 6 cargos), zero tool
call, e a modelo respondeu "11 canais e 10 cargos". Números inventados com a
verdade na frente dela.
"""

from __future__ import annotations

from atlas.conferencia import conferir_contagem, contagens_reais
from atlas.models import Channel, ChannelType, GuildSnapshot, Role


def _snapshot(n_texto: int = 6, n_categoria: int = 1, n_cargo: int = 6) -> GuildSnapshot:
    canais: list[Channel] = [
        Channel(id=1, name="atlas-config", type=ChannelType.GUILD_TEXT)
    ]
    nid = 2
    for i in range(n_categoria):
        canais.append(Channel(id=nid, name=f"CAT{i}", type=ChannelType.GUILD_CATEGORY))
        nid += 1
    for i in range(n_texto):
        canais.append(Channel(id=nid, name=f"texto-{i}", type=ChannelType.GUILD_TEXT,
                              parent_id=2))
        nid += 1
    cargos = [Role(id=i, name=f"c{i}", position=i, permissions=0) for i in range(n_cargo)]
    return GuildSnapshot(id=1, name="P", owner_id=1, bot_role_id=4, bot_permissions=0,
                         channels=canais, roles=cargos)


def test_contagens_reais_separa_categoria_de_canal():
    reais = contagens_reais(_snapshot(n_texto=6, n_categoria=1, n_cargo=6))
    assert reais["canais"] == 7, "1 solto + 6 dentro da categoria"
    assert reais["canais_com_categoria"] == 8, "é o que a API do Discord devolve"
    assert reais["categorias"] == 1
    assert reais["cargos"] == 6


def test_corrige_o_caso_real_medido_em_producao():
    """Este é o bug que motivou o módulo. 11 e 10 não existem no servidor."""
    novo, div = conferir_contagem("11 canais e 10 cargos.", _snapshot())
    assert "7 canais" in novo
    assert "6 cargos" in novo
    assert len(div) == 2, f"tinha que apontar as duas: {div}"


def test_nao_mexe_quando_a_contagem_esta_certa():
    texto = "Tem 7 canais e 6 cargos."
    novo, div = conferir_contagem(texto, _snapshot())
    assert novo == texto
    assert div == []


def test_aceita_as_duas_contagens_de_canal():
    """O Discord lista categoria como canal (8), o índice do prompt separa (7+1).
    As duas leituras são defensáveis. 'Corrigir' 8 para 7 seria introduzir um
    erro novo em cima do que estou tentando tirar."""
    snap = _snapshot()
    assert conferir_contagem("8 canais.", snap)[1] == []
    assert conferir_contagem("7 canais.", snap)[1] == []


def test_texto_sem_contagem_passa_intacto():
    texto = "Criei o canal de avisos dentro de INFORMAÇÕES."
    novo, div = conferir_contagem(texto, _snapshot())
    assert novo == texto
    assert div == []


def test_nao_estoura_sem_snapshot():
    assert conferir_contagem("11 canais.", None) == ("11 canais.", [])


def test_singular_tambem_e_conferido():
    novo, div = conferir_contagem("Tem 1 categoria só.", _snapshot())
    assert div == []
    novo, div = conferir_contagem("Tem 9 categoria.", _snapshot())
    assert div, "9 categorias não existe"


def test_numero_grande_inventado_e_pego():
    """Caso extremo: a modelo chuta um número absurdo."""
    novo, div = conferir_contagem("O servidor tem 999 canais.", _snapshot())
    assert div and "999" in div[0]
    assert "999" not in novo


def test_acento_nao_atrapalha_a_deteccao():
    """Com e sem acento tem que casar igual. O snapshot tem 1 categoria, então
    '1 categoria' passa e '5 categorias' diverge — nas duas grafias."""
    assert conferir_contagem("1 categoria.", _snapshot())[1] == []
    assert conferir_contagem("5 categorias.", _snapshot())[1] != []
    # sem acento: a comparação normaliza, então continua pegando
    assert conferir_contagem("5 categorias", _snapshot())[1] != []


def test_correcao_nao_vaza_para_a_resposta_do_usuario():
    """A regra permanente é resposta curta e sem ruído interno. A divergência
    vai para o log, não para o embed — o usuário vê só o número certo."""
    novo, div = conferir_contagem("11 canais e 10 cargos.", _snapshot())
    assert "divergência" not in novo.lower()
    assert "contradiz" not in novo.lower()
    assert div, "a divergência tem que existir para ir ao log"
