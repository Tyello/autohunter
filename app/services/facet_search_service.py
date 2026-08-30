"""Serviço de busca facetada (read-only).

Calcula contagens por faceta (state, city, color, body_type, doors, make, model,
year, price, mileage_km) para um termo de busca livre, em uma única query SQL.

Reaproveit parse_wishlist_query_with_implicit_filters para extrair filtros
implícitos do texto (ex. "até 80000" → filtro price lte 80000).
"""

from dataclasses import dataclass
from decimal import Decimal
import logging

from sqlalchemy import (
    func,
    case,
    cast,
    Text,
    Column,
    Integer,
    or_,
    and_,
    select,
    union_all,
    literal_column,
    null,
)
from sqlalchemy.orm import Session

from app.models.car_listing import CarListing
from app.services.wishlists_service import parse_wishlist_query_with_implicit_filters

logger = logging.getLogger(__name__)

FACET_FIELDS = ["state", "city", "color", "body_type", "doors", "make", "model"]


@dataclass
class FacetCount:
    """Contagem por faceta."""
    facet: str
    bucket: str | None
    count: int


def _year_bucket_expr():
    """Expressão CASE WHEN para bucketing de year.

    Buckets: < 2010 | 2010-2014 | 2015-2019 | 2020-2024 | 2025+
    """
    return case(
        (CarListing.year < 2010, "< 2010"),
        (CarListing.year <= 2014, "2010-2014"),
        (CarListing.year <= 2019, "2015-2019"),
        (CarListing.year <= 2024, "2020-2024"),
        else_="2025+",
    )


def _price_bucket_expr():
    """Expressão CASE WHEN para bucketing de price.

    Buckets: < 20000 | 20000-39999 | 40000-59999 | 60000-79999 | 80000-99999 | 100000-149999 | 150000+
    """
    return case(
        (CarListing.price < 20000, "< 20.000"),
        (CarListing.price < 40000, "20.000-39.999"),
        (CarListing.price < 60000, "40.000-59.999"),
        (CarListing.price < 80000, "60.000-79.999"),
        (CarListing.price < 100000, "80.000-99.999"),
        (CarListing.price < 150000, "100.000-149.999"),
        else_="150.000+",
    )


def _mileage_bucket_expr():
    """Expressão CASE WHEN para bucketing de mileage_km.

    Buckets: < 20000 | 20000-49999 | 50000-99999 | 100000-149999 | 150000+
    """
    return case(
        (CarListing.mileage_km < 20000, "< 20.000 km"),
        (CarListing.mileage_km < 50000, "20.000-49.999 km"),
        (CarListing.mileage_km < 100000, "50.000-99.999 km"),
        (CarListing.mileage_km < 150000, "100.000-149.999 km"),
        else_="150.000+ km",
    )


def build_search_conditions(term: str) -> tuple[list, str]:
    """Extrai filtros implícitos do termo e constrói condições SQLAlchemy.

    Chama parse_wishlist_query_with_implicit_filters para extrair filtros,
    traduz cada NormalizedWishlistFilter para condição SQLAlchemy conforme
    a tabela na spec.

    Args:
        term: termo de busca livre

    Returns:
        (lista_de_condicoes_sqlalchemy, cleaned_query)
    """
    parsed = parse_wishlist_query_with_implicit_filters(term)
    conditions = []

    for filter_obj in parsed.filters:
        field = filter_obj.field
        operator = filter_obj.operator
        value = filter_obj.value

        # Verifica se o campo existe em CarListing
        if not hasattr(CarListing, field):
            logger.warning(f"Campo {field} não existe em CarListing, ignorando filtro")
            continue

        column = getattr(CarListing, field)

        # Tradução de filtros numéricos
        if field in ("price", "year", "mileage_km", "doors"):
            if field == "price":
                try:
                    numeric_value = Decimal(value)
                except (ValueError, TypeError):
                    logger.warning(f"Não consigo converter price '{value}' para Decimal, ignorando")
                    continue
            else:
                try:
                    numeric_value = int(value)
                except (ValueError, TypeError):
                    logger.warning(f"Não consigo converter {field} '{value}' para int, ignorando")
                    continue

            if operator == "eq":
                conditions.append(column == numeric_value)
            elif operator == "gte":
                conditions.append(column >= numeric_value)
            elif operator == "lte":
                conditions.append(column <= numeric_value)
            elif operator == "gt":
                conditions.append(column > numeric_value)
            elif operator == "lt":
                conditions.append(column < numeric_value)
            elif operator == "neq":
                conditions.append(column != numeric_value)

        # Tradução de filtros de texto livre (make, model)
        elif field in ("make", "model"):
            conditions.append(column.ilike(f"%{value}%"))

        # Tradução de filtros categóricos
        elif field in ("state", "city", "color", "body_type"):
            conditions.append(func.lower(column) == value.lower())

    # Monta condição do termo residual (cleaned_query)
    cleaned_query = parsed.cleaned_query.strip()
    # Remove palavras-chave comuns que podem estar no cleaned_query (de diretivas extraídas)
    keywords = ("até", "ate", "acima", "mais", "desde", "a partir", "menor", "maior", "entre", "de", "do", "da")
    cleaned_query_words = cleaned_query.lower().split()
    meaningful_words = [
        w for w in cleaned_query_words
        if w not in keywords and len(w) > 1 and not w.isdigit()
    ]
    meaningful_query = " ".join(meaningful_words).strip() if meaningful_words else ""

    if meaningful_query:
        conditions.append(
            or_(
                CarListing.title.ilike(f"%{meaningful_query}%"),
                CarListing.make.ilike(f"%{meaningful_query}%"),
                CarListing.model.ilike(f"%{meaningful_query}%"),
            )
        )

    return conditions, cleaned_query


def compute_facet_counts(
    db: Session, term: str, extra_conditions: list | None = None
) -> list[FacetCount]:
    """Calcula contagens por faceta em uma única query SQL.

    Monta predicado base (status != 'inativo' + condições de build_search_conditions
    + extra_conditions opcionais), roda UMA ÚNICA query SQL via UNION ALL de 11
    sub-SELECTs (10 facetas + 1 total).

    Args:
        db: sessão SQLAlchemy
        term: termo de busca livre
        extra_conditions: condições SQLAlchemy adicionais (AND), ex. filtros de
            refinamento por faceta escolhidos interativamente pelo usuário.
            Opcional — chamadas existentes sem esse argumento continuam idênticas.

    Returns:
        list[FacetCount]
    """
    conditions, _ = build_search_conditions(term)

    # Predicado base: status != 'inativo' + condições do termo + refinamentos extras
    base_conditions = [CarListing.status != "inativo"] + conditions + list(extra_conditions or [])
    base_predicate = and_(*base_conditions)

    # 1. Faceta 'state'
    q1 = (
        select(
            literal_column("'state'").label("facet"),
            CarListing.state.label("bucket"),
            func.count().label("count"),
        )
        .where(base_predicate)
        .where(CarListing.state.isnot(None))
        .group_by(CarListing.state)
        .order_by(func.count().desc())
        .limit(20)
        .subquery()
    )

    # 2. Faceta 'city'
    q2 = (
        select(
            literal_column("'city'").label("facet"),
            CarListing.city.label("bucket"),
            func.count().label("count"),
        )
        .where(base_predicate)
        .where(CarListing.city.isnot(None))
        .group_by(CarListing.city)
        .order_by(func.count().desc())
        .limit(20)
        .subquery()
    )

    # 3. Faceta 'color'
    q3 = (
        select(
            literal_column("'color'").label("facet"),
            CarListing.color.label("bucket"),
            func.count().label("count"),
        )
        .where(base_predicate)
        .where(CarListing.color.isnot(None))
        .group_by(CarListing.color)
        .order_by(func.count().desc())
        .limit(20)
        .subquery()
    )

    # 4. Faceta 'body_type'
    q4 = (
        select(
            literal_column("'body_type'").label("facet"),
            CarListing.body_type.label("bucket"),
            func.count().label("count"),
        )
        .where(base_predicate)
        .where(CarListing.body_type.isnot(None))
        .group_by(CarListing.body_type)
        .order_by(func.count().desc())
        .limit(20)
        .subquery()
    )

    # 5. Faceta 'doors' (castado para TEXT)
    q5 = (
        select(
            literal_column("'doors'").label("facet"),
            cast(CarListing.doors, Text).label("bucket"),
            func.count().label("count"),
        )
        .where(base_predicate)
        .where(CarListing.doors.isnot(None))
        .group_by(CarListing.doors)
        .order_by(func.count().desc())
        .limit(20)
        .subquery()
    )

    # 6. Faceta 'make'
    q6 = (
        select(
            literal_column("'make'").label("facet"),
            CarListing.make.label("bucket"),
            func.count().label("count"),
        )
        .where(base_predicate)
        .where(CarListing.make.isnot(None))
        .group_by(CarListing.make)
        .order_by(func.count().desc())
        .limit(20)
        .subquery()
    )

    # 7. Faceta 'model'
    q7 = (
        select(
            literal_column("'model'").label("facet"),
            CarListing.model.label("bucket"),
            func.count().label("count"),
        )
        .where(base_predicate)
        .where(CarListing.model.isnot(None))
        .group_by(CarListing.model)
        .order_by(func.count().desc())
        .limit(20)
        .subquery()
    )

    # 8. Faceta 'year' (com bucketing)
    q8 = (
        select(
            literal_column("'year'").label("facet"),
            _year_bucket_expr().label("bucket"),
            func.count().label("count"),
        )
        .where(base_predicate)
        .where(CarListing.year.isnot(None))
        .group_by(_year_bucket_expr())
        .order_by(func.count().desc())
        .subquery()
    )

    # 9. Faceta 'price' (com bucketing)
    q9 = (
        select(
            literal_column("'price'").label("facet"),
            _price_bucket_expr().label("bucket"),
            func.count().label("count"),
        )
        .where(base_predicate)
        .where(CarListing.price.isnot(None))
        .group_by(_price_bucket_expr())
        .order_by(func.count().desc())
        .subquery()
    )

    # 10. Faceta 'mileage_km' (com bucketing)
    q10 = (
        select(
            literal_column("'mileage_km'").label("facet"),
            _mileage_bucket_expr().label("bucket"),
            func.count().label("count"),
        )
        .where(base_predicate)
        .where(CarListing.mileage_km.isnot(None))
        .group_by(_mileage_bucket_expr())
        .order_by(func.count().desc())
        .subquery()
    )

    # 11. Total (sem GROUP BY)
    q11 = select(
        literal_column("'__total__'").label("facet"),
        cast(null(), Text).label("bucket"),
        func.count().label("count"),
    ).where(base_predicate).subquery()

    # Une todas as sub-queries usando union_all
    union_query = (
        select(q1)
        .union_all(select(q2), select(q3), select(q4), select(q5), select(q6), select(q7), select(q8), select(q9), select(q10), select(q11))
    )

    # Executa uma única query
    result = db.execute(union_query)

    # Converte resultado para list[FacetCount]
    facet_counts = []
    for row in result:
        facet_counts.append(FacetCount(
            facet=row.facet,
            bucket=row.bucket,
            count=row.count,
        ))

    return facet_counts
