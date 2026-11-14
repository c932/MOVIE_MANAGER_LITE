import json

import pytest


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


@pytest.mark.parametrize('field', ['tmdb_token', 'tmdb_api_key', 'omdb_api_key', 'language', 'proxy'])
@pytest.mark.parametrize('control', ['\r', '\n', '\t', '\x00', '\x1f', '\x7f', '\x85'])
def test_settings_reject_control_characters_without_echoing_value(field, control):
    from scraper.scrape_settings import ScrapeSettings
    value = 'fixture-prefix' + control + 'fixture-suffix'
    with pytest.raises(ValueError) as error:
        ScrapeSettings(**{field: value}).validate()
    assert 'fixture-prefix' not in str(error.value)
    assert 'fixture-suffix' not in str(error.value)


def test_invalid_token_cannot_replace_saved_config_and_load_fails_closed(scrape_data_dir):
    from scraper.scrape_settings import ScrapeSettings
    ScrapeSettings(tmdb_token='valid-fixture-token').save()
    path = scrape_data_dir / 'scrape_config.json'
    before = path.read_bytes()
    with pytest.raises(ValueError):
        ScrapeSettings(tmdb_token='fixture\r\ninjected').save()
    assert path.read_bytes() == before
    path.write_text(json.dumps({'tmdb_token': 'fixture\r\ninjected'}), encoding='utf-8')
    assert ScrapeSettings.load().tmdb_token == ''
