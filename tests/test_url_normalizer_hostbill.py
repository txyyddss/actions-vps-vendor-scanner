from src.misc.url_normalizer import normalize_url


def test_normalize_url_preserves_hostbill_pseudo_route_query() -> None:
    url = "https://clients.example.com/index.php?/cart/&action=add&id=94"
    normalized = normalize_url(url, force_english=True)
    assert (
        normalized
        == "https://clients.example.com/index.php?/cart/&action=add&id=94&language=english"
    )


def test_normalize_url_keeps_hostbill_path_style_route_intact() -> None:
    url = "https://clients.example.com/cart/&action=add&id=94"
    normalized = normalize_url(url, force_english=True)
    assert normalized == url
