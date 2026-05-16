from app.sources.auctions.registry import (
    get_auction_source_definition,
    is_auction_source_user_eligible,
    list_user_eligible_auction_source_keys,
    render_user_eligible_auction_sources_hint,
    list_supported_auction_source_keys,
    render_supported_auction_sources_hint,
    resolve_auction_source_alias,
)


def test_resolve_aliases():
    assert resolve_auction_source_alias("vip") == "vip_auctions"
    assert resolve_auction_source_alias("mega") == "mega_auctions"
    assert resolve_auction_source_alias("win") == "win_auctions"
    assert resolve_auction_source_alias("copart") == "copart_auctions"
    assert resolve_auction_source_alias("sodre") == "sodre_auctions"
    assert resolve_auction_source_alias("superbid") == "superbid_auctions"
    assert resolve_auction_source_alias("invalid") is None


def test_supported_source_keys_and_enrich_flags():
    keys = list_supported_auction_source_keys()
    assert {"vip_auctions", "mega_auctions", "win_auctions", "sodre_auctions", "superbid_auctions", "copart_auctions"}.issubset(keys)

    assert get_auction_source_definition("vip").supports_enrich is True
    assert get_auction_source_definition("mega").supports_enrich is False
    assert get_auction_source_definition("win").supports_enrich is False
    assert get_auction_source_definition("copart").supports_enrich is False
    assert get_auction_source_definition("sodre").supports_enrich is False


def test_render_hint():
    assert "sodre" in render_supported_auction_sources_hint()
    assert "superbid" in render_supported_auction_sources_hint()


def test_user_eligibility_policy():
    assert is_auction_source_user_eligible("vip")
    assert not is_auction_source_user_eligible("mega")
    assert not is_auction_source_user_eligible("win")
    assert not is_auction_source_user_eligible("sodre")
    assert not is_auction_source_user_eligible("superbid")
    assert not is_auction_source_user_eligible("copart")
    assert list_user_eligible_auction_source_keys() == {"vip_auctions"}
    assert render_user_eligible_auction_sources_hint() == "Sources elegíveis: vip"
