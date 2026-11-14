import json


def test_scrape_settings_roundtrip_preserves_existing_options(scrape_data_dir):
    from scraper.scrape_settings import ScrapeSettings
    scrape_data_dir.mkdir(parents=True, exist_ok=True)
    path = scrape_data_dir / "scrape_config.json"
    path.write_text('{"legacy_option": true}', encoding="utf-8")
    settings = ScrapeSettings(tmdb_token="test-token", timeout=12)
    settings.save()
    assert ScrapeSettings.load().tmdb_token == "test-token"
    assert ScrapeSettings.load().timeout == 12
    assert json.loads(path.read_text(encoding="utf-8"))["legacy_option"] is True
    assert not list(scrape_data_dir.glob("*.tmp"))


def test_settings_reject_invalid_network_values():
    import pytest
    from scraper.scrape_settings import ScrapeSettings
    with pytest.raises(ValueError, match="超时"):
        ScrapeSettings(timeout=0).save()
    with pytest.raises(ValueError, match="代理"):
        ScrapeSettings(proxy="file:///secret").save()
