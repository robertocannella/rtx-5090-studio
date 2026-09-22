from types import SimpleNamespace

import pipeline
import prompts


def _ns(domain):
    return SimpleNamespace(domain=domain)


def test_new_manifest_uses_requested_domain():
    m = {}  # no "domain" key yet, as init_or_load_manifest would leave a truly fresh dict
    domain = pipeline.resolve_domain(_ns("math"), m)
    assert domain == "math"
    assert m["domain"] == "math"


def test_resumed_manifest_keeps_its_stored_domain(capsys):
    m = {"domain": "history"}
    domain = pipeline.resolve_domain(_ns("math"), m)
    assert domain == "history"
    assert m["domain"] == "history"
    out = capsys.readouterr().out
    assert "domain=" in out  # informs the user their --domain was ignored


def test_resumed_manifest_with_matching_domain_is_silent(capsys):
    m = {"domain": "discovery"}
    domain = pipeline.resolve_domain(_ns("discovery"), m)
    assert domain == "discovery"
    out = capsys.readouterr().out
    assert out == ""


def test_manifest_without_a_domain_key_falls_back_to_requested_domain():
    # Simulates an episode created before the domain feature existed.
    m = {"segments": []}
    domain = pipeline.resolve_domain(_ns("history"), m)
    assert domain == "history"
    assert m["domain"] == "history"


def test_init_or_load_manifest_stores_domain_for_new_episode(tmp_path):
    import manifest as manifest_mod
    paths = manifest_mod.episode_paths(str(tmp_path), "domain-test")
    m = pipeline.init_or_load_manifest(
        paths, "Some Topic", 60, "af_heart", 1.0, 0.0, 0.5, "math", "qwen3:32b", force=False,
    )
    assert m["domain"] == "math"


def test_all_registered_domains_are_valid_for_resolve_domain():
    for domain in prompts.DOMAINS:
        m = {}
        assert pipeline.resolve_domain(_ns(domain), m) == domain
