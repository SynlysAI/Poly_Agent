---
name: polyagent-attribution
description: Use when modifying PolyAgent system modules, algorithm pages, vertical prediction models, model upload flows, tool service entries, or pages that expose external frameworks, institutions, models, methods, or dependencies. Ensures visible source, citation, developer, and institution Logo attribution.
---

# PolyAgent Attribution

## When Working On PolyAgent UI Or Algorithms

Always check whether the page or API exposes a framework, method, model, institution, dependency, or uploaded algorithm. If it does, attribution must be visible in the product UI and backed by the unified attribution schema.

## Rules

- Use structured attribution data, not page-local hardcoded prose.
- System pages should use `AttributionBanner` near the page title or main tool card, with short public-facing labels such as `模型服务来自`, `方法来源`, `参考框架`, `工具支持`, or `算法开发者`.
- Algorithm cards/details/results should show developer attribution with `AttributionBadges` or the attribution banner.
- If an institution is known and a Logo is authorized or submitted with the algorithm package, show the Logo plus a short source sentence.
- If Logo authorization is unclear, do not create or download a fake Logo; show a text source badge instead.
- Public UI attribution must stay concise and external-facing. Do not show internal implementation terms such as `ProblemSpec`, `ManualWorkflow`, `AutoResearch`, `artifact`, `worker`, `audit`, `契约`, or upload-package lifecycle wording in source banners.
- Public attribution banners and source cards must not open detail drawers, external pages, or new tabs. Keep full links and citations in README and the source matrix.
- Do not show a `PolyAgent`/`Poly Agent` source card in public-facing source banners; the product UI should emphasize external frameworks, institutions, dependencies, and model developers.
- Logo and text source cards must remain readable on desktop and mobile. Use full organization names, allow wrapping, and avoid tiny initials or ellipsized labels.
- Never imply copied code or ownership. For ChemOS 2.0, state it is an orchestration/framework reference. For ALchemist, state it is the active-learning/Bayesian-optimization method source.
- New uploaded algorithms should capture `developer`, `developer_organization`, `developer_contact`, `source_url`, `citation`, and optional Logo fields.

## Data Locations

- Backend schema: `backend/app/schemas/attribution.py`
- Module registry: `backend/app/services/attribution_service.py`
- Algorithm schema: `backend/app/schemas/research_engine.py`
- Frontend components: `frontend/src/components/attribution/`
- Source matrix: `doc/polyagent-attribution-source-matrix.md`
