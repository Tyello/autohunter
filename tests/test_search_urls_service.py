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
        == "https://www.facebook.com/marketplace/search/?query="
    )

    assert (
        search_urls_service.turboclass_url(query)
        == "https://turboclass.com.br/anuncio-lista.php?o=&pg=1&q="
    )


def test_turboclass_url_encodes_query():
    assert (
        search_urls_service.turboclass_url("civic si")
        == "https://turboclass.com.br/anuncio-lista.php?o=&pg=1&q=civic+si"
    )
