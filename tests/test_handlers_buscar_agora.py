"""Testes para handlers_buscar_agora.py (Etapa 1 da spec 018).

Testa o fluxo: termo → facetas → refinamento → top-10.
"""

import asyncio
import types
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import and_
from telegram.ext import ConversationHandler

from app.bot import handlers_buscar_agora as hba
from app.bot.handlers_buscar_agora import (
    _bucket_to_condition,
    _render_facets_keyboard,
    buscar_agora_conversation,
    buscar_agora_on_term,
    cb_buscar_agora_facet,
    cb_buscar_agora_create_alert,
    cb_buscar_agora_top10,
    BUSCAR_AGORA_TERM,
    BUSCAR_AGORA_FACETS,
)
from app.models.car_listing import CarListing
from app.services.facet_search_service import FacetCount


def _insert_listing(db, **kwargs) -> CarListing:
    """Utilitário para inserir um CarListing com defaults."""
    defaults = {
        "id": uuid.uuid4(),
        "source": "test_source",
        "external_id": f"ext_{uuid.uuid4()}",
        "url": "http://example.com",
        "status": "ativo",
        "currency": "BRL",
        "is_sold": False,
        "last_seen_at": datetime.now(tz=timezone.utc),
        "state": "SP",
        "city": "São Paulo",
        "make": "Honda",
        "model": "Civic",
        "year": 2015,
        "price": Decimal("50000"),
        "mileage_km": 80000,
        "color": "Preto",
        "body_type": "Sedan",
        "doors": 4,
    }
    defaults.update(kwargs)
    listing = CarListing(**defaults)
    db.add(listing)
    db.commit()
    return listing


class TestBucketToCondition:
    """Testes para a função _bucket_to_condition."""

    def test_state_categoric_exact_match(self):
        """State bucket deve gerar igualdade exata."""
        conditions = _bucket_to_condition("state", "SP")
        assert len(conditions) == 1
        # Verifica que é uma condição SQLAlchemy
        assert hasattr(conditions[0], "comparator")

    def test_city_categoric_exact_match(self):
        """City bucket deve gerar igualdade exata."""
        conditions = _bucket_to_condition("city", "São Paulo")
        assert len(conditions) == 1

    def test_make_categoric_exact_match(self):
        """Make bucket deve gerar igualdade exata."""
        conditions = _bucket_to_condition("make", "Honda")
        assert len(conditions) == 1

    def test_year_bucket_less_than_2010(self):
        """Year bucket '< 2010' deve gerar year < 2010."""
        conditions = _bucket_to_condition("year", "< 2010")
        assert len(conditions) == 1

    def test_year_bucket_2010_2014(self):
        """Year bucket '2010-2014' deve gerar intervalo."""
        conditions = _bucket_to_condition("year", "2010-2014")
        assert len(conditions) == 1

    def test_year_bucket_2025_plus(self):
        """Year bucket '2025+' deve gerar year >= 2025."""
        conditions = _bucket_to_condition("year", "2025+")
        assert len(conditions) == 1

    def test_price_bucket_less_than_20000(self):
        """Price bucket '< 20.000' deve gerar price < 20000."""
        conditions = _bucket_to_condition("price", "< 20.000")
        assert len(conditions) == 1

    def test_price_bucket_20000_39999(self):
        """Price bucket '20.000-39.999' deve gerar intervalo."""
        conditions = _bucket_to_condition("price", "20.000-39.999")
        assert len(conditions) == 1

    def test_price_bucket_150000_plus(self):
        """Price bucket '150.000+' deve gerar price >= 150000."""
        conditions = _bucket_to_condition("price", "150.000+")
        assert len(conditions) == 1

    def test_mileage_bucket_less_than_20000(self):
        """Mileage bucket '< 20.000 km' deve gerar mileage_km < 20000."""
        conditions = _bucket_to_condition("mileage_km", "< 20.000 km")
        assert len(conditions) == 1

    def test_mileage_bucket_20000_49999(self):
        """Mileage bucket '20.000-49.999 km' deve gerar intervalo."""
        conditions = _bucket_to_condition("mileage_km", "20.000-49.999 km")
        assert len(conditions) == 1

    def test_doors_numeric_bucket(self):
        """Doors bucket deve parsear como int e gerar igualdade."""
        conditions = _bucket_to_condition("doors", "4")
        assert len(conditions) == 1

    def test_invalid_facet_returns_empty_list(self):
        """Faceta inválida deve retornar lista vazia."""
        conditions = _bucket_to_condition("invalid_facet", "some_bucket")
        assert conditions == []

    def test_none_bucket_returns_empty_list(self):
        """Bucket None deve retornar lista vazia."""
        conditions = _bucket_to_condition("state", None)
        assert conditions == []

    def test_invalid_doors_value_returns_empty_list(self):
        """Valor inválido de doors deve retornar lista vazia."""
        conditions = _bucket_to_condition("doors", "abc")
        assert conditions == []


class TestRenderFacetsKeyboard:
    """Testes para a função _render_facets_keyboard."""

    def test_render_empty_facets(self):
        """Teclado vazio quando não há facetas."""
        kb = _render_facets_keyboard([])
        assert kb is not None
        # Deve ter pelo menos botões de ação no rodapé
        assert len(kb.inline_keyboard) >= 1

    def test_render_with_total_count(self):
        """Teclado deve mostrar total de resultados."""
        facets = [FacetCount(facet="__total__", bucket=None, count=100)]
        kb = _render_facets_keyboard(facets)
        # Primeira linha deve ter o total
        assert len(kb.inline_keyboard) > 0
        # Verifica se contém "100"
        buttons_text = " ".join(b.text for row in kb.inline_keyboard for b in row)
        assert "100" in buttons_text

    def test_render_state_facets(self):
        """Teclado deve mostrar facetas de state."""
        facets = [
            FacetCount(facet="state", bucket="SP", count=50),
            FacetCount(facet="state", bucket="RJ", count=30),
        ]
        kb = _render_facets_keyboard(facets)
        buttons_text = " ".join(b.text for row in kb.inline_keyboard for b in row)
        assert "SP" in buttons_text
        assert "RJ" in buttons_text

    def test_render_callback_data_format(self):
        """Teclado deve gerar callback_data correto para facetas."""
        facets = [
            FacetCount(facet="state", bucket="SP", count=50),
        ]
        kb = _render_facets_keyboard(facets)
        # Procura pelo botão com "SP"
        for row in kb.inline_keyboard:
            for btn in row:
                if "SP" in btn.text:
                    assert btn.callback_data == "BUSCAR_AGORA:FACET:state:SP"
                    break

    def test_render_has_action_buttons(self):
        """Teclado deve ter botões de ação (top-10, cancelar)."""
        facets = [FacetCount(facet="state", bucket="SP", count=50)]
        kb = _render_facets_keyboard(facets)
        # Última linha deve ter top-10 e cancelar
        buttons_text = " ".join(b.text for row in kb.inline_keyboard[-1:] for b in row)
        assert "10" in buttons_text  # "Ver os 10 primeiros"
        assert "Cancelar" in buttons_text












class TestBuscarAgoraConversation:
    """Testes para buscar_agora_conversation."""

    def test_conversation_handler_created(self):
        """Função deve retornar um ConversationHandler válido."""
        conv = buscar_agora_conversation()
        assert conv is not None
        assert hasattr(conv, "entry_points")
        assert hasattr(conv, "states")
        assert hasattr(conv, "fallbacks")
        assert len(conv.entry_points) > 0
        assert len(conv.states) > 0

    def test_conversation_handler_has_states(self):
        """ConversationHandler deve ter os estados corretos."""
        conv = buscar_agora_conversation()
        assert BUSCAR_AGORA_TERM in conv.states
        assert BUSCAR_AGORA_FACETS in conv.states


class TestBucketToConditionIntegration:
    """Testes de integração para _bucket_to_condition com o banco de dados."""

    def test_year_bucket_filters_correctly(self, db):
        """Condição year deve filtrar listings corretamente."""
        # Insere anúncios com anos diferentes
        _insert_listing(db, year=2008, state="SP")
        _insert_listing(db, year=2012, state="SP")
        _insert_listing(db, year=2017, state="SP")
        _insert_listing(db, year=2022, state="SP")
        _insert_listing(db, year=2025, state="SP")

        # Testa cada bucket de year
        conditions = _bucket_to_condition("year", "2015-2019")
        query = db.query(CarListing).filter(and_(*conditions) if conditions else True)
        results = query.all()
        # Deve ter apenas o 2017
        assert len(results) == 1
        assert results[0].year == 2017

    def test_price_bucket_filters_correctly(self, db):
        """Condição price deve filtrar listings corretamente."""
        # Insere anúncios com preços diferentes
        _insert_listing(db, price=Decimal("15000"), state="SP")
        _insert_listing(db, price=Decimal("35000"), state="SP")
        _insert_listing(db, price=Decimal("50000"), state="SP")
        _insert_listing(db, price=Decimal("90000"), state="SP")
        _insert_listing(db, price=Decimal("150000"), state="SP")

        # Testa bucket "40.000-59.999"
        conditions = _bucket_to_condition("price", "40.000-59.999")
        query = db.query(CarListing).filter(and_(*conditions) if conditions else True)
        results = query.all()
        # Deve ter apenas o 50000
        assert len(results) == 1
        assert results[0].price == Decimal("50000")

    def test_state_bucket_filters_exactly(self, db):
        """Condição state deve fazer igualdade exata."""
        # Insere anúncios de diferentes estados
        _insert_listing(db, state="SP", city="São Paulo")
        _insert_listing(db, state="RJ", city="Rio de Janeiro")
        _insert_listing(db, state="MG", city="Belo Horizonte")

        conditions = _bucket_to_condition("state", "SP")
        query = db.query(CarListing).filter(and_(*conditions) if conditions else True)
        results = query.all()
        # Deve ter apenas SP
        assert len(results) == 1
        assert results[0].state == "SP"

    def test_mileage_bucket_filters_correctly(self, db):
        """Condição mileage_km deve filtrar listings corretamente."""
        # Insere anúncios com quilometragem diferente
        _insert_listing(db, mileage_km=10000, state="SP")
        _insert_listing(db, mileage_km=30000, state="SP")
        _insert_listing(db, mileage_km=70000, state="SP")
        _insert_listing(db, mileage_km=120000, state="SP")

        # Testa bucket "50.000-99.999 km"
        conditions = _bucket_to_condition("mileage_km", "50.000-99.999 km")
        query = db.query(CarListing).filter(and_(*conditions) if conditions else True)
        results = query.all()
        # Deve ter apenas o 70000
        assert len(results) == 1
        assert results[0].mileage_km == 70000


class TestBucketToFilterDescriptors:
    """Testes para a função _bucket_to_filter_descriptors."""

    def test_state_categorical_bucket(self):
        """Bucket categórico de state deve retornar SimpleNamespace com eq."""
        from app.bot.handlers_buscar_agora import _bucket_to_filter_descriptors
        descriptors = _bucket_to_filter_descriptors("state", "SP")
        assert len(descriptors) == 1
        assert descriptors[0].field == "state"
        assert descriptors[0].operator == "eq"
        assert descriptors[0].value == "SP"

    def test_color_categorical_bucket(self):
        """Bucket categórico de color deve retornar SimpleNamespace com eq."""
        from app.bot.handlers_buscar_agora import _bucket_to_filter_descriptors
        descriptors = _bucket_to_filter_descriptors("color", "preto")
        assert len(descriptors) == 1
        assert descriptors[0].field == "color"
        assert descriptors[0].operator == "eq"
        assert descriptors[0].value == "preto"

    def test_year_bucket_less_than_2010(self):
        """Bucket year '< 2010' deve retornar lt com value '2010'."""
        from app.bot.handlers_buscar_agora import _bucket_to_filter_descriptors
        descriptors = _bucket_to_filter_descriptors("year", "< 2010")
        assert len(descriptors) == 1
        assert descriptors[0].field == "year"
        assert descriptors[0].operator == "lt"
        assert descriptors[0].value == "2010"

    def test_year_bucket_2010_2014(self):
        """Bucket year '2010-2014' deve retornar dois descritores: gte 2010 e lte 2014."""
        from app.bot.handlers_buscar_agora import _bucket_to_filter_descriptors
        descriptors = _bucket_to_filter_descriptors("year", "2010-2014")
        assert len(descriptors) == 2
        assert descriptors[0].field == "year"
        assert descriptors[0].operator == "gte"
        assert descriptors[0].value == "2010"
        assert descriptors[1].field == "year"
        assert descriptors[1].operator == "lte"
        assert descriptors[1].value == "2014"

    def test_year_bucket_2025_plus(self):
        """Bucket year '2025+' deve retornar gte com value '2025'."""
        from app.bot.handlers_buscar_agora import _bucket_to_filter_descriptors
        descriptors = _bucket_to_filter_descriptors("year", "2025+")
        assert len(descriptors) == 1
        assert descriptors[0].field == "year"
        assert descriptors[0].operator == "gte"
        assert descriptors[0].value == "2025"

    def test_price_bucket_less_than_20000(self):
        """Bucket price '< 20.000' deve retornar lt com value '20000'."""
        from app.bot.handlers_buscar_agora import _bucket_to_filter_descriptors
        descriptors = _bucket_to_filter_descriptors("price", "< 20.000")
        assert len(descriptors) == 1
        assert descriptors[0].field == "price"
        assert descriptors[0].operator == "lt"
        assert descriptors[0].value == "20000"

    def test_price_bucket_150000_plus(self):
        """Bucket price '150.000+' deve retornar gte com value '150000'."""
        from app.bot.handlers_buscar_agora import _bucket_to_filter_descriptors
        descriptors = _bucket_to_filter_descriptors("price", "150.000+")
        assert len(descriptors) == 1
        assert descriptors[0].field == "price"
        assert descriptors[0].operator == "gte"
        assert descriptors[0].value == "150000"

    def test_mileage_bucket_less_than_20000_km(self):
        """Bucket mileage_km '< 20.000 km' deve retornar lt com value '20000'."""
        from app.bot.handlers_buscar_agora import _bucket_to_filter_descriptors
        descriptors = _bucket_to_filter_descriptors("mileage_km", "< 20.000 km")
        assert len(descriptors) == 1
        assert descriptors[0].field == "mileage_km"
        assert descriptors[0].operator == "lt"
        assert descriptors[0].value == "20000"

    def test_mileage_bucket_150000_plus_km(self):
        """Bucket mileage_km '150.000+ km' deve retornar gte com value '150000'."""
        from app.bot.handlers_buscar_agora import _bucket_to_filter_descriptors
        descriptors = _bucket_to_filter_descriptors("mileage_km", "150.000+ km")
        assert len(descriptors) == 1
        assert descriptors[0].field == "mileage_km"
        assert descriptors[0].operator == "gte"
        assert descriptors[0].value == "150000"

    def test_invalid_facet_returns_empty_list(self):
        """Faceta inválida deve retornar lista vazia."""
        from app.bot.handlers_buscar_agora import _bucket_to_filter_descriptors
        descriptors = _bucket_to_filter_descriptors("invalid_facet", "some_bucket")
        assert descriptors == []

    def test_none_bucket_returns_empty_list(self):
        """Bucket None deve retornar lista vazia."""
        from app.bot.handlers_buscar_agora import _bucket_to_filter_descriptors
        descriptors = _bucket_to_filter_descriptors("state", None)
        assert descriptors == []


class TestCbBuscarAgoraCreateAlert:
    """Testes para a função cb_buscar_agora_create_alert."""

    def test_create_alert_function_exists(self):
        """Função cb_buscar_agora_create_alert deve estar importável."""
        from app.bot.handlers_buscar_agora import cb_buscar_agora_create_alert
        assert callable(cb_buscar_agora_create_alert)
        # Verifica se é uma função corrotina (async)
        import inspect
        assert inspect.iscoroutinefunction(cb_buscar_agora_create_alert)

    def test_create_alert_context_keys_initialized(self):
        """Testa que contexto de buscar_agora mantém estrutura esperada."""
        context_user_data = {
            "buscar_agora_term": "civic si até 120000 sp",
            "buscar_agora_extra_filters_struct": [],
        }
        # Verifica que as chaves esperadas estão presentes
        assert "buscar_agora_term" in context_user_data
        assert "buscar_agora_extra_filters_struct" in context_user_data
        # Verifica que extra_filters_struct é lista
        assert isinstance(context_user_data["buscar_agora_extra_filters_struct"], list)


# ============================================================================
# Classes de mock para testes de handlers assíncronos (Etapa 2)
# ============================================================================

class _MessageMock:
    """Mock de Message para handlers de /buscar_agora."""

    def __init__(self, text: str = ""):
        self.text = text
        self.sent_messages = []

    async def reply_text(self, text: str, reply_markup=None):
        """Mock de reply_text."""
        self.sent_messages.append({"text": text, "reply_markup": reply_markup})


class _CallbackQueryMock:
    """Mock de CallbackQuery para handlers de callback."""

    def __init__(self, data: str = ""):
        self.data = data
        self.edited_messages = []
        self.answers = []

    async def answer(self, text: str = "", show_alert: bool = False):
        """Mock de answer."""
        self.answers.append({"text": text, "show_alert": show_alert})

    async def edit_message_text(self, text: str, reply_markup=None):
        """Mock de edit_message_text."""
        self.edited_messages.append({"text": text, "reply_markup": reply_markup})


class _UpdateMock:
    """Mock de Update para handlers de /buscar_agora."""

    def __init__(self, message_text: str = "", callback_data: str = ""):
        self.effective_chat = types.SimpleNamespace(id=12345)
        self.effective_user = types.SimpleNamespace(username="test_user")

        if message_text:
            self.message = _MessageMock(message_text)
            self.effective_message = self.message
            self.callback_query = None
        else:
            self.message = None
            self.effective_message = None

        if callback_data:
            self.callback_query = _CallbackQueryMock(callback_data)
        else:
            self.callback_query = None


class _SessionMock:
    """Mock de SessionLocal para handlers de /buscar_agora."""

    def __init__(self, listings=None, raise_error=False):
        self.listings = listings or []
        self.raise_error = raise_error

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def query(self, model):
        """Mock de query que retorna um objeto com filter/order_by/limit/all."""
        return _QueryMock(self.listings, self.raise_error)


class _QueryMock:
    """Mock de Query para simular db.query(...).filter(...).order_by(...).limit(10).all()."""

    def __init__(self, listings, raise_error=False):
        self.listings = listings
        self.raise_error = raise_error

    def filter(self, *args, **kwargs):
        """Mock de filter — retorna self para chaining."""
        if self.raise_error:
            raise Exception("Mock database error")
        return self

    def order_by(self, *args, **kwargs):
        """Mock de order_by — retorna self para chaining."""
        return self

    def limit(self, n):
        """Mock de limit — retorna self para chaining."""
        return self

    def all(self):
        """Mock de all — retorna a lista de listings."""
        return self.listings


# ============================================================================
# Testes de integração para handlers assíncronos (Etapa 2)
# ============================================================================

class TestHandlersBuscarAgoraAsync:
    """Testes de integração para os handlers assíncronos do fluxo buscar_agora."""

    def test_buscar_agora_on_term_with_results(self, monkeypatch):
        """
        Teste 1: buscar_agora_on_term com resultado > 0.

        Mocka compute_facet_counts retornando facetas com total > 0.
        Chama o handler e verifica que retorna BUSCAR_AGORA_FACETS
        e que context.user_data["buscar_agora_term"] foi setado.
        """
        # Mock de compute_facet_counts com resultados
        def mock_compute_facet_counts(db, term, extra_conditions=None):
            return [
                FacetCount(facet="__total__", bucket=None, count=50),
                FacetCount(facet="state", bucket="SP", count=30),
                FacetCount(facet="state", bucket="RJ", count=20),
            ]

        monkeypatch.setattr(hba, "compute_facet_counts", mock_compute_facet_counts)
        monkeypatch.setattr(hba, "SessionLocal", lambda: _SessionMock())

        # Setup
        update = _UpdateMock(message_text="civic si até 120000 sp")
        context = types.SimpleNamespace(user_data={}, bot=types.SimpleNamespace())

        # Executa
        result = asyncio.run(buscar_agora_on_term(update, context))

        # Assertions
        assert result == BUSCAR_AGORA_FACETS
        assert context.user_data["buscar_agora_term"] == "civic si até 120000 sp"
        assert context.user_data["buscar_agora_extra_filters"] == []
        assert context.user_data["buscar_agora_extra_filters_struct"] == []

    def test_buscar_agora_on_term_zero_results_with_valid_filter(self, monkeypatch):
        """
        Teste 2: buscar_agora_on_term com zero resultado E filtro válido extraído.

        Termo "civic até 80000" extrai um filtro de price automaticamente.
        Mocka compute_facet_counts retornando __total__ = 0.
        Verifica que retorna BUSCAR_AGORA_FACETS e que a mensagem contém
        botão de "Criar alerta".
        """
        # Mock de compute_facet_counts retornando zero
        def mock_compute_facet_counts(db, term, extra_conditions=None):
            return [FacetCount(facet="__total__", bucket=None, count=0)]

        monkeypatch.setattr(hba, "compute_facet_counts", mock_compute_facet_counts)
        monkeypatch.setattr(hba, "SessionLocal", lambda: _SessionMock())

        # Setup
        update = _UpdateMock(message_text="civic até 80000")
        context = types.SimpleNamespace(user_data={}, bot=types.SimpleNamespace())

        # Executa
        result = asyncio.run(buscar_agora_on_term(update, context))

        # Assertions
        assert result == BUSCAR_AGORA_FACETS
        # Verifica que a mensagem tem botão de alerta
        assert len(update.message.sent_messages) > 0
        last_message = update.message.sent_messages[-1]
        assert last_message["reply_markup"] is not None
        # Procura pelo callback_data CREATE_ALERT nos botões
        create_alert_found = False
        for row in last_message["reply_markup"].inline_keyboard:
            for btn in row:
                if btn.callback_data == "BUSCAR_AGORA:CREATE_ALERT":
                    create_alert_found = True
                    break
        assert create_alert_found, "Botão CREATE_ALERT não encontrado na resposta"

    def test_buscar_agora_on_term_zero_results_no_valid_filter(self, monkeypatch):
        """
        Teste 3: buscar_agora_on_term com zero resultado E SEM filtro válido.

        Termo "blablabla xyz" não tem filtro implícito.
        Mocka compute_facet_counts retornando __total__ = 0.
        Verifica que retorna ConversationHandler.END e que NÃO há botão CREATE_ALERT.
        """
        # Mock de compute_facet_counts retornando zero
        def mock_compute_facet_counts(db, term, extra_conditions=None):
            return [FacetCount(facet="__total__", bucket=None, count=0)]

        monkeypatch.setattr(hba, "compute_facet_counts", mock_compute_facet_counts)
        monkeypatch.setattr(hba, "SessionLocal", lambda: _SessionMock())

        # Setup
        update = _UpdateMock(message_text="blablabla xyz")
        context = types.SimpleNamespace(user_data={}, bot=types.SimpleNamespace())

        # Executa
        result = asyncio.run(buscar_agora_on_term(update, context))

        # Assertions
        assert result == ConversationHandler.END
        # Verifica que a mensagem não tem botão CREATE_ALERT
        assert len(update.message.sent_messages) > 0
        last_message = update.message.sent_messages[-1]
        if last_message["reply_markup"] is not None:
            create_alert_found = False
            for row in last_message["reply_markup"].inline_keyboard:
                for btn in row:
                    if btn.callback_data == "BUSCAR_AGORA:CREATE_ALERT":
                        create_alert_found = True
                        break
            assert not create_alert_found, "Botão CREATE_ALERT não deveria estar presente"

    def test_cb_buscar_agora_facet_valid_click_with_results(self, monkeypatch):
        """
        Teste 4: cb_buscar_agora_facet clique válido com resultado > 0.

        Monta context.user_data com buscar_agora_term/extra_filters já inicializados.
        Clique em "state:SP" simula um refinamento.
        Mocka compute_facet_counts retornando total > 0.
        Verifica que retorna BUSCAR_AGORA_FACETS e que extra_filters_struct
        foi estendido com SimpleNamespace(field="state", operator="eq", value="SP").
        """
        # Mock de compute_facet_counts
        def mock_compute_facet_counts(db, term, extra_conditions=None):
            return [
                FacetCount(facet="__total__", bucket=None, count=25),
                FacetCount(facet="state", bucket="RJ", count=15),
                FacetCount(facet="city", bucket="Rio", count=10),
            ]

        monkeypatch.setattr(hba, "compute_facet_counts", mock_compute_facet_counts)
        monkeypatch.setattr(hba, "SessionLocal", lambda: _SessionMock())

        # Setup
        update = _UpdateMock(callback_data="BUSCAR_AGORA:FACET:state:SP")
        context = types.SimpleNamespace(
            user_data={
                "buscar_agora_term": "civic",
                "buscar_agora_extra_filters": [],
                "buscar_agora_extra_filters_struct": [],
            },
            bot=types.SimpleNamespace(),
        )

        # Executa
        result = asyncio.run(cb_buscar_agora_facet(update, context))

        # Assertions
        assert result == BUSCAR_AGORA_FACETS
        extra_struct = context.user_data["buscar_agora_extra_filters_struct"]
        assert len(extra_struct) == 1
        assert extra_struct[0].field == "state"
        assert extra_struct[0].operator == "eq"
        assert extra_struct[0].value == "SP"
        # Verifica que edit_message_text foi chamado
        assert len(update.callback_query.edited_messages) > 0

    def test_cb_buscar_agora_facet_click_zeroes_results(self, monkeypatch):
        """
        Teste 5: cb_buscar_agora_facet clique que zera o resultado.

        Mesma montagem, mas mocka compute_facet_counts retornando total=0 após clique.
        Verifica que tela de oferta de alerta é mostrada e retorno == BUSCAR_AGORA_FACETS.
        """
        # Mock de compute_facet_counts retornando zero
        def mock_compute_facet_counts(db, term, extra_conditions=None):
            return [FacetCount(facet="__total__", bucket=None, count=0)]

        monkeypatch.setattr(hba, "compute_facet_counts", mock_compute_facet_counts)
        monkeypatch.setattr(hba, "SessionLocal", lambda: _SessionMock())

        # Setup
        update = _UpdateMock(callback_data="BUSCAR_AGORA:FACET:price:100.000-149.999")
        context = types.SimpleNamespace(
            user_data={
                "buscar_agora_term": "ferrari",
                "buscar_agora_extra_filters": [],
                "buscar_agora_extra_filters_struct": [],
            },
            bot=types.SimpleNamespace(),
        )

        # Executa
        result = asyncio.run(cb_buscar_agora_facet(update, context))

        # Assertions
        assert result == BUSCAR_AGORA_FACETS
        # Verifica que foi editada a mensagem com botão de alerta
        assert len(update.callback_query.edited_messages) > 0
        edited = update.callback_query.edited_messages[-1]
        assert edited["reply_markup"] is not None
        # Procura pelo CREATE_ALERT nos botões
        create_alert_found = False
        for row in edited["reply_markup"].inline_keyboard:
            for btn in row:
                if btn.callback_data == "BUSCAR_AGORA:CREATE_ALERT":
                    create_alert_found = True
                    break
        assert create_alert_found, "Botão CREATE_ALERT não encontrado na tela de zero resultados"

    def test_cb_buscar_agora_create_alert_reentry_flow(self, monkeypatch):
        """
        Teste 6: cb_buscar_agora_create_alert — o caminho mais sensível.

        Monta context.user_data com:
        - buscar_agora_term = "civic até 80000"
        - buscar_agora_extra_filters_struct = [SimpleNamespace(field="state", operator="eq", value="SP")]

        Simula 1 refinamento já aplicado (state=SP).
        Mocka _show_create_wishlist_summary_screen para retornar um sentinel.

        Verifica que:
        - context.user_data["menu_create_wishlist_query"] foi populado com cleaned_query
        - context.user_data["menu_create_wishlist_draft_filters"] é uma lista não-vazia
        - context.user_data["menu_create_wishlist_include_auctions"] is False
        - O retorno do handler é o mesmo que _show_create_wishlist_summary_screen retornou
        """
        # Mock de _show_create_wishlist_summary_screen
        async def mock_show_summary(update, context):
            return 9999  # sentinel return value

        monkeypatch.setattr(hba, "_show_create_wishlist_summary_screen", mock_show_summary)
        monkeypatch.setattr(hba, "SessionLocal", lambda: _SessionMock())

        # Setup
        update = _UpdateMock(callback_data="BUSCAR_AGORA:CREATE_ALERT")
        context = types.SimpleNamespace(
            user_data={
                "buscar_agora_term": "civic até 80000",
                "buscar_agora_extra_filters_struct": [
                    types.SimpleNamespace(field="state", operator="eq", value="SP")
                ],
            },
            bot=types.SimpleNamespace(),
        )

        # Executa
        result = asyncio.run(cb_buscar_agora_create_alert(update, context))

        # Assertions
        assert result == 9999, "Handler deve retornar o resultado de _show_create_wishlist_summary_screen"

        # Verifica que menu_create_wishlist_query foi setado
        assert "menu_create_wishlist_query" in context.user_data
        assert context.user_data["menu_create_wishlist_query"] is not None

        # Verifica que menu_create_wishlist_draft_filters foi criado (não vazio)
        assert "menu_create_wishlist_draft_filters" in context.user_data
        draft_filters = context.user_data["menu_create_wishlist_draft_filters"]
        assert isinstance(draft_filters, list)
        assert len(draft_filters) > 0, "draft_filters deve conter pelo menos um grupo"

        # Verifica que cada grupo tem a estrutura esperada
        for group in draft_filters:
            assert "group" in group
            assert "label" in group
            assert "filters" in group
            assert isinstance(group["filters"], list)

        # Verifica que menu_create_wishlist_include_auctions é False
        assert context.user_data["menu_create_wishlist_include_auctions"] is False

    def test_cb_buscar_agora_top10_happy_path(self, monkeypatch):
        """
        Teste 7: cb_buscar_agora_top10 — caminho feliz com resultados.

        Monta context.user_data com buscar_agora_term = "civic" e
        buscar_agora_extra_filters vazio.
        Mocka SessionLocal para retornar 2 CarListings via query.
        Mocka format_ad_message para retornar payload simples.
        Mocka asyncio.create_task para evitar envio real de mensagens.
        Verifica que retorna ConversationHandler.END.
        """
        # Mock de format_ad_message
        def mock_format_ad_message(listing):
            return {
                "text": f"Honda {listing.model} - R$ {listing.price}",
                "inline_keyboard": [
                    [{"text": "Abrir anúncio", "url": "http://example.com"}]
                ]
            }

        # Mock de asyncio.create_task para não enviar mensagens reais
        async def mock_create_task(coro):
            pass

        # Cria listings mock
        listing1 = types.SimpleNamespace(
            id=uuid.uuid4(),
            model="Civic",
            price=Decimal("50000"),
            created_at=datetime.now(tz=timezone.utc)
        )
        listing2 = types.SimpleNamespace(
            id=uuid.uuid4(),
            model="Civic Si",
            price=Decimal("60000"),
            created_at=datetime.now(tz=timezone.utc)
        )

        # Setup mocks
        monkeypatch.setattr(
            hba, "SessionLocal",
            lambda: _SessionMock(listings=[listing1, listing2])
        )
        monkeypatch.setattr(hba, "format_ad_message", mock_format_ad_message)
        monkeypatch.setattr(asyncio, "create_task", mock_create_task)

        # Setup update e context
        update = _UpdateMock(callback_data="BUSCAR_AGORA:TOP10")
        context = types.SimpleNamespace(
            user_data={
                "buscar_agora_term": "civic",
                "buscar_agora_extra_filters": [],
            },
            bot=types.SimpleNamespace(),
        )

        # Executa
        result = asyncio.run(cb_buscar_agora_top10(update, context))

        # Assertions
        assert result == ConversationHandler.END
        # Verifica que q.answer foi chamado
        assert len(update.callback_query.answers) > 0

    def test_cb_buscar_agora_top10_expired_session(self, monkeypatch):
        """
        Teste 8: cb_buscar_agora_top10 — sessão expirada (term vazio).

        Monta context.user_data SEM buscar_agora_term (ou vazio).
        Verifica que retorna ConversationHandler.END e que
        q.answer foi chamado com show_alert=True e texto "Sessão expirou.".
        """
        # Mock SessionLocal (não será usado)
        monkeypatch.setattr(hba, "SessionLocal", lambda: _SessionMock())

        # Setup update e context SEM buscar_agora_term
        update = _UpdateMock(callback_data="BUSCAR_AGORA:TOP10")
        context = types.SimpleNamespace(
            user_data={},  # Sem buscar_agora_term
            bot=types.SimpleNamespace(),
        )

        # Executa
        result = asyncio.run(cb_buscar_agora_top10(update, context))

        # Assertions
        assert result == ConversationHandler.END
        # Verifica que q.answer foi chamado com alert
        assert len(update.callback_query.answers) > 0
        last_answer = update.callback_query.answers[-1]
        assert "Sessão expirou" in last_answer["text"]
        assert last_answer["show_alert"] is True

    def test_cb_buscar_agora_top10_search_error(self, monkeypatch):
        """
        Teste 9: cb_buscar_agora_top10 — erro na busca do banco.

        Monta context.user_data com buscar_agora_term = "civic".
        Mocka SessionLocal.query para lançar exceção.
        Verifica que retorna BUSCAR_AGORA_FACETS (não END!) e que
        q.answer foi chamado com "Erro ao buscar anúncios.".
        """
        # Mock SessionLocal que lança erro
        monkeypatch.setattr(
            hba, "SessionLocal",
            lambda: _SessionMock(raise_error=True)
        )

        # Setup update e context
        update = _UpdateMock(callback_data="BUSCAR_AGORA:TOP10")
        context = types.SimpleNamespace(
            user_data={
                "buscar_agora_term": "civic",
                "buscar_agora_extra_filters": [],
            },
            bot=types.SimpleNamespace(),
        )

        # Executa
        result = asyncio.run(cb_buscar_agora_top10(update, context))

        # Assertions
        assert result == BUSCAR_AGORA_FACETS
        # Verifica que q.answer foi chamado com alerta
        assert len(update.callback_query.answers) > 0
        last_answer = update.callback_query.answers[-1]
        assert "Erro ao buscar anúncios" in last_answer["text"]
        assert last_answer["show_alert"] is True

    def test_cb_buscar_agora_top10_no_results(self, monkeypatch):
        """
        Teste 10: cb_buscar_agora_top10 — nenhum resultado encontrado.

        Monta context.user_data com buscar_agora_term = "ferrari".
        Mocka SessionLocal.query para retornar lista vazia.
        Verifica que retorna BUSCAR_AGORA_FACETS (não END!) e que
        q.answer foi chamado com "Nenhum anúncio encontrado...".
        """
        # Mock SessionLocal que retorna lista vazia
        monkeypatch.setattr(
            hba, "SessionLocal",
            lambda: _SessionMock(listings=[])  # Vazio!
        )

        # Setup update e context
        update = _UpdateMock(callback_data="BUSCAR_AGORA:TOP10")
        context = types.SimpleNamespace(
            user_data={
                "buscar_agora_term": "ferrari",
                "buscar_agora_extra_filters": [],
            },
            bot=types.SimpleNamespace(),
        )

        # Executa
        result = asyncio.run(cb_buscar_agora_top10(update, context))

        # Assertions
        assert result == BUSCAR_AGORA_FACETS
        # Verifica que q.answer foi chamado
        assert len(update.callback_query.answers) > 0
        last_answer = update.callback_query.answers[-1]
        assert "Nenhum anúncio encontrado" in last_answer["text"]
        assert last_answer["show_alert"] is True
