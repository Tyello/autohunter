"""Regressao: sessoes HTTP reutilizadas (app.scrapers.base._get_session) nunca
expiravam. Como o scheduler roda como processo unico por dias, a sessao de um
source (ex.: turboclass) acumula cookies/fingerprint por uma semana+; alguns
sites degradam silenciosamente sessoes assim -- continuam respondendo 200 com
imagens, mas passam a omitir campos de preco/ano (field_coverage cai a zero
sem nenhum erro/bloqueio explicito, ver app/services/operational_alerts_service.py).

_get_session deve reciclar (fechar + recriar) a sessao apos _SESSION_TTL_SECONDS,
mas continuar reutilizando a mesma sessao dentro da janela (o reuso e o que
ajuda sites como OLX que sao sensiveis a trafego sem estado)."""

from app.scrapers import base as base_mod


def _reset_sessions():
    base_mod._sessions.clear()
    base_mod._sessions_created_at.clear()


def test_get_session_reuses_same_session_within_ttl():
    _reset_sessions()
    try:
        s1 = base_mod._get_session(None, session_key="turboclass")
        s2 = base_mod._get_session(None, session_key="turboclass")
        assert s1 is s2
    finally:
        _reset_sessions()


def test_get_session_recycles_after_ttl_expires():
    _reset_sessions()
    try:
        s1 = base_mod._get_session(None, session_key="turboclass")
        key = "turboclass::__default__"
        # Simula o relogio monotonico tendo avancado alem do TTL.
        base_mod._sessions_created_at[key] -= base_mod._SESSION_TTL_SECONDS + 1

        s2 = base_mod._get_session(None, session_key="turboclass")

        assert s2 is not s1
    finally:
        _reset_sessions()


def test_get_session_keeps_other_keys_isolated_from_recycling():
    _reset_sessions()
    try:
        olx = base_mod._get_session(None, session_key="olx")
        turbo = base_mod._get_session(None, session_key="turboclass")

        key = "turboclass::__default__"
        base_mod._sessions_created_at[key] -= base_mod._SESSION_TTL_SECONDS + 1
        turbo2 = base_mod._get_session(None, session_key="turboclass")
        olx2 = base_mod._get_session(None, session_key="olx")

        assert turbo2 is not turbo
        assert olx2 is olx
    finally:
        _reset_sessions()
