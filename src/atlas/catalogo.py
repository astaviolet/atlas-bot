"""Catálogo de padrões (spec 32/33), confiança (spec 119) e feedback (spec 140).

A REGRA QUE DEFINE ESTE MÓDULO
------------------------------
A spec 32 mostra como exemplo de padrão: "comunidades competitivas normalmente
precisam separar LFG, competitivo, resultados e recrutamento", com CONFIANÇA:
Alta e FONTE: Referências pesquisadas.

**Este projeto não pesquisou nada.** Pesquisa na web está fora do escopo por
decisão explícita do usuário (a lista de 21 tools é fechada). Então eu não tenho
fonte para afirmar isso com confiança alta — e escrever CONFIANÇA: Alta sem ter
pesquisado seria exatamente a "configuração inventada" que a spec 185 proíbe.

O que este módulo faz, então:
- guarda os padrões que **têm** fonte real (limite da API do Discord,
  comportamento medido deste sistema) com a fonte e a confiança verdadeiras;
- guarda os padrões de design de comunidade como **NÃO VERIFICADO**, para que
  fiquem visíveis como hipótese em vez de passarem por conhecimento;
- `utilizaveis(confianca_minima=...)` filtra, então nada de confiança baixa
  entra em decisão crítica sem validação — que é a spec 119 ao pé da letra.

Quando a pesquisa entrar, o campo `fonte` recebe a referência e a confiança sobe.
A estrutura já está pronta; o que falta é dado, não código.

PRINCÍPIOS, NÃO TEMPLATES (spec 33)
-----------------------------------
Cada entrada é um princípio ("canal sem função clara não deve existir"), nunca
uma estrutura pronta ("servidor de Fortnite tem estes 27 canais"). Template fixo
é o que a spec 27 e a 79 proíbem, e foi o que a medição da Fase 5 mostrou que o
modelo faz sozinho quando recebe template.

FEEDBACK É POR GUILD (spec 140 + spec 8)
----------------------------------------
"Este servidor achou muitas categorias excessivo" é dado daquele servidor.
Aplicar a outro automaticamente seria vazamento entre guilds. Por isso o
feedback fica isolado por `guild_id` e entra como LOW — promover exige validação
(spec 76), não acontece sozinho.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


class Confianca(str, Enum):
    """Spec 119."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNKNOWN = "unknown"


_ORDEM = {
    Confianca.HIGH: 3,
    Confianca.MEDIUM: 2,
    Confianca.LOW: 1,
    Confianca.UNKNOWN: 0,
}


@dataclass
class Padrao:
    id: str
    texto: str
    aplicabilidade: list[str] = field(default_factory=list)
    confianca: Confianca = Confianca.UNKNOWN
    fonte: str = ""
    verificado_em: float | None = None

    def utilizavel_para(self, contexto: str | None) -> bool:
        if not self.aplicabilidade:
            return True
        if contexto is None:
            return False
        alvo = contexto.strip().casefold()
        return any(a.strip().casefold() in alvo or alvo in a.strip().casefold()
                   for a in self.aplicabilidade)


def _p(id_: str, texto: str, aplicabilidade: list[str], confianca: Confianca,
       fonte: str) -> Padrao:
    return Padrao(id=id_, texto=texto, aplicabilidade=aplicabilidade,
                  confianca=confianca, fonte=fonte,
                  verificado_em=time.time() if confianca != Confianca.UNKNOWN else None)


#: Semente. Só o que tem fonte de verdade.
_SEMENTE: list[Padrao] = [
    # --- limites reais da API, documentados pelo Discord -------------------
    _p("api.limite.nome_guild",
       "Nome de servidor tem de 2 a 100 caracteres.",
       [], Confianca.HIGH, "documentação oficial do Discord (resources/guild)"),
    _p("api.limite.nome_canal",
       "Nome de canal tem de 1 a 100 caracteres.",
       [], Confianca.HIGH, "documentação oficial do Discord (resources/channel)"),
    _p("api.limite.topico",
       "Tópico de canal tem de 0 a 1024 caracteres.",
       [], Confianca.HIGH, "documentação oficial do Discord (resources/channel)"),
    _p("api.categoria_maiuscula",
       "O Discord grava nome de categoria em caixa alta; buscar categoria por "
       "nome tem que comparar sem diferenciar maiúscula.",
       [], Confianca.HIGH, "medido neste projeto (Fase 14)"),

    # --- comportamento medido deste sistema --------------------------------
    _p("sistema.prompt_nao_segura_design",
       "Instrução longa de design no prompt não garante resultado: o pool "
       "gratuito devolveu template genérico e canais duplicados mesmo com a "
       "doutrina no contexto. Regra de design tem que ser imposta em código.",
       [], Confianca.HIGH, "medido neste projeto (Fase 5, 25,1s com IA real)"),
    _p("sistema.duplicacao_e_o_risco_real",
       "Sem reuso por nome, o mesmo canal é criado duas vezes quando o modelo "
       "repete a intenção em voltas diferentes.",
       [], Confianca.HIGH, "medido neste projeto (auditoria Fase 0)"),

    # --- princípios de design: válidos como princípio, sem fonte pesquisada -
    _p("design.canal_precisa_de_funcao",
       "Canal sem função clara não deve ser criado; preencher espaço não é "
       "organização.",
       [], Confianca.MEDIUM,
       "space-node.net/blog/discord-server-templates-layout-guide-2026 "
       "('empty channels make a server feel dead') + memvers.com "
       "('an active server with 10 channels beats a dead one with 40')"),
    _p("design.escala_define_granularidade",
       "Arquitetura depende do tamanho da comunidade: até 500 membros, 8 a 15 "
       "canais em 4 a 5 categorias; de 500 a 5 mil, 15 a 25; acima de 5 mil, 20 "
       "a 35 com canais de fórum. O que funciona para 50 mil não funciona para "
       "50.",
       [], Confianca.MEDIUM,
       "memvers.com/blog/discord-server-setup-guide-2026 (tabela de canais por "
       "tamanho e 'copying big servers exactly - what works for 50K doesn't "
       "work for 50')"),
    _p("design.poucos_canais_por_categoria",
       "Cerca de 4 a 5 canais por categoria; mais que isso vira parede de texto "
       "e a seção deixa de ser navegável.",
       [], Confianca.MEDIUM,
       "siift.ai/blog/channels-discord, citando orientação de comunidade do "
       "Discord (fonte de segunda mão, não o documento oficial)"),
    _p("design.ordem_das_categorias",
       "Ordem de cima para baixo: informação/regras, comunidade, temas "
       "específicos, voz, equipe. A lista fica mais específica conforme o membro "
       "desce.",
       [], Confianca.MEDIUM,
       "peakbot.pro/blog/how-to-organize-discord-channels-and-categories e "
       "memvers.com/blog/discord-server-setup-guide-2026 (guias de terceiros "
       "concordando entre si, não documento oficial do Discord)"),
    _p("design.info_somente_leitura",
       "Boas-vindas, regras e avisos devem ser somente leitura: o membro lê, não "
       "posta.",
       [], Confianca.MEDIUM,
       "peakbot.pro ('members should read them, not post in them') e "
       "memvers.com ('Read-only. First thing new members see')"),
    _p("design.hierarquia_de_cargos",
       "Hierarquia usual: dono, admin (1 a 2 pessoas), moderador, apoiador/VIP, "
       "membro.",
       [], Confianca.MEDIUM,
       "memvers.com/blog/discord-server-setup-guide-2026 (passo 4)"),

    _p("design.onboarding_minimo",
       "Onboarding mínimo que funciona: boas-vindas, uma etapa de regra ou "
       "verificação, uma escolha de cargo e um canal óbvio de conversa. Cada "
       "etapa deve destravar acesso ou ajudar a achar conversa relevante.",
       [], Confianca.MEDIUM,
       "noriaflow.com/docs/discord-server-onboarding e "
       "memvers.com/blog/discord-server-setup-guide-2026 (passo 7)"),

    # --- hipoteses de comunidade: NAO verificadas, marcadas como tal ---------
    _p("comunidade.competitiva_separa_lfg",
       "Comunidades de jogo costumam ter canal de LFG para juntar partida; "
       "competitivas separam também competitivo, resultados e recrutamento.",
       ["gaming", "competitivo", "esports", "clã"], Confianca.MEDIUM,
       "space-node.net ('add an #lfg channel for gaming communities to connect "
       "players') e memvers.com ('Gaming: #lfg, #clips'). A separação de "
       "resultados e recrutamento continua sem fonte direta."),
    _p("comunidade.survival_separa_mundos",
       "Comunidades de Minecraft costumam separar por mundo/servidor e ter área "
       "de construções e suporte.",
       ["minecraft", "survival"], Confianca.UNKNOWN,
       "NÃO VERIFICADO — pesquisa web fora do escopo por decisão do usuário"),
    _p("comunidade.rp_separa_faccoes",
       "Comunidades de GTA RP costumam separar personagens, facções, "
       "recrutamento e regras.",
       ["gta", "rp"], Confianca.UNKNOWN,
       "NÃO VERIFICADO — pesquisa web fora do escopo por decisão do usuário"),
]


class Catalogo:
    """Padrões + feedback, com isolamento por guild no que é feedback."""

    def __init__(self, caminho: str | Path | None = None) -> None:
        self._padroes: dict[str, Padrao] = {p.id: p for p in _SEMENTE}
        self._feedback: dict[int, list[dict[str, Any]]] = {}
        self.caminho = Path(caminho) if caminho else None
        if self.caminho is not None:
            self._carregar()

    # ------------------------------------------------------------------ leitura
    def todos(self) -> list[Padrao]:
        return list(self._padroes.values())

    def utilizaveis(
        self,
        contexto: str | None = None,
        *,
        confianca_minima: Confianca = Confianca.LOW,
    ) -> list[Padrao]:
        """Filtro da spec 119: nada abaixo da confiança mínima sai daqui.

        Decisão crítica chama com `confianca_minima=Confianca.MEDIUM` e as
        hipóteses de comunidade ficam de fora — que é o comportamento correto
        enquanto ninguém pesquisou.
        """
        piso = _ORDEM[confianca_minima]
        return [
            p for p in self._padroes.values()
            if _ORDEM[p.confianca] >= piso and p.utilizavel_para(contexto)
        ]

    def get(self, id_: str) -> Padrao | None:
        return self._padroes.get(id_)

    # ----------------------------------------------------------------- feedback
    def registrar_feedback(self, guild_id: int, texto: str) -> None:
        """Spec 140. Isolado por guild (spec 8): o que um servidor achou feio não
        vira regra para outro automaticamente."""
        texto = (texto or "").strip()
        if not texto:
            return
        self._feedback.setdefault(int(guild_id), []).append({
            "texto": texto[:300],
            "em": time.time(),
            "confianca": Confianca.LOW.value,
        })
        if self.caminho is not None:
            self._salvar()

    def feedback_de(self, guild_id: int) -> list[dict[str, Any]]:
        """Só o feedback DAQUELE guild. Nunca o de outro."""
        return list(self._feedback.get(int(guild_id), []))

    def promover(self, id_: str, confianca: Confianca, fonte: str) -> bool:
        """Spec 76: subir confiança exige fonte. Sem fonte não promove."""
        padrao = self._padroes.get(id_)
        if padrao is None or not fonte.strip():
            return False
        padrao.confianca = confianca
        padrao.fonte = fonte
        padrao.verificado_em = time.time()
        if self.caminho is not None:
            self._salvar()
        return True

    # ------------------------------------------------------------- persistencia
    def _salvar(self) -> None:
        if self.caminho is None:
            return
        try:
            self.caminho.parent.mkdir(parents=True, exist_ok=True)
            self.caminho.write_text(json.dumps({
                "padroes": [asdict(p) | {"confianca": p.confianca.value}
                            for p in self._padroes.values()],
                "feedback": self._feedback,
            }, ensure_ascii=False, indent=1), encoding="utf-8")
        except Exception:  # noqa: BLE001 - diagnostico nunca derruba o pedido
            log.warning("nao deu para salvar o catalogo", exc_info=True)

    def _carregar(self) -> None:
        if self.caminho is None or not self.caminho.exists():
            return
        try:
            dados = json.loads(self.caminho.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            log.warning("catalogo ilegivel; usando a semente", exc_info=True)
            return
        for item in dados.get("padroes") or []:
            try:
                confianca = Confianca(item.get("confianca") or "unknown")
            except ValueError:
                confianca = Confianca.UNKNOWN
            id_ = str(item.get("id") or "")
            if id_:
                self._padroes[id_] = Padrao(
                    id=id_,
                    texto=str(item.get("texto") or ""),
                    aplicabilidade=list(item.get("aplicabilidade") or []),
                    confianca=confianca,
                    fonte=str(item.get("fonte") or ""),
                    verificado_em=item.get("verificado_em"),
                )
        for gid, lista in (dados.get("feedback") or {}).items():
            try:
                self._feedback[int(gid)] = list(lista)
            except (TypeError, ValueError):
                continue
