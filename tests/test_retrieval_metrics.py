import math

import pytest

from app.retrieval_metrics import paired_bootstrap, ranking_metrics


def test_ranking_metrics_scores_first_relevant_parent_when_single_gold():
    # Given
    gold = ("jo-39",)
    predicted = ("jo-8", "jo-39", "jo-2", "jo-3", "jo-4")

    # When
    metrics = ranking_metrics(gold, predicted)

    # Then
    assert metrics.recall_at_1 == 0.0
    assert metrics.recall_at_3 == 1.0
    assert metrics.recall_at_5 == 1.0
    assert metrics.hit_at_1 is False
    assert metrics.hit_at_3 is True
    assert metrics.hit_at_5 is True
    assert metrics.reciprocal_rank_at_5 == 0.5
    assert metrics.ndcg_at_5 == pytest.approx(1 / math.log2(3))


def test_ranking_metrics_gives_partial_recall_when_multiple_gold_parents_exist():
    # Given
    gold = ("jo-7", "jo-13")
    predicted = ("jo-13", "jo-99", "jo-7", "jo-4", "jo-8")

    # When
    metrics = ranking_metrics(gold, predicted)

    # Then
    assert metrics.recall_at_1 == 0.5
    assert metrics.recall_at_3 == 1.0
    assert metrics.recall_at_5 == 1.0
    assert metrics.reciprocal_rank_at_5 == 1.0
    expected_dcg = 1 + 1 / math.log2(4)
    expected_idcg = 1 + 1 / math.log2(3)
    assert metrics.ndcg_at_5 == pytest.approx(expected_dcg / expected_idcg)


def test_ranking_metrics_rejects_empty_gold_parent_ids():
    # Given
    gold: tuple[str, ...] = ()

    # When
    with pytest.raises(ValueError) as error:
        ranking_metrics(gold, ("jo-1",))

    # Then
    assert "gold_parent_ids" in str(error.value)


def test_paired_bootstrap_is_deterministic_for_a_fixed_seed():
    # Given
    before = (0.0, 0.0, 1.0, 1.0)
    after = (1.0, 1.0, 1.0, 1.0)

    # When
    first = paired_bootstrap(before, after, samples=2_000, seed=17)
    second = paired_bootstrap(before, after, samples=2_000, seed=17)

    # Then
    assert first == second
    assert first.mean_difference == 0.5
    assert first.lower <= first.mean_difference <= first.upper


def test_paired_bootstrap_rejects_unpaired_values():
    # Given
    before = (0.0,)
    after = (0.0, 1.0)

    # When
    with pytest.raises(ValueError) as error:
        paired_bootstrap(before, after, samples=10, seed=1)

    # Then
    assert "same non-zero length" in str(error.value)
