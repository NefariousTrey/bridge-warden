from bridge_warden.ai import ScamTextModel, llm_explain, tokens


def test_tokens_include_bigrams():
    assert "gift_cards" in tokens("Buy gift cards")


def test_model_separates_scam_from_normal():
    m = ScamTextModel()
    assert m.scam_probability("send bitcoin to unlock your account") > 0.9
    assert m.scam_probability("payment for logo design invoice") < 0.2


def test_unknown_words_give_no_signal():
    assert ScamTextModel().scam_probability("zzqx blorf") == 0.0


def test_model_trains_from_examples():
    m = ScamTextModel([{"text": "banana fee now", "label": "scam"}, {"text": "apple order", "label": "ok"}])
    assert m.scam_probability("banana") > m.scam_probability("apple")


def test_llm_is_optional(monkeypatch):
    monkeypatch.delenv("CHECKER_LLM_URL", raising=False)
    assert llm_explain({"action": "payout"}, {"verdict": "hold"}) is None


def test_llm_failure_is_ignored(monkeypatch):
    monkeypatch.setenv("CHECKER_LLM_URL", "http://127.0.0.1:9/nothing")
    assert llm_explain({"action": "payout"}, {"verdict": "hold"}, timeout=1) is None
