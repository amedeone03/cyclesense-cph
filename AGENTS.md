# CycleSense CPH — Instructions for coding agents

- Follow the updated project proposal under `docs/research_proposal.pdf` and `docs/research_plan.md`.
- Research goal: optimize modeled-route coverage, route-community diversity, and robustness.
- Core 02807 methods: MinHash + LSH, Louvain community detection; outside-course: greedy combinatorial optimization.
- Do not replace the study with unrelated machine-learning prediction tasks.
- Keep real mapped street infrastructure separate from simulated origin–destination demand.
- Counter sites are **eligible graph edges**, not arbitrary node radii.
- Avoid leakage: build/tune route representations and placement on calibration scenarios, evaluate on held-out route scenarios.
- Prioritize reproducible experiments with fixed seeds, stable graph snapshots and meaningful baselines.
- Add focused synthetic tests for every algorithmic component; benchmark accuracy and scaling.
- Keep large data and outputs outside Git; no API credentials, tokens, or personal data in source.
- Update README and docs when assumptions or objective definitions change.
- Do not claim measured real-world cyclist coverage without measured trip ground truth.
