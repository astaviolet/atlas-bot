"""View de botões para Components V2 (spec 73).

Separado de `botoes.py` de propósito: `botoes.py` tem a validação pura (testada,
15 casos), este arquivo só tem a cola com discord.py. Se a validação morasse
aqui, ela nunca seria testada — e botão de confirmação não testado é o mesmo que
não ter confirmação.

O callback NÃO decide nada por conta própria. Ele traduz a interação em dados,
chama `validar_clique`, e age conforme o veredito.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from .botoes import ACAO_CANCELAR, ACAO_CONFIRMAR, mensagem_de_recusa, montar_custom_id, validar_clique

log = logging.getLogger(__name__)


class BotoesConfirmacao:
    """Dois botões — confirmar e cancelar — amarrados ao token do plano.

    `timeout=None` porque o prazo real é o da confirmação (`confirmation_ttl`),
    não o da view. Deixar a view expirar sozinha faria o botão sumir da tela
    antes do prazo, e o usuário ficaria sem entender por quê.
    """

    def __init__(
        self,
        *,
        token: str,
        guild_id: int,
        ao_decidir: Callable[[Any, str, Any], Awaitable[None]],
        sessions: Any = None,
    ) -> None:
        self.token = token
        self.guild_id = guild_id
        self._ao_decidir = ao_decidir
        self._sessions = sessions

    def anexar_em(self, view: Any) -> None:
        """Acrescenta a fileira de botões ao container Components V2.

        Falha aqui não pode deixar o usuário sem resposta: sem botão ele ainda
        confirma por texto ("sim"/"não"), que continua funcionando.
        """
        try:
            view_botoes = _View(self, timeout=None)
            for item in view_botoes.children:
                view.add_item(item)
        except Exception:  # noqa: BLE001 - botao e conveniencia, nao requisito
            log.warning("nao deu para anexar os botoes; confirmacao por texto segue valendo",
                        exc_info=True)

    async def ao_clicar(self, interacao: Any) -> None:
        custom_id = getattr(getattr(interacao, "data", None), "custom_id", "") or ""
        session = self._resolver_sessao(interacao)
        if session is None:
            await interacao.response.send_message(
                mensagem_de_recusa("sem_confirmacao_pendente"), ephemeral=True
            )
            return

        veredito = validar_clique(
            custom_id=custom_id,
            guild_id_clique=getattr(interaction_guild(interacao), "id", None),
            user_id_clique=getattr(getattr(interacao, "user", None), "id", None),
            session=session,
        )
        if not veredito.ok:
            log.warning("clique recusado (%s) no guild %s", veredito.motivo, self.guild_id)
            await interacao.response.send_message(
                mensagem_de_recusa(veredito.motivo), ephemeral=True
            )
            return

        await self._ao_decidir(interacao, veredito.decidir, session)

    def _resolver_sessao(self, interacao: Any) -> Any:
        if self._sessions is None:
            return None
        guild = interaction_guild(interacao)
        canal = getattr(interacao, "channel", None)
        if guild is None or canal is None:
            return None
        return self._sessions.get(guild.id, canal.id)


def interaction_guild(interacao: Any) -> Any:
    """Guild REAL da interação. Nunca um campo do payload (spec 7)."""
    return getattr(interacao, "guild", None)


class _View:
    """Construída sob demanda dentro de `anexar_em` para não importar discord
    na hora de instanciar — assim este módulo continua importável em teste."""

    def __new__(cls, dono: "BotoesConfirmacao", timeout: float | None = None) -> Any:
        import discord

        class View(discord.ui.LayoutView):
            pass

        view = View(timeout=timeout)

        confirmar = discord.ui.Button(
            label="Confirmar",
            style=discord.ButtonStyle.success,
            custom_id=montar_custom_id(ACAO_CONFIRMAR, dono.token),
        )
        cancelar = discord.ui.Button(
            label="Cancelar",
            style=discord.ButtonStyle.secondary,
            custom_id=montar_custom_id(ACAO_CANCELAR, dono.token),
        )

        async def _callback(interacao: Any, _botao: Any = None) -> None:
            await dono.ao_clicar(interacao)

        confirmar.callback = _callback
        cancelar.callback = _callback

        linha = discord.ui.ActionRow()
        linha.add_item(confirmar)
        linha.add_item(cancelar)
        view.add_item(linha)
        return view
