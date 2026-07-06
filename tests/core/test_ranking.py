from __future__ import annotations

from argumentwinner.core.models import CandidateResponse, Persona, Risk, SpiceLevel
from argumentwinner.core.ranking import order_candidates
from argumentwinner.core.strategy import ALLOWED_RISKS


def cand(text: str, risk: Risk = Risk.SAFE) -> CandidateResponse:
    return CandidateResponse(text=text, persona=Persona.LOGICIAN, tactic_note="t", risk=risk)


MEDIUM = ALLOWED_RISKS[SpiceLevel.MEDIUM]


def test_keeps_llm_order_when_all_clean():
    candidates = [cand("alpha argument one"), cand("beta argument two"), cand("gamma three")]
    assert order_candidates(candidates, MEDIUM, 1800) == tuple(candidates)


def test_demotes_over_risk_candidates():
    nuclear = cand("scorched earth reply", Risk.NUCLEAR)
    safe = cand("measured reply")
    assert order_candidates([nuclear, safe], MEDIUM, 1800)[0] is safe


def test_demotes_overlength_candidates():
    long = cand("word " * 500)
    short = cand("short and sharp")
    assert order_candidates([long, short], MEDIUM, 100)[0] is short


def test_demotes_near_duplicates_keeping_first():
    first = cand("your entire argument rests on popularity alone my friend")
    dupe = cand("your entire argument rests on popularity alone friend")
    distinct = cand("what evidence would change your mind")
    ordered = order_candidates([first, dupe, distinct], MEDIUM, 1800)
    assert ordered[0] is first
    assert ordered[1] is distinct
    assert ordered[2] is dupe


def test_stable_between_equal_demerits():
    a = cand("completely different words here", Risk.NUCLEAR)
    b = cand("another unrelated set of tokens", Risk.NUCLEAR)
    ordered = order_candidates([a, b], MEDIUM, 1800)
    assert ordered == (a, b)
