import pytest

from app.services import search_urls_service


@pytest.mark.parametrize(
    "query, expected",
    [
        (
            "Civic Si",
            "https://www.webmotors.com.br/carros/estoque?tipoveiculo=carros&marca1=Honda&modelo1=Civic&search=si",
        ),
        (
            "VW Golf",
            "https://www.webmotors.com.br/carros/estoque?tipoveiculo=carros&marca1=Volkswagen&modelo1=Golf",
        ),
    ],
)
def test_webmotors_url_infers_brand_and_model(query, expected):
    assert search_urls_service.webmotors_url(query) == expected


def test_mobiauto_url_falls_back_when_brand_is_missing():
    assert (
        search_urls_service.mobiauto_url("hot hatch")
        == "https://www.mobiauto.com.br/comprar/carros/brasil"
    )


def test_icarros_url_infers_brand_and_model():
    assert (
        search_urls_service.icarros_url("Subaru WRX")
        == "https://www.icarros.com.br/comprar/usados/subaru/wrx"
    )


@pytest.mark.parametrize(
    "query",
    ["", None],
)
def test_url_builders_handle_empty_queries(query):
    assert (
        search_urls_service.olx_url(query)
        == "https://www.olx.com.br/autos-e-pecas/carros-vans-e-utilitarios?q="
    )
    assert (
        search_urls_service.gogarage_url(query)
        == "https://www.gogarage.com.br/index.php?q="
    )
    assert (
        search_urls_service.icarros_url(query)
        == "https://www.icarros.com.br/busca?anunciante=concessionaria&produto=carro&palavra-chave="
    )
    assert (
        search_urls_service.facebook_marketplace_url(query)
        == "https://www.facebook.com/marketplace/saopaulo/vehicles?exact=false&query="
    )

    assert (
        search_urls_service.turboclass_url(query)
        == "https://turboclass.com.br/anuncio-lista.php?q="
    )


def test_turboclass_url_encodes_query():
    assert (
        search_urls_service.turboclass_url("civic si")
        == "https://turboclass.com.br/anuncio-lista.php?q=civic+si"
    )


@pytest.mark.parametrize("query", ["Civic Si", "civic si", "  CIVIC   SI "])
def test_q_based_urls_ignore_case_and_extra_spaces(query):
    assert search_urls_service.olx_url(query) == search_urls_service.olx_url("civic si")
    assert (
        search_urls_service.olx_url(query)
        == "https://www.olx.com.br/autos-e-pecas/carros-vans-e-utilitarios?q=civic+si"
    )
    assert search_urls_service.turboclass_url(query) == search_urls_service.turboclass_url("civic si")
    assert search_urls_service.facebook_marketplace_url(query) == search_urls_service.facebook_marketplace_url("civic si")


@pytest.mark.parametrize("query", ["Civic Si", "  CIVIC   SI "])
def test_free_text_fallback_urls_ignore_case_and_extra_spaces(query):
    for builder in (
        search_urls_service.gogarage_url,
        search_urls_service.icarros_url,
        search_urls_service.chavesnamao_url,
        search_urls_service.webmotors_url,
    ):
        assert builder(query) == builder("civic si"), builder.__name__
    assert search_urls_service.icarros_url("Hot Hatch") == search_urls_service.icarros_url("hot  hatch")
    assert search_urls_service.chavesnamao_url("Hot  Hatch").endswith("?q=hot+hatch")


def test_v2_adapters_build_normalized_search_urls():
    from app.scrapers.sources.chavesnamao import ChavesNaMaoScraper
    from app.scrapers.sources.gogarage_mobiauto import GoGarageScraper, MobiautoScraper
    from app.scrapers.sources.olx import OLXScraper

    assert OLXScraper().build_search_url("Civic  Si") == OLXScraper().build_search_url("civic si")
    assert ChavesNaMaoScraper().build_search_url("Civic  Si").endswith("?q=civic+si")
    assert MobiautoScraper().build_search_url("Civic  Si").endswith("?q=civic+si")
    assert GoGarageScraper().build_search_url("Civic  Si").endswith("/carros/civic-si")
