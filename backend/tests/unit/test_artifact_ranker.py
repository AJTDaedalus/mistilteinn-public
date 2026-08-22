"""G.4 — ranking artifacts by marginal value.

The question is not "what is my best build" (that is the optimizer) but "which of these is
worth keeping". The two answers differ, and the tests here are mostly about the ways a
plausible-looking ranking gets that wrong: scoring a piece without reference to what it
replaces, averaging away a piece that is superb for exactly one character, and inventing a
second definition of what a build is worth.
"""

from __future__ import annotations

import pytest

from app.formula.genshin import tags
from app.formula.genshin.damage import Hit
from app.pando.calculator import NodeRegistry
from app.services import artifact_ranker
from app.services.artifact_optimizer import (
    ArtifactCandidate,
    OptimizerInputError,
    SetBonus,
    bonuses_by_set,
    build_combination_log,
)
from app.services.artifact_ranker import (
    ContextScore,
    RankContext,
    RankProgress,
    rank,
)
from app.services.damage_calculator import BuildEvaluator, Enemy
from app.services.stat_calculator import build_log

ORDINARY = Enemy(level=90, resistances=dict.fromkeys(tags.DAMAGE_CHANNELS, 0.1))
CRYO_HIT = Hit(multiplier=2.0, channel="cryo", scope="burst")
PYRO_HIT = Hit(multiplier=2.0, channel="pyro", scope="burst")

_MAIN_STATS = {
    "equip_bracer": "FIGHT_PROP_HP",
    "equip_necklace": "FIGHT_PROP_ATTACK",
    "equip_shoes": "FIGHT_PROP_ATTACK_PERCENT",
    "equip_ring": "FIGHT_PROP_ICE_ADD_HURT",
    "equip_dress": "FIGHT_PROP_CRITICAL_HURT",
}


def _base():
    log = build_log(NodeRegistry())
    log.add(tags.Q_BASE_ATK, 800.0, tags.SRC_CHARACTER, "character")
    log.add(tags.Q_BASE_ATK, 500.0, tags.SRC_WEAPON, "weapon")
    log.add(tags.Q_CRIT_RATE, 0.30, tags.SRC_CHARACTER, "base")
    log.add(tags.Q_CRIT_DMG, 0.5, tags.SRC_CHARACTER, "base")
    return tuple(log.contributions)


def _piece(slot, name, *, set_id=1, substats=(), main=None):
    return ArtifactCandidate(
        artifact_id=name, slot=slot, set_id=set_id, rarity=5, level=20,
        main_stat=main or _MAIN_STATS[slot], substats=tuple(substats),
    )


def _equipped(**overrides):
    worn = {slot: _piece(slot, f"worn-{slot}") for slot in _MAIN_STATS}
    worn.update(overrides)
    return tuple(worn.values())


def _context(name="main", hit=CRYO_HIT, weight=1.0, equipped=None):
    return RankContext(
        name=name,
        base_contributions=_base(),
        equipped=equipped or _equipped(),
        hit=hit,
        enemy=ORDINARY,
        character_level=90,
        weight=weight,
    )


# ---- The measure -----------------------------------------------------------

def test_a_ranking_is_against_what_is_already_worn():
    """A flat score says a player's worst flower is excellent. True, and useless — they
    already have a better one. The measure is what the piece is worth *instead of*."""
    worn_goblet = _piece("equip_ring", "worn-equip_ring", substats=(
        {"stat": "FIGHT_PROP_CRITICAL_HURT", "value": 0.5},))
    context = _context(equipped=_equipped(equip_ring=worn_goblet))

    better = _piece("equip_ring", "better", substats=(
        {"stat": "FIGHT_PROP_CRITICAL_HURT", "value": 0.9},))
    worse = _piece("equip_ring", "worse", substats=(
        {"stat": "FIGHT_PROP_CRITICAL_HURT", "value": 0.1},))

    result = rank([better, worse], [context])

    assert [a.artifact_id for a in result.artifacts] == ["better", "worse"]
    assert result.artifacts[0].mean_improvement_pct > 0
    # A piece worse than what is equipped is worth a *negative* amount, not zero. Clamping
    # it would say "no change", which is the opposite of what it tells a player.
    assert result.artifacts[1].mean_improvement_pct < 0


def test_the_piece_already_worn_scores_exactly_zero():
    """It is its own baseline. Anything else means the swap and the baseline disagree about
    what a build is."""
    context = _context()
    worn = next(a for a in context.equipped if a.slot == "equip_ring")

    result = rank([worn], [context])

    assert result.artifacts[0].mean_improvement_pct == pytest.approx(0.0)
    assert result.baselines["main"] == pytest.approx(result.artifacts[0].scores[0].damage)


def test_the_ranker_and_the_optimizer_agree_on_what_a_build_is_worth():
    """One definition of a build's damage, or the tool contradicts itself.

    The ranker's baseline must be exactly the number `build_combination_log` plus the
    evaluator produce for the same five pieces — the same path the optimizer scores on.
    """
    context = _context()
    result = rank([_piece("equip_ring", "any")], [context])

    log, _ = build_combination_log(_base(), context.equipped, bonuses_by_set(()))
    expected = BuildEvaluator(
        registry=log.registry, enemy=ORDINARY, character_level=90,
    ).evaluate(CRYO_HIT).expected

    assert result.baselines["main"] == pytest.approx(expected)


def test_swapping_only_touches_the_candidates_own_slot():
    context = _context()
    candidate = _piece("equip_dress", "new-circlet", substats=(
        {"stat": "FIGHT_PROP_CRITICAL_HURT", "value": 0.4},))

    result = rank([candidate], [context])
    swapped_damage = result.artifacts[0].scores[0].damage

    worn_without_circlet = [a for a in context.equipped if a.slot != "equip_dress"]
    log, _ = build_combination_log(
        _base(), [*worn_without_circlet, candidate], bonuses_by_set(()),
    )
    expected = BuildEvaluator(
        registry=log.registry, enemy=ORDINARY, character_level=90,
    ).evaluate(CRYO_HIT).expected

    assert swapped_damage == pytest.approx(expected)


# ---- Contexts --------------------------------------------------------------

#: A Pyro goblet, against a build wearing a Cryo one. The elemental main stat is the only
#: thing here that is genuinely context-dependent: a crit substat gains the *same
#: percentage* in every context, because crit is a separate multiplicative factor, so a
#: test built on one would compare two identical numbers and pass on floating-point noise.
def _pyro_goblet():
    return _piece("equip_ring", "pyro-goblet", main="FIGHT_PROP_FIRE_ADD_HURT")


def test_a_piece_that_is_superb_for_one_character_keeps_its_best_context():
    """The mean hides it, and a player who fed the piece away on the mean would be right to
    be cross. A Pyro goblet is a large gain for one team and a downgrade for the other."""
    result = rank(
        [_pyro_goblet()],
        [_context("cryo-team", CRYO_HIT), _context("pyro-team", PYRO_HIT)],
    )
    ranked = result.artifacts[0]

    by_context = {s.context: s.improvement_pct for s in ranked.scores}

    assert ranked.best_context == "pyro-team"
    assert by_context["pyro-team"] > 0 > by_context["cryo-team"]
    # The mean is not the story: it lands *positive* here even though the piece is a 32%
    # downgrade for the cryo team, because the pyro gain is larger than the cryo loss. A
    # ranking that reported only the mean would read as "mild upgrade, equip it".
    assert ranked.best_improvement_pct > ranked.mean_improvement_pct > 0
    assert by_context["cryo-team"] < ranked.mean_improvement_pct


def test_weight_lets_a_main_team_outvote_an_experiment_without_silencing_it():
    even = rank(
        [_pyro_goblet()], [_context("cryo", CRYO_HIT), _context("pyro", PYRO_HIT)],
    )
    weighted = rank(
        [_pyro_goblet()],
        [_context("cryo", CRYO_HIT, weight=1.0), _context("pyro", PYRO_HIT, weight=9.0)],
    )

    assert weighted.artifacts[0].mean_improvement_pct > even.artifacts[0].mean_improvement_pct
    # Still counted, not silenced: the 10% context drags the weighted mean below its best.
    assert (
        weighted.artifacts[0].mean_improvement_pct
        < weighted.artifacts[0].best_improvement_pct
    )


def test_set_bonuses_are_read_the_same_way_the_search_reads_them():
    """A piece that completes a 4-piece is worth the bonus, not just its own stats."""
    bonus = SetBonus(set_id=2, pieces_required=4, add_props=(
        {"prop_type": "FIGHT_PROP_CRITICAL_HURT", "value": 0.8},))
    worn = _equipped(
        **{
            slot: _piece(slot, f"worn-{slot}", set_id=2)
            for slot in ("equip_bracer", "equip_necklace", "equip_shoes")
        },
    )
    context = _context(equipped=worn)

    completes = _piece("equip_ring", "completes-the-set", set_id=2)
    plain = _piece("equip_ring", "plain", set_id=3)

    result = rank([completes, plain], [context], set_bonuses=[bonus])

    assert result.artifacts[0].artifact_id == "completes-the-set"
    assert result.artifacts[0].mean_improvement_pct > 0


# ---- Refusals --------------------------------------------------------------

def test_a_context_missing_a_slot_is_refused():
    """A ranking measures a swap. With an empty slot there is nothing to swap against, and
    every candidate for it would score as a free upgrade."""
    with pytest.raises(OptimizerInputError, match="equip_ring"):
        RankContext(
            name="broken",
            base_contributions=_base(),
            equipped=tuple(a for a in _equipped() if a.slot != "equip_ring"),
            hit=CRYO_HIT, enemy=ORDINARY, character_level=90,
        )


def test_two_artifacts_in_one_slot_is_refused():
    worn = _equipped()
    with pytest.raises(OptimizerInputError, match="two artifacts in one slot"):
        RankContext(
            name="doubled",
            base_contributions=_base(),
            equipped=(*worn, _piece("equip_ring", "spare")),
            hit=CRYO_HIT, enemy=ORDINARY, character_level=90,
        )


def test_a_non_positive_weight_is_refused():
    with pytest.raises(OptimizerInputError, match="weight"):
        _context(weight=0.0)


def test_ranking_with_no_contexts_is_refused():
    with pytest.raises(OptimizerInputError, match="at least one context"):
        rank([_piece("equip_ring", "x")], [])


def test_a_candidate_in_an_unknown_slot_is_refused():
    """Refused by the shared validation, which already names the five. The ranker had its
    own copy of that check and its own copy of the list; one place is enough."""
    odd = ArtifactCandidate(
        artifact_id="odd", slot="equip_hat", set_id=1, rarity=5, level=20,
        main_stat="FIGHT_PROP_HP",
    )
    with pytest.raises(OptimizerInputError, match="equip_hat"):
        rank([odd], [_context()])


def test_asking_for_a_slot_that_does_not_exist_is_refused():
    result = rank([_piece("equip_ring", "x")], [_context()])
    with pytest.raises(OptimizerInputError, match="equip_hat"):
        result.for_slot("equip_hat")


# ---- Reading the result ----------------------------------------------------

def test_for_slot_answers_what_should_i_farm_one_slot_at_a_time():
    candidates = [
        _piece("equip_ring", "goblet-a", substats=(
            {"stat": "FIGHT_PROP_CRITICAL_HURT", "value": 0.4},)),
        _piece("equip_dress", "circlet-a", substats=(
            {"stat": "FIGHT_PROP_CRITICAL_HURT", "value": 0.9},)),
    ]
    result = rank(candidates, [_context()])

    goblets = result.for_slot("equip_ring")
    assert [a.artifact_id for a in goblets] == ["goblet-a"]
    assert [a.artifact_id for a in result.for_slot("equip_dress")] == ["circlet-a"]


def test_a_zero_baseline_ranks_as_zero_rather_than_infinity():
    """An unbuilt character is a real thing to hand this. Every candidate being infinitely
    better than nothing is not a ranking."""
    score = ContextScore(context="x", damage=500.0, baseline=0.0)

    assert score.improvement == 500.0
    assert score.improvement_pct == 0.0


# ---- Progress --------------------------------------------------------------

def test_progress_reaches_the_end(monkeypatch):
    monkeypatch.setattr("app.services.artifact_ranker.PROGRESS_TICK_SECONDS", 0.0)
    seen: list[RankProgress] = []

    rank(
        [_piece("equip_ring", f"g{i}") for i in range(3)],
        [_context("a"), _context("b", PYRO_HIT)],
        progress_callback=seen.append,
    )

    assert len(seen) > 1
    assert seen[-1].fraction == 1.0
    assert seen[-1].total == 6
    assert seen[0].elapsed_seconds >= 0.0


def test_progress_fraction_is_one_for_an_empty_total():
    assert RankProgress(0, 0, 0.0).fraction == 1.0


def test_a_ranking_with_no_candidates_is_empty_not_an_error():
    """Nothing to rank is an answer, unlike no context to rank against."""
    result = rank([], [_context()])

    assert result.artifacts == ()
    assert "main" in result.baselines


# ---- Findings from reviewing this PR ---------------------------------------

def test_a_conditional_set_bonus_is_reported_not_silently_dropped():
    """The search reports these. A ranking that dropped them would leave "why is this
    4-piece worth nothing" unanswerable in exactly the tool a player consults *before*
    deciding whether to keep the piece.

    Counted by tier identity, not per swap — the PR #9 correction, which would otherwise
    have to be made a second time here once the numbers got large enough to notice.
    """
    conditional = SetBonus(set_id=2, pieces_required=2, add_props=(
        {"prop_type": "FIGHT_PROP_NONE", "value": 0},))
    worn = _equipped(**{
        slot: _piece(slot, f"worn-{slot}", set_id=2)
        for slot in ("equip_bracer", "equip_necklace")
    })
    context = _context(equipped=worn)

    result = rank(
        [_piece("equip_ring", f"g{i}") for i in range(4)],
        [context, _context("second", PYRO_HIT, equipped=worn)],
        set_bonuses=[conditional],
    )

    # Four candidates x two contexts x (one baseline each) all meet the same tier.
    assert result.skipped_conditional_bonuses == 1


def test_every_piece_is_validated_once_not_once_per_swap(monkeypatch):
    """The unchanged four-fifths of a build were re-validated for every candidate in every
    context — the repeated-immutable-work finding from the search, at a smaller exponent."""
    calls: list[str] = []
    real = artifact_ranker.validated_stats

    def counting(candidate):
        calls.append(candidate.artifact_id)
        return real(candidate)

    monkeypatch.setattr(artifact_ranker, "validated_stats", counting)

    candidates = [_piece("equip_ring", f"g{i}") for i in range(4)]
    rank(candidates, [_context("a"), _context("b", PYRO_HIT)])

    # Five worn pieces (shared by both contexts) plus four candidates. Once each.
    assert sorted(calls) == sorted({*(c.artifact_id for c in candidates),
                                   *(w.artifact_id for w in _equipped())})


def test_an_illegal_candidate_is_named():
    illegal = ArtifactCandidate(
        artifact_id="impossible-flower", slot="equip_bracer", set_id=1, rarity=5,
        level=20, main_stat="FIGHT_PROP_CRITICAL_HURT",
    )
    with pytest.raises(OptimizerInputError, match="impossible-flower"):
        rank([illegal], [_context()])
