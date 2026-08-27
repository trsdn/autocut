"""Cut plan construction: fillers, pause trimming, protected ranges, merging."""
from __future__ import annotations

import json

import pytest

from autocut.plan import CutPlan, Removal, build_plan


def word(w: str, start: float, end: float) -> dict:
    return {"word": w, "startTime": start, "endTime": end, "confidence": 1.0}


def plan(**overrides):
    """build_plan with an inert baseline, so each test varies one thing."""
    kwargs = dict(
        source="clip.mp4",
        duration=10.0,
        words=[],
        silences_coarse=[],
        silences_fine=[],
    )
    kwargs.update(overrides)
    return build_plan(**kwargs)


# --------------------------------------------------------------------------
# Keep/remove inversion
# --------------------------------------------------------------------------
def test_empty_input_keeps_the_whole_clip():
    p = plan()

    assert p.keep == [(0.0, 10.0)]
    assert p.removed == []
    assert p.total_removed() == 0.0


def test_keep_segments_are_the_complement_of_removals():
    p = plan(redundancy_ranges=[(2.0, 4.0, "restated")])

    assert p.keep == [(0.0, 2.0), (4.0, 10.0)]
    assert p.total_removed() == pytest.approx(2.0)


def test_removal_touching_the_start_drops_the_leading_segment():
    p = plan(redundancy_ranges=[(0.0, 3.0, "intro waffle")])

    assert p.keep == [(3.0, 10.0)]


def test_removal_running_to_the_end_drops_the_trailing_segment():
    p = plan(duration=10.0, redundancy_ranges=[(8.0, 10.0, "weak outro")])

    assert p.keep == [(0.0, 8.0)]


def test_segments_shorter_than_min_keep_are_discarded():
    """A 0.05 s sliver between two cuts is not worth a concat segment."""
    p = plan(
        redundancy_ranges=[(2.0, 4.0, "a"), (4.05, 6.0, "b")],
        min_keep=0.10,
    )

    # The 4.00-4.05 sliver is dropped; 0.05 < 0.02 merge tolerance is false,
    # so they stay separate removals but the sliver never becomes a keep.
    assert (4.0, 4.05) not in p.keep
    assert all(e - s >= 0.10 for s, e in p.keep)


# --------------------------------------------------------------------------
# Filler words
# --------------------------------------------------------------------------
def test_english_filler_is_removed_with_padding():
    p = plan(words=[word("um", 1.0, 1.2)], language="en", filler_pad=0.06)

    assert [r.kind for r in p.removed] == ["filler"]
    assert p.removed[0].start == pytest.approx(0.94)
    assert p.removed[0].end == pytest.approx(1.26)
    assert p.removed[0].note == "um"


@pytest.mark.parametrize("token", ["um", "uh", "uhm", "er", "ah", "Um", "uh."])
def test_english_filler_variants_match(token):
    p = plan(words=[word(token, 1.0, 1.2)], language="en")

    assert [r.kind for r in p.removed] == ["filler"]


@pytest.mark.parametrize("token", ["äh", "ähm", "öh", "öhm", "hm", "ÄHM"])
def test_german_filler_variants_match(token):
    p = plan(words=[word(token, 1.0, 1.2)], language="de")

    assert [r.kind for r in p.removed] == ["filler"]


@pytest.mark.parametrize("token", ["umbrella", "under", "the", "error", "ahead"])
def test_real_words_that_start_like_fillers_are_kept(token):
    """The patterns are anchored, so 'umbrella' must survive."""
    p = plan(words=[word(token, 1.0, 1.5)], language="en")

    assert p.removed == []


def test_german_fillers_are_not_cut_when_language_is_english():
    p = plan(words=[word("ähm", 1.0, 1.2)], language="en")

    assert p.removed == []


def test_cut_fillers_false_disables_filler_removal():
    p = plan(words=[word("um", 1.0, 1.2)], cut_fillers=False)

    assert p.removed == []


def test_unknown_language_falls_back_to_english_patterns():
    p = plan(words=[word("um", 1.0, 1.2)], language="fr")

    assert [r.kind for r in p.removed] == ["filler"]


def test_filler_boundaries_snap_to_nearby_fine_silence():
    """Padding is a guess; a real silence boundary within 0.12 s wins."""
    p = plan(
        words=[word("um", 1.0, 1.2)],
        silences_fine=[(0.9, 0.95), (1.3, 1.35)],
        filler_pad=0.06,
    )

    # 0.94 snaps to the 0.95 silence end; 1.26 snaps to the 1.30 silence start.
    assert p.removed[0].start == pytest.approx(0.95)
    assert p.removed[0].end == pytest.approx(1.30)


# --------------------------------------------------------------------------
# Pause trimming
# --------------------------------------------------------------------------
def test_long_narrator_pause_is_trimmed_to_the_configured_keep():
    p = plan(
        silences_fine=[(1.0, 2.0)],
        pause_trim_narrator_above=0.35,
        pause_trim_narrator_keep=0.20,
    )

    assert [r.kind for r in p.removed] == ["pause"]
    removed = p.removed[0]
    assert removed.end - removed.start == pytest.approx(0.80)
    # The kept 0.2 s straddles the middle of the original pause.
    assert (removed.start + removed.end) / 2 == pytest.approx(1.5)
    assert removed.note == "1.00s"


def test_short_narrator_pause_is_left_alone():
    p = plan(silences_fine=[(1.0, 1.3)], pause_trim_narrator_above=0.35)

    assert p.removed == []


def test_pause_exactly_at_the_threshold_is_left_alone():
    """The threshold is exclusive: `dur <= above` is kept."""
    p = plan(silences_fine=[(1.0, 1.5)], pause_trim_narrator_above=0.5)

    assert p.removed == []


def test_protected_pause_uses_the_more_generous_threshold_and_keep():
    """Inside a protected range, pauses are only trimmed above 0.6 s and keep 0.3 s."""
    p = plan(
        silences_coarse=[(1.0, 2.0)],
        protect_ranges=[(0.0, 5.0)],
        pause_trim_protected_above=0.6,
        pause_trim_protected_keep=0.30,
    )

    assert [r.kind for r in p.removed] == ["pause"]
    removed = p.removed[0]
    assert removed.end - removed.start == pytest.approx(0.70)
    assert removed.note == "1.00s (protected)"


def test_coarse_silences_outside_protected_ranges_are_not_pause_trimmed():
    """Coarse silences only drive pause trimming inside protected ranges."""
    p = plan(silences_coarse=[(1.0, 3.0)])

    assert p.removed == []


# --------------------------------------------------------------------------
# Protected ranges
# --------------------------------------------------------------------------
def test_redundancy_fully_inside_a_protected_range_is_skipped():
    p = plan(
        redundancy_ranges=[(2.0, 3.0, "restated")],
        protect_ranges=[(1.0, 5.0)],
    )

    assert p.removed == []
    assert p.keep == [(0.0, 10.0)]


def test_redundancy_only_partially_overlapping_protection_is_still_cut():
    """Protection requires full containment; a straddling range is fair game."""
    p = plan(
        redundancy_ranges=[(4.0, 6.0, "restated")],
        protect_ranges=[(5.0, 8.0)],
    )

    assert [r.kind for r in p.removed] == ["redundancy"]


def test_filler_inside_a_protected_range_is_skipped():
    p = plan(words=[word("um", 2.0, 2.2)], protect_ranges=[(1.0, 5.0)])

    assert p.removed == []


def test_narrator_pause_inside_a_protected_range_is_skipped():
    p = plan(silences_fine=[(2.0, 3.0)], protect_ranges=[(1.0, 5.0)])

    assert p.removed == []


# --------------------------------------------------------------------------
# Merging
# --------------------------------------------------------------------------
def test_overlapping_removals_merge_and_combine_their_kinds():
    p = plan(
        duration=10.0,
        redundancy_ranges=[(1.0, 2.0, "restated")],
        silences_fine=[(1.8, 3.0)],
        pause_trim_narrator_above=0.35,
        pause_trim_narrator_keep=0.20,
    )

    assert len(p.removed) == 1
    merged = p.removed[0]
    assert merged.kind == "redundancy+pause"
    assert merged.start == pytest.approx(1.0)
    # The pause removal ends at 2.4 + (1.2 - 0.2) / 2 and extends the redundancy.
    assert merged.end == pytest.approx(2.9)
    assert len(p.keep) == 2
    assert p.keep[0] == (0.0, 1.0)
    assert p.keep[1][0] == pytest.approx(2.9)
    assert p.keep[1][1] == 10.0


def test_adjacent_removals_within_the_merge_tolerance_are_joined():
    """A gap of <= 0.02 s is not worth keeping as a separate segment."""
    p = plan(redundancy_ranges=[(1.0, 2.0, "a"), (2.01, 3.0, "b")])

    assert len(p.removed) == 1
    assert p.removed[0].end == pytest.approx(3.0)


def test_removals_further_apart_than_the_tolerance_stay_separate():
    p = plan(redundancy_ranges=[(1.0, 2.0, "a"), (2.5, 3.0, "b")])

    assert len(p.removed) == 2
    assert p.keep == [(0.0, 1.0), (2.0, 2.5), (3.0, 10.0)]


def test_a_removal_swallowed_by_a_longer_one_does_not_shorten_it():
    p = plan(redundancy_ranges=[(1.0, 5.0, "long"), (2.0, 3.0, "inner")])

    assert len(p.removed) == 1
    assert p.removed[0].end == pytest.approx(5.0)


def test_merged_kind_is_not_repeated_for_the_same_kind():
    p = plan(redundancy_ranges=[(1.0, 2.0, "a"), (1.5, 3.0, "b")])

    assert p.removed[0].kind == "redundancy"


def test_removals_are_returned_in_chronological_order():
    p = plan(
        redundancy_ranges=[(7.0, 8.0, "c"), (1.0, 2.0, "a"), (4.0, 5.0, "b")],
    )

    starts = [r.start for r in p.removed]
    assert starts == sorted(starts)


# --------------------------------------------------------------------------
# CutPlan serialisation
# --------------------------------------------------------------------------
def test_total_removed_sums_every_removal():
    p = CutPlan(
        source="a.mp4",
        duration=10.0,
        keep=[],
        removed=[Removal("filler", 1.0, 1.5), Removal("pause", 3.0, 4.25)],
    )

    assert p.total_removed() == pytest.approx(1.75)


def test_write_emits_readable_json_with_every_field(tmp_path):
    p = plan(duration=10.0, redundancy_ranges=[(2.0, 4.0, "restated")])
    out = tmp_path / "cut_plan.json"

    p.write(out)
    data = json.loads(out.read_text())

    assert data["source"] == "clip.mp4"
    assert data["duration"] == 10.0
    assert data["keep"] == [[0.0, 2.0], [4.0, 10.0]]
    assert data["removed"] == [
        {"kind": "redundancy", "start": 2.0, "end": 4.0, "note": "restated"}
    ]


def test_plan_accounts_for_the_whole_timeline():
    """kept + removed must equal the source duration (nothing lost or double counted)."""
    p = plan(
        duration=10.0,
        words=[word("um", 6.0, 6.2)],
        silences_fine=[(1.0, 2.0)],
        redundancy_ranges=[(3.0, 4.0, "restated")],
    )

    kept = sum(e - s for s, e in p.keep)
    assert kept + p.total_removed() == pytest.approx(10.0)
