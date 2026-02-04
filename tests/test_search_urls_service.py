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
