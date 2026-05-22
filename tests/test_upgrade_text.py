from app.bot.renderers import render_upgrade_text


def test_render_upgrade_text_with_payment_links():
    text = render_upgrade_text(True)

    assert "Garagem Alvo Premium" in text
    assert "perdeu o carro certo" in text
    assert "No Free" in text
    assert "No Premium" in text
    assert "Mais buscas salvas" in text
    assert "Mais alertas por dia" in text
    assert "Mais anúncios rastreados" in text
    assert "R$ 5,99/mês" in text
    assert "R$ 59,99/ano" in text
    assert "Escolha uma opção abaixo" in text
    assert "links de pagamento ainda não estão configurados" not in text


def test_render_upgrade_text_without_payment_links():
    text = render_upgrade_text(False)

    assert "Garagem Alvo Premium" in text
    assert "perdeu o carro certo" in text
    assert "No Free" in text
    assert "No Premium" in text
    assert "links de pagamento ainda não estão configurados" in text
    assert "Escolha uma opção abaixo" not in text
