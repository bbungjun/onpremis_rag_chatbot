# Implementation sequence

1. Write failing tests for fixed context, A/B/C intervention, paired denominators and checkpoints.
2. Implement evaluation-only preparation and durable sequential Ollama generation/judge phases.
3. Freeze 98 inputs; pilot representative arms, inspect output and memory, then finish all arms.
4. Run separate EXAONE phase and inspect disagreements and incomplete/truncated cases.
5. Run required Docker regressions, record measured results and limitations in portfolio.
6. Review file diffs, commit scoped files and publish a reviewable PR; do not merge automatically.
