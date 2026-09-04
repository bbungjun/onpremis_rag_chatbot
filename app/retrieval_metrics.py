from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from math import floor, log2
from random import Random
from statistics import fmean


@dataclass(frozen=True, slots=True)
class RetrievalMetricError(ValueError):
    message: str

    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True, slots=True)
class RankingMetrics:
    recall_at_1: float
    recall_at_3: float
    recall_at_5: float
    hit_at_1: bool
    hit_at_3: bool
    hit_at_5: bool
    reciprocal_rank_at_5: float
    ndcg_at_5: float


@dataclass(frozen=True, slots=True)
class BootstrapInterval:
    mean_difference: float
    lower: float
    upper: float
    samples: int
    seed: int


def ranking_metrics(
    gold_parent_ids: Sequence[str], predicted_parent_ids: Sequence[str]
) -> RankingMetrics:
    if not gold_parent_ids:
        raise RetrievalMetricError("gold_parent_ids must not be empty")

    gold = frozenset(gold_parent_ids)
    predicted = _unique(predicted_parent_ids)
    return RankingMetrics(
        recall_at_1=_recall(gold, predicted, 1),
        recall_at_3=_recall(gold, predicted, 3),
        recall_at_5=_recall(gold, predicted, 5),
        hit_at_1=_hit(gold, predicted, 1),
        hit_at_3=_hit(gold, predicted, 3),
        hit_at_5=_hit(gold, predicted, 5),
        reciprocal_rank_at_5=_reciprocal_rank(gold, predicted, 5),
        ndcg_at_5=_ndcg(gold, predicted, 5),
    )


def paired_bootstrap(
    before: Sequence[float],
    after: Sequence[float],
    *,
    samples: int = 10_000,
    seed: int = 20260831,
) -> BootstrapInterval:
    if not before or len(before) != len(after):
        raise RetrievalMetricError("paired values must have the same non-zero length")
    if samples <= 0:
        raise RetrievalMetricError("samples must be greater than zero")

    differences = tuple(
        after_value - before_value for before_value, after_value in zip(before, after, strict=True)
    )
    random = Random(seed)
    sampled_means = sorted(
        fmean(differences[random.randrange(len(differences))] for _ in differences)
        for _ in range(samples)
    )
    return BootstrapInterval(
        mean_difference=fmean(differences),
        lower=_percentile(sampled_means, 0.025),
        upper=_percentile(sampled_means, 0.975),
        samples=samples,
        seed=seed,
    )


def _unique(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def _recall(gold: frozenset[str], predicted: Sequence[str], limit: int) -> float:
    return len(gold.intersection(predicted[:limit])) / len(gold)


def _hit(gold: frozenset[str], predicted: Sequence[str], limit: int) -> bool:
    return bool(gold.intersection(predicted[:limit]))


def _reciprocal_rank(gold: frozenset[str], predicted: Sequence[str], limit: int) -> float:
    for rank, parent_id in enumerate(predicted[:limit], start=1):
        if parent_id in gold:
            return 1 / rank
    return 0.0


def _ndcg(gold: frozenset[str], predicted: Sequence[str], limit: int) -> float:
    dcg = sum(
        1 / log2(rank + 1)
        for rank, parent_id in enumerate(predicted[:limit], start=1)
        if parent_id in gold
    )
    ideal_relevant_count = min(len(gold), limit)
    ideal_dcg = sum(1 / log2(rank + 1) for rank in range(1, ideal_relevant_count + 1))
    return dcg / ideal_dcg


def _percentile(sorted_values: Sequence[float], quantile: float) -> float:
    position = (len(sorted_values) - 1) * quantile
    lower_index = floor(position)
    upper_index = min(lower_index + 1, len(sorted_values) - 1)
    fraction = position - lower_index
    return (
        sorted_values[lower_index]
        + (sorted_values[upper_index] - sorted_values[lower_index]) * fraction
    )
