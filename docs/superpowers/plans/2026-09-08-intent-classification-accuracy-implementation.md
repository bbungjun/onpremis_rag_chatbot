# Intent classification accuracy implementation plan

1. Add failing tests for gold parsing, validation, confusion counts, type-level accuracy, and error
   listing.
2. Implement the gold-label loader and accuracy report alongside the existing coverage report.
3. Add 98 independently reviewed labels in `datasets/eval/intent_gold.jsonl`.
4. Add a dataset contract test proving exact ID coverage and valid labels.
5. Run targeted tests and the evaluation CLI; review every emitted misclassification.
6. Correct annotation mistakes only when the written labeling policy supports the correction; do
   not tune labels to improve the classifier score.
7. Run the full required Docker verification and record the exact baseline, confusion matrix,
   limitations, dataset hash, and runtime conditions in `docs/portfolio/`.
