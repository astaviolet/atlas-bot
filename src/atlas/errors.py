"""Hierarquia de excecoes. O executor traduz tudo isso em embed de erro."""

from __future__ import annotations


class AtlasError(Exception):
    """Base. Tudo que o agente deve reportar ao usuario deriva daqui."""

    user_message: str = "Nao consegui concluir essa operacao."

    def __init__(self, message: str = "", *, user_message: str | None = None) -> None:
        super().__init__(message or self.__class__.__doc__ or self.__class__.__name__)
        if user_message is not None:
            self.user_message = user_message


class PolicyViolation(AtlasError):
    """Acao bloqueada pela politica de seguranca."""

    user_message = "Essa acao nao e permitida para este agente."


class GuildIsolationViolation(PolicyViolation):
    """Tentativa de agir fora do servidor da interacao."""

    user_message = "So posso trabalhar no servidor onde esta conversa esta acontecendo."


class ForbiddenAction(PolicyViolation):
    """Ferramenta proibida (moderacao de pessoas, spam, etc)."""

    user_message = "Essa ferramenta nao existe para este agente por seguranca."


class PermissionError_(AtlasError):
    """Falta permissao do Discord ou hierarquia impede."""

    user_message = "Nao tenho permissao no Discord para isso."


class HierarchyViolation(PermissionError_):
    """Alvo esta acima do cargo do bot."""

    user_message = "Esse alvo esta acima do meu cargo na hierarquia do Discord."


class RateLimited(AtlasError):
    """Cota de acoes estourada."""

    user_message = "Voce atingiu o limite de acoes por solicitacao. Vamos por partes."


class QuotaExceeded(RateLimited):
    """Plano grande demais para executar de uma vez."""

    user_message = "Esse pedido geraria acoes demais de uma vez. Peça em etapas menores."


class ConfirmationRequired(AtlasError):
    """Operacao destrutiva precisa de confirmacao explicita."""

    def __init__(self, message: str = "", *, summary: str = "", token: str = "") -> None:
        super().__init__(message)
        self.summary = summary
        self.token = token
        self.user_message = "Essa operacao e destrutiva e precisa de confirmacao."


class ToolError(AtlasError):
    """Parametro invalido ou falha ao aplicar a ferramenta."""

    user_message = "Nao consegui aplicar essa alteracao."


class NotFound(ToolError):
    """Objeto nao existe no servidor."""

    user_message = "Nao encontrei esse item no servidor."


class GatewayError(AtlasError):
    """A API do Discord falhou."""

    user_message = "A API do Discord retornou um erro."


class AIError(AtlasError):
    """A camada de IA falhou (provedor, gateway, timeout, cota ou modelo)."""

    user_message = "A camada de IA nao respondeu."


class PromptInjectionBlocked(PolicyViolation):
    """Tentativa de sobrescrever as regras do sistema."""

    user_message = "Instrucoes vindas da conversa nao mudam minhas regras."
