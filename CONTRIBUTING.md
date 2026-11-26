# Contributing to API Sentinel

Start with the [local investigation](docs/local-demo.md) to see the workflow a change should support. The [roadmap](docs/roadmap.md) lists release priorities. Issues labeled **good first issue** include a starting point and an observable result.

## Develop and verify

Use Python 3.11+ for the host scripts, uv 0.13.9 for the locked Python 3.13 application environment, Node 24.22.3 and Docker Compose v2.20+. From the repository root, run `python scripts/check.py` for API linting, types and unit tests plus frontend linting, tests and the production build. Follow the [local reference](docs/local-reference.md) to start a disposable stack. For database changes, run `docker compose run --rm --build record-tests`. Use synthetic fixtures and keep credentials outside version control.

## Submit a change

Create a short kebab-case branch from current main. Keep each PR focused on one behavior. Inspect the staged diff and use an imperative commit message. Review the full branch diff before describing the outcome, compatibility impact, commands run and results. Include a regression test for a corrected defect and document migration or operator steps when applicable.

Use the [security policy](SECURITY.md) for sensitive reports. Community participation follows the [code of conduct](CODE_OF_CONDUCT.md).
