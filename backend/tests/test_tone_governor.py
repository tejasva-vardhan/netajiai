from backend.app.application.tone_governor import DeterministicToneGovernor


def test_tone_governor_blocks_advice_categories_but_allows_civic_text():
    governor = DeterministicToneGovernor()

    assert governor.review("Which political party should I vote for?").allowed is False
    assert governor.review("Can you give me legal advice?").reason_code == "legal_advice"
    assert governor.review("Mujhe medical treatment chahiye").category == "medical"
    assert governor.review("Mujhe pothole ki complaint likhni hai").allowed is True
    assert governor.review("Is verified yojana ki eligibility batao").allowed is True


def test_tone_governor_detects_explicit_threat_without_rewriting_facts():
    decision = DeterministicToneGovernor().review("I will attack the officer")

    assert decision.allowed is False
    assert decision.category == "abuse"
    assert decision.reason_code == "threatening_or_abusive_language"
