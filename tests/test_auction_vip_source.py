from pathlib import Path
from datetime import datetime, timezone

from app.sources.auctions import vip
from app.sources.auctions.parsing import parse_datetime_br

FIXTURE_WITH_CARDS = Path("tests/fixtures/auctions/vip_listing_with_cards.html")
FIXTURE_NO_CARDS = Path("tests/fixtures/auctions/vip_listing_without_cards.html")


def test_allowlist_accepts_vip_domains():
    assert vip.validate_auction_source_url("https://www.vipleiloes.com.br/", vip.ALLOWED_DOMAINS)
    assert vip.validate_auction_source_url("https://www2.vipleiloes.com.br/lista", vip.ALLOWED_DOMAINS)


def test_allowlist_rejects_blocked_or_outside_domains():
    assert not vip.validate_auction_source_url("https://vipleiloes.club/", vip.ALLOWED_DOMAINS)
    assert not vip.validate_auction_source_url("https://example.com/", vip.ALLOWED_DOMAINS)


def test_parser_groups_duplicate_blocks_by_url(monkeypatch):
    html = FIXTURE_WITH_CARDS.read_text(encoding="utf-8")

    class FakeResp:
        text = html

        def raise_for_status(self):
            return None

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def get(self, url):
            return FakeResp()

    monkeypatch.setattr(vip.httpx, "Client", FakeClient)
    lots = vip.fetch_vip_lots(limit=5)

    assert len(lots) == 2
    by_id = {lot.external_id: lot for lot in lots}
    assert set(by_id) == {"157925", "156375"}

    first = by_id["157925"]
    assert first.title == "DUCATO MAXICARGO - 2010/2011"
    assert first.status == "live"
    assert first.make == "Fiat"
    assert first.mileage_km == 180000
    assert first.year == 2010
    assert first.item_type == "car"
    assert first.extras.get("plate_final") == "7"

    second = by_id["156375"]
    assert second.title == "SANDERO EXPR 10 - 2018/2019"
    assert second.status == "live"
    assert second.make == "Renault"
    assert second.mileage_km == 95000
    assert second.year == 2018
    assert second.item_type == "car"


def test_fallback_without_cards_returns_reason(monkeypatch):
    html = FIXTURE_NO_CARDS.read_text(encoding="utf-8")

    class FakeResp:
        text = html

        def raise_for_status(self):
            return None

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def get(self, url):
            return FakeResp()

    monkeypatch.setattr(vip.httpx, "Client", FakeClient)
    lots = vip.fetch_vip_lots(limit=5)
    assert lots == []
    assert vip.get_last_reason() == "no_public_lot_cards_found"


def test_extract_total_bids_requires_explicit_field():
    assert vip._extract_total_bids_vip("<article>AXOR 2540 S - 2009/2009</article>", "AXOR 2540 S - 2009/2009") is None
    assert vip._extract_total_bids_vip("<article>CLASSIC LS - 2012/2013</article>", "CLASSIC LS - 2012/2013") is None


def test_extract_total_bids_accepts_explicit_patterns():
    assert vip._extract_total_bids_vip("<div>Lances: 7</div>", "texto qualquer") == 7
    assert vip._extract_total_bids_vip("<div>status</div>", "7 lances") == 7


def test_extract_total_bids_discards_invalid_large_values():
    assert vip._extract_total_bids_vip("<div>Lances: 10001</div>", "Lances: 10001") is None


def test_normalize_status_maps_dou_lhe_duas_to_live():
    assert vip._normalize_status_vip("Dou-lhe duas") == "live"


FIXTURE_DETAIL_BIDS = Path("tests/fixtures/auctions/vip_detail_with_bids.html")
FIXTURE_DETAIL_MIN = Path("tests/fixtures/auctions/vip_detail_minimal.html")


def test_parse_detail_with_bids_and_dates_location_image():
    html = FIXTURE_DETAIL_BIDS.read_text(encoding="utf-8")
    detail = vip.parse_vip_lot_detail_html(html, base_url="https://www.vipleiloes.com.br/evento/anuncio/x")
    assert float(detail["initial_bid"]) == 5000.0
    assert float(detail["current_bid"]) == 8200.0
    assert detail["auction_end_at"] is not None
    assert detail["city"] == "Curitiba"
    assert detail["state"] == "PR"
    assert detail["thumbnail_url"].endswith("/images/lote1.jpg")
    assert detail["lot_number"] == "444"
    assert detail["image_count"] >= 1


def test_parse_detail_minimal_does_not_break():
    html = FIXTURE_DETAIL_MIN.read_text(encoding="utf-8")
    detail = vip.parse_vip_lot_detail_html(html)
    assert isinstance(detail, dict)


def test_detail_rejects_non_allowlisted_domain():
    try:
        vip.fetch_vip_lot_detail("https://evil.com/lot")
    except ValueError as exc:
        assert "invalid_detail_url" in str(exc)
    else:
        assert False


def test_enrich_failure_keeps_base_and_adds_warning(monkeypatch):
    lot = vip.NormalizedAuctionLot(source="vip_auctions", external_id="1", title="Base", url="https://www.vipleiloes.com.br/evento/anuncio/1")

    def boom(url, timeout=15.0):
        raise RuntimeError("x")

    monkeypatch.setattr(vip, "fetch_vip_lot_detail", boom)
    out = vip.enrich_vip_lot_detail(lot)
    assert out.title == "Base"
    assert "parser_warnings" in out.extras


def test_parse_detail_sanitizes_dirty_location_state_lot_and_images():
    html = """
    <div>Local do Lote: &gt;Local do Lote:</div>
    <div>UF: DO</div>
    <div>cidade: &gt;Local do Lote:</div>
    <script>{"lote": "100", "x":1}</script>
    <img src="https://www.vipleiloes.com.br/images/vipleiloes/logo.svg">
    <img src="https://www.vipleiloes.com.br/images/fixbtn-wapp.png">
    <img src="https://www.vipleiloes.com.br/images/logo-footer.png">
    <img src="https://www.vipleiloes.com.br/images/aleibras.svg">
    <img src="https://www.vipleiloes.com.br/images/leilao-seguro.svg">
    <img src="https://armazupvipleiloesprd.blob.core.windows.net/uploads/lote-real-1.jpg">
    <img src="https://armazupvipleiloesprd.blob.core.windows.net/uploads/lote-real-2.jpg">
    <div>Lance atual: R$ 8.200,00</div>
    <div>Lances: 3</div>
    """
    detail = vip.parse_vip_lot_detail_html(html, base_url="https://www.vipleiloes.com.br/evento/anuncio/x")
    assert detail.get("city") is None
    assert detail.get("state") is None
    assert detail.get("location") is None
    assert detail.get("lot_number") == "100"
    assert detail["thumbnail_url"].startswith("https://armazupvipleiloesprd.blob.core.windows.net/uploads/")
    assert detail["image_count"] == 2
    assert all("logo" not in img.lower() for img in detail["images"])
    assert float(detail["current_bid"]) == 8200.0
    assert detail["total_bids"] == 3


def test_apply_vip_detail_does_not_overwrite_with_dirty_values():
    lot = vip.NormalizedAuctionLot(
        source="vip_auctions",
        external_id="1",
        title="Base",
        city="Curitiba",
        state="PR",
        location="Curitiba/PR",
        lot_number="321",
        thumbnail_url="https://armazupvipleiloesprd.blob.core.windows.net/uploads/good.jpg",
        images=["https://armazupvipleiloesprd.blob.core.windows.net/uploads/good.jpg"],
    )
    dirty = {
        "city": ">Local do Lote:",
        "state": "DO",
        "location": "Local do Lote",
        "lot_number": '": "100",',
        "thumbnail_url": "https://www.vipleiloes.com.br/images/vipleiloes/logo.svg",
        "images": ["https://www.vipleiloes.com.br/images/logo-footer.png"],
    }
    out = vip.apply_vip_detail(lot, dirty)
    assert out.city == "Curitiba"
    assert out.state == "PR"
    assert out.location == "Curitiba/PR"
    assert out.lot_number == "321"
    assert out.thumbnail_url.endswith("/good.jpg")
    assert out.to_payload()["image_count"] == 1


def test_parse_datetime_br_supported_formats():
    assert parse_datetime_br("15/05/2026 10:00") == datetime(2026, 5, 15, 13, 0, tzinfo=timezone.utc)
    assert parse_datetime_br("15/05/2026 às 10:00") == datetime(2026, 5, 15, 13, 0, tzinfo=timezone.utc)
    assert parse_datetime_br("15/05/2026 - 10:00") == datetime(2026, 5, 15, 13, 0, tzinfo=timezone.utc)
    assert parse_datetime_br("15/05/26 10:00") == datetime(2026, 5, 15, 13, 0, tzinfo=timezone.utc)
    assert parse_datetime_br("2026-05-15T10:00:00") == datetime(2026, 5, 15, 13, 0, tzinfo=timezone.utc)
    assert parse_datetime_br("xpto") is None


def test_parse_detail_extracts_end_at_from_labels_and_iso():
    detail = vip.parse_vip_lot_detail_html("<div>Encerramento: 15/05/2026 18:30</div>")
    assert detail["auction_end_at"] == datetime(2026, 5, 15, 21, 30, tzinfo=timezone.utc)
    detail2 = vip.parse_vip_lot_detail_html("<div>Leilão encerra em 15/05/2026 às 18:30</div>")
    assert detail2["auction_end_at"] == datetime(2026, 5, 15, 21, 30, tzinfo=timezone.utc)
    detail3 = vip.parse_vip_lot_detail_html('<script>{"auctionEndAt":"2026-05-15T18:30:00"}</script>')
    assert detail3["auction_end_at"] == datetime(2026, 5, 15, 21, 30, tzinfo=timezone.utc)


def test_apply_vip_detail_preserves_existing_end_at_when_new_missing():
    lot = vip.NormalizedAuctionLot(
        source="vip_auctions",
        external_id="1",
        auction_end_at=datetime(2026, 5, 15, 21, 30, tzinfo=timezone.utc),
    )
    out = vip.apply_vip_detail(lot, {"current_bid": 1})
    assert out.auction_end_at == datetime(2026, 5, 15, 21, 30, tzinfo=timezone.utc)


def test_infer_item_type_motorcycle_heuristics():
    assert vip._infer_item_type("CG 160 Start", "Honda", None, "") == "motorcycle"
    assert vip._infer_item_type("SHI 175 2024/2024", "Shineray", None, "") == "motorcycle"
    assert vip._infer_item_type("XY200GY-04", "Shineray", None, "") == "motorcycle"
    assert vip._infer_item_type("Yamaha Fazer 250", "Yamaha", None, "") == "motorcycle"
    assert vip._infer_item_type("Dafra Next 300", "Dafra", None, "") == "motorcycle"


def test_infer_item_type_keeps_honda_cars_as_car():
    assert vip._infer_item_type("Honda Civic EXL 2020", "Honda", 10000, "") == "car"
    assert vip._infer_item_type("Honda HR-V EX 2021", "Honda", 20000, "") == "car"
