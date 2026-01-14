import re
from decimal import Decimal
from typing import Optional


def parse_brl_price(text: str) -> Optional[Decimal]:
    """
    Recebe algo tipo "R$ 85.900" ou "85.900" e converte para Decimal.
    Retorna None se não conseguir.
    """
    if not text:
        return None

    t = text.strip()
    # remove moeda e espaços
    t = t.replace("R$", "").replace("\xa0", " ").strip()

    # pega só dígitos, ponto e vírgula
    t = re.sub(r"[^\d\.,]", "", t)

    # Caso comum no BR: "85.900" (milhar com ponto, sem decimais)
    # remove pontos de milhar e troca vírgula por ponto
    if t.count(",") <= 1:
        t = t.replace(".", "").replace(",", ".")
    else:
        # raro, mas se vier "1.234.567,89"
        t = t.replace(".", "").replace(",", ".")

    try:
        return Decimal(t)
    except Exception:
        return None
