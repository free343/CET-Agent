# CET-Agent Repository Guide

Last updated: 2026-08-22 (Asia/Shanghai)

This file is the authoritative, continuously maintained project-state document for agents working in `D:\work\english`. Read it completely before modifying code. Update it whenever architecture, completed behavior, verification evidence, known gaps, or development constraints change.

## 1. Project mission

CET-Agent is a local-first PySide6 desktop learning agent for Chinese CET-4/CET-6 students. It records review behavior, schedules deterministic spaced repetition, discovers personal vocabulary-confusion patterns, proactively reminds the user, and uses a small LLM only to explain algorithmically discovered problems.

The central rule is:

> Algorithms discover problems. LLMs explain problems.

The LLM must never control scheduling, queue ordering, database queries, statistics, edit distance, relation scoring, graph construction, clustering, or reminder timing.

## 2. Required architecture

```text
PySide6 UI
    ↓
Application Services
    ↓
Deterministic Domain Algorithms
    ↓
SQLite / LLM / Embedding / Notification Adapters
```

Layer responsibilities:

- `app/ui/`: rendering, input, navigation, and asynchronous presentation only. It must not query SQLAlchemy directly or call a concrete model adapter.
- `app/services/`: application use cases, transaction boundaries, orchestration, structured data extraction, and safe model fallbacks.
- `app/domain/`: deterministic, side-effect-free learning algorithms wherever practical.
- `app/db/`: SQLAlchemy models, repositories, UTC persistence, seed data, and database lifecycle.
- `app/ai/`: replaceable LLM/Embedding interfaces, concrete providers, centralized prompts, and Pydantic output schemas.
- `app/infrastructure/`: desktop notification and other operating-system adapters.
- `scripts/`: repeatable demo or validation utilities; scripts must be safe to run more than once when documented as idempotent.
- `tests/`: algorithm, service, provider-cache, reminder, and UI-regression tests.

Do not add a framework or abstraction unless the current boundary actually needs replaceability. The intended replaceable seams are LLM Provider, Embedding Provider, Repository/data evolution, and operating-system notification adapters.

## 3. Current repository facts

- Workspace: `D:\work\english`.
- The workspace is a local Git repository on branch `main`, initialized with a baseline commit on 2026-08-22. No remote is configured; inspect files before editing and preserve unrelated work.
- Python target: 3.11+.
- Runtime stack: PySide6, SQLite, SQLAlchemy 2.x, py-fsrs 6.3.2, Pydantic, httpx, python-dotenv.
- Test runner: pytest.
- Main entry point: `main.py`.
- Runtime database: `data/cet_agent.db` (ignored by source control rules).
- Ollama model storage observed on this machine: `D:\model`.
- Vocabulary: 13 curated demo words in `data/sample_words.csv` plus 4,598 validated open-data words in `data/cet_vocabulary_open.csv` (3,320 CET4 and 1,278 CET6); the two files do not overlap.
- Logs: `logs/cet-agent.log`, rotating and never intended to contain secrets.
- Detailed Phase 1–9 audit snapshot: `docs/handoff/CET_AGENT_HANDOFF.md`. It is historical context; this `AGENTS.md` is authoritative when the two differ.

Local Ollama:

- Executable: `C:\Users\Admin\AppData\Local\Programs\Ollama\ollama.exe`
- API: `http://127.0.0.1:11434`
- Version observed this session: 0.32.13
- Chat model: `qwen2.5:3b`, ID `357c53fb659c`, size 1.9 GB.
- Embedding model: `nomic-embed-text:latest`, ID `0a109f422b47`, size 274 MB.
- Current state: both manifests are installed and both models pass the repository's live Provider/Service validation.
- Operational cleanup: the two agent-created temporary Range files used to complete the throttled download were deleted after both model manifests were verified. No download partials remain.

## 4. Implemented architecture and features

### Bootstrap and persistence

- `app/bootstrap.py` configures logging, upgrades the database schema, validates and idempotently imports both bundled vocabulary files, and creates missing LearningState rows.
- `app/db/migrations.py` owns the explicit sequential schema registry, currently version 2. A single-row `schema_version` table tracks the current version; upgrades take a SQLite write reservation, update schema plus version in one transaction, adopt pre-versioning MVP databases without data loss, and reject databases newer than the application.
- `app/config.py` loads `.env`, resolves relative SQLite paths from the project root, and owns all model, graph, reminder, and logging configuration.
- Unsafe graph/reminder configuration is rejected at startup: thresholds are bounded, candidate count stays within 1–100, relation weights must be finite/non-negative and sum to 1, and reminder windows/cooldowns must be valid.
- `app/db/models.py` defines Word, LearningState, ReviewLog, ConfusionEdge, AIAnalysis, EmbeddingCache, and ReminderRuntimeState.
- UTC-aware values are converted through a custom SQLAlchemy type so stored SQLite timestamps are consistent and loaded values regain UTC awareness.
- SQLite review writes acquire `BEGIN IMMEDIATE` before reading LearningState because SQLite ignores `SELECT ... FOR UPDATE`; competing application windows therefore cannot both overwrite the same prior state.
- `app/db/seed.py` validates an entire CSV before mutation, including its required columns, unique single-word English headwords, CET4/CET6 levels, nonempty meanings, and bounded numeric fields. Word seeding is idempotent and supports a per-row initial release delay.
- `scripts/build_open_vocabulary.py` reproducibly builds the redistributable CET artifact from hash-pinned ECDICT and FreeDict sources. Only words with an ECDICT CET tag/phonetic/Chinese meaning and an independent FreeDict bilingual/pronunciation entry survive. The generated CSV hash, source hashes, versions, licenses, transformation, and counts are committed alongside the artifact.

### Review and learning loop

- `app/domain/fsrs_scheduler.py` is a deterministic adapter over the official MIT-licensed `py-fsrs` 6.3.2 implementation of FSRS-6. It uses 90% desired retention, one ten-minute learning step, one ten-minute relearning step, a 36,500-day maximum, and no interval fuzzing.
- LearningState persists FSRS Learning/Review/Relearning state and the active step. Schema migration 2 maps untouched legacy cards to Learning step 0 and reviewed legacy cards to Review without discarding their difficulty, stability, or history.
- `app/services/review_service.py` deterministically selects due words and atomically updates LearningState plus ReviewLog.
- `STUDY_LEVEL` is validated as CET4 or CET6. Review queues, due counts, reminder inputs, and every dashboard statistic are restricted to the selected level.
- The open wordbank stages each level independently at no more than 20 newly due words per day; the 13 curated confusion examples remain immediately available and override any open-data duplicate.
- Review timestamps must advance monotonically for each word, preventing delayed or duplicate submissions from moving a learning state backwards.
- Due ordering prioritizes longest overdue, then higher lapse count, then higher error count.
- Review batches default to 30; completing one batch loads another when more words are already due.
- `app/services/learning_service.py` derives dashboard metrics from ReviewLog rather than trusting only aggregate LearningState values.
- Dashboard statistics ignore future-dated ReviewLog rows so clock/import anomalies cannot inflate completed counts, accuracy, streaks, or wrong-word rankings.
- `app/ui/review_page.py` supports reveal plus Again/Hard/Good/Easy with Space/1/2/3/4 shortcuts.
- Starting a review session from sidebar navigation dismisses any visible reminder banner, preventing stale counts from remaining above an active review.
- `app/ui/dashboard_page.py` shows due count, completed today, seven-day accuracy, streak, and frequent wrong words.

### Confusion analysis

- `app/domain/similarity.py` implements Levenshtein distance, bounded spelling similarity, clipped 0–1 cosine similarity, one-to-one co-error matching, and temporal exponential decay.
- `app/services/analysis_service.py` selects words with at least two errors in the configured recent window, limits candidates to 100, obtains optional embeddings, scores candidate pairs, replaces graph edges, and exposes clusters.
- The default relation formula is `0.30 semantic + 0.25 spelling + 0.30 co-error + 0.15 temporal`, threshold `0.65`.
- Candidate selection and cluster error counts use the same 30-day window.
- `app/domain/clustering.py` uses connected components; clusters above eight words pass only their highest-weight core words to the LLM.
- The Analysis list defines an explicit readable selected-item style; selection no longer renders dark/white text invisibly against the platform theme.
- `scripts/create_demo_data.py` idempotently creates correlated errors for three groups. Latest deterministic demo result: 7 candidates, 5 edges, 3 clusters (`adapt/adopt/adept`, `economic/economical`, `complement/compliment`).
- `scripts/benchmark_confusion_graph.py` creates an ephemeral worst-case dense graph with 100 candidates and 4,950 persisted edges, asserts the exact result, runs three timed rebuilds, and fails if the median exceeds a configurable five-second budget. It never touches the runtime database.

### LLM and Embedding integration

- `app/ai/llm_provider.py` is the LLM abstraction.
- `app/ai/ollama_provider.py` uses Ollama `/api/chat`.
- `app/ai/openai_compatible_provider.py` supports OpenAI-compatible chat and normalizes `/v1` without duplication.
- `app/ai/embedding_provider.py` uses Ollama `/api/embed` behind an independent Embedding Provider and SQLite cache.
- Ollama chat and embedding calls set `trust_env=False`, preventing Windows/HTTP proxy settings from capturing localhost traffic.
- The Embedding adapter allows a 60-second cold start; the observed first load was 20.159 seconds, so the old 20-second limit was too brittle.
- Chat and embeddings have separate provider, base URL, and model settings.
- Embedding cache identity includes provider type, base URL, and model.
- Invalid or non-finite cached vectors are deleted and regenerated. Model calls occur outside SQLite transactions so an Embedding cold start cannot hold a database transaction open.
- Embedding cache persistence uses SQLite conflict-update semantics, so simultaneous workers converge on one valid row instead of raising a unique-key error.
- `app/ai/prompts.py` is the only location for model prompts.
- `app/ai/schemas.py` strictly validates structured cluster analysis with Pydantic and forbids extra fields.
- `app/services/ai_service.py` retries invalid structured JSON once, then returns a safe degraded result; normal chat also degrades without crashing.
- Local and advanced chat Providers have independent provider/model/base-URL/API-key settings. `create_advanced_llm_provider` returns `None` when disabled and constructs an Ollama or OpenAI-compatible adapter when explicitly configured; the UI enables the advanced choice only in the latter case.
- API-key fields are excluded from the Settings representation. Keys remain local to `.env` and are never rendered by the settings page or logged.
- Structured cluster output must explain every algorithm-selected input word exactly once; schema-valid output containing missing, duplicate, or unrelated words is rejected and retried.
- AI cache identity includes prompt version, provider type, model, base URL, cluster words, relation type, and major statistics.
- If another window stores the same AI analysis after the initial cache read, the losing writer reloads the winning validated row and returns it as a cache hit.
- `app/domain/query_routing.py` owns an injectable deterministic policy that normalizes input and returns an explainable `LOCAL`, `CONFIRM_ADVANCED`, or `REFUSE` decision with bounded confidence. It distinguishes language questions about an otherwise off-topic noun from actual real-time/professional requests, routes long or complex language tasks through explicit user choice, and never asks an LLM to select a model.
- The local assistant rejects empty, general-chat, real-time, and professional out-of-scope requests without calling a model. The Chat UI consumes the structured route instead of comparing a magic confidence threshold.

### Reminder and desktop lifecycle

- `app/domain/reminder_policy.py` is deterministic and independently tested.
- It suppresses reminders with no due words, during a review, during cooldown/snooze, before 08:00, after 23:00, or after the day's work is complete.
- `app/services/reminder_service.py` persists notification, snooze, and completion state across restarts.
- ReminderService accepts an injectable clock so constructor state and explicit evaluations use one deterministic time source; this prevents tests and state transitions from drifting across real midnight.
- A newly due word on the same day clears a stale completed state.
- A far-future persisted notification timestamp cannot suppress reminders indefinitely after a system-clock correction; only a small rollback within the configured cooldown remains suppressed.
- `app/infrastructure/notification_adapter.py` provides a Qt system-tray notification.
- `app/ui/widgets/reminder_banner.py` contains the actionable “start review” and “snooze 30 minutes” buttons.
- `app/ui/main_window.py` waits for active AI QThreads before destroying the window, preventing shutdown crashes.

### Resilience and diagnostics

- Model unavailable, embedding unavailable, invalid JSON, empty data, no clusters, and SQLite busy conditions have recoverable paths.
- Failed review-queue reloads clear and disable the stale card; dashboard and analysis refresh failures display safe state instead of leaking an exception through a Qt callback.
- While chat is waiting for a low-confidence routing choice, its pending question and input controls are locked so a second send cannot silently replace the first question.
- Model/network work runs in `AsyncWorker` QThreads, not on the UI thread.
- Detailed failures go to logs; user-facing messages remain concise.
- pytest cacheprovider is disabled by `pytest.ini` to avoid cache-directory write failures in restricted environments.
- `scripts/validate_local_ai.py` is the repeatable P0 integration check for live chat, cached embeddings, semantic graph rebuild, structured cluster output, and AI cache reuse. Its latest cold and warm runs both exited successfully.

### Delivery engineering

- `requirements.txt` and `requirements-dev.txt` declare compatible direct dependencies; the corresponding `.lock` files pin the complete tested runtime and development dependency trees. Regenerate them with pip-tools 7.6.1 after changing a direct dependency.
- `pyproject.toml` centralizes the Python 3.11 Ruff and Mypy baselines. The entire Python tree is Ruff-formatted; CI rejects lint, format, or application/script type-check drift.
- `.github/workflows/ci.yml` runs on Windows for Python 3.11 and 3.13 with read-only repository permission. It installs the development lock, runs `pip check`, Ruff lint/format, Mypy, all tests, and the offscreen startup smoke. No Git remote is configured yet, so the workflow is locally validated but has not had a hosted run.

## 5. Verification ledger

Update this section after every material change. Never report a feature as verified based only on code inspection.

| Verification | Latest result | Evidence date |
|---|---:|---:|
| Full pytest suite | 105 passed in 2.13s | 2026-08-22 |
| Ruff static check | all checks passed | 2026-08-22 |
| Ruff format gate | 76 files already formatted | 2026-08-22 |
| Mypy application/scripts check | exit code 0; 53 source files | 2026-08-22 |
| Deterministic chat routing | 15 new/updated routing and integration cases cover local vocabulary/grammar, Unicode normalization, advanced confirmation, empty/general/off-topic refusal, scope override, and zero-call refusal | 2026-08-22 |
| Advanced Provider bootstrap | disabled/default, independent OpenAI-compatible construction, invalid/incomplete configuration rejection, explicit advanced dispatch, and API-key repr redaction passed | 2026-08-22 |
| Live advanced-provider dispatch | explicit advanced choice returned a non-degraded 283-character response from independent `qwen2.5:3b` while the local Provider pointed to an unreachable endpoint | 2026-08-22 |
| 100-candidate graph performance | dense 4,950-edge rebuild runs: 0.208s, 0.223s, 0.208s; median 0.208s; exact one-cluster invariant passed | 2026-08-22 |
| Locked dependency install | clean Python 3.13 virtual environment installed `requirements-dev.lock`; `pip check` passed; Python 3.11/win_amd64 wheel-resolution dry run passed | 2026-08-22 |
| GitHub Actions workflow | Windows Python 3.11/3.13 matrix defined with current official v7 checkout/setup actions; local-equivalent full gate passed; hosted run pending remote configuration | 2026-08-22 |
| Schema migration matrix | 5 focused tests passed: fresh, pre-version adoption, v1→v2 FSRS state mapping, idempotency/newer-version guard, transactional rollback | 2026-08-22 |
| Official FSRS-6 reference vectors | initial Again/Hard/Good/Easy plus five-review sequence passed against py-fsrs 6.3.2 | 2026-08-22 |
| Deterministic randomized algorithm invariants | 6,000 checks passed | 2026-08-22 |
| Concurrent review/AI/Embedding focused regression | 15 tests passed in five consecutive runs; no lost update or cache exception | 2026-08-22 |
| Open vocabulary artifact | deterministic rebuild hash matched `1afc9925…9a16f`; 4,598 unique rows, 3,320 CET4 + 1,278 CET6, Chinese meaning and phonetic coverage 100%, no curated overlap | 2026-08-22 |
| Bundled vocabulary import | 4,611 total words/states; second import inserted 0; invalid/duplicate/out-of-range rows rejected before mutation | 2026-08-22 |
| Offscreen startup smoke | exit code 0; schema version 2; inserted 4,598 new open-data words into the existing runtime database | 2026-08-22 |
| SQLite integrity and foreign keys | 4,611 runtime words (3,329 CET4 + 1,282 CET6); `integrity_check=ok`; no foreign-key violations | 2026-08-22 |
| Demo graph | 7 candidates, 5 edges, 3 clusters | 2026-08-22 |
| Ollama chat through project provider | cold 29.490s; warm 1.246s; non-degraded Chinese response | 2026-08-22 |
| Ollama embedding through cached provider | 2 vectors, dimension 768; cold 20.159s; cache rows 0→2→2 | 2026-08-22 |
| Semantic graph rebuild | 7 candidates, 5 edges, 3 clusters; `embedding_available=true` | 2026-08-22 |
| Structured cluster JSON and AI cache hit | first live result `cached=false`; second `cached=true`; Pydantic passed | 2026-08-22 |
| Latest warm full local-AI validation | exit code 0; chat 2.647s; embedding cache rows remained 7→7→7 | 2026-08-22 |
| Visible Windows desktop flow | navigation, reminder banner, Space reveal, `3=Good`, next-card load, cluster selection/readability, cached AI display, settings, close/restart passed; native toast/tray timing remains | 2026-08-22 |

Baseline commands:

```powershell
Set-Location 'D:\work\english'
python -m pip install -r requirements-dev.lock
python -m pip check
python -m pytest -q
python -m ruff check app scripts tests main.py
python -m ruff format --check app scripts tests main.py
python -m mypy
$env:QT_QPA_PLATFORM='offscreen'
python main.py --smoke-test
python scripts/create_demo_data.py
python scripts/benchmark_confusion_graph.py
python scripts/validate_local_ai.py
& 'C:\Users\Admin\AppData\Local\Programs\Ollama\ollama.exe' list
python main.py
```

## 6. Known incomplete work

### P2: product completeness

- Native OS notifications do not contain action buttons; actions exist only in the in-app banner.
- Chat is intentionally single-turn and has no bounded conversation persistence.
- Complete the remaining native Windows validation for tray/toast behavior, real 30-minute snooze timing, and closing during an uncached active AI request.

### P3: delivery engineering

- No release build or Windows installer.
- The CI workflow has no hosted run evidence until a Git remote is configured and the branch is pushed.
- No full packaging test for writable data/log locations after installation.

## 7. Key design decisions

1. Algorithm first: structured deterministic evidence is produced before any LLM call.
2. Provider separation: LLM and Embedding endpoints are independently configurable because real deployments commonly use different servers/models.
3. Cache namespacing: endpoint identity is part of cache identity so switching providers cannot silently reuse stale model output.
4. Window consistency: candidate selection and displayed cluster error counts refer to the same configured recent period.
5. Negative cosine policy: negative cosine similarity maps to 0 rather than being shifted upward.
6. Bounded graph cost: only recent repeat-error candidates are compared, capped at 100.
7. Graceful degradation: semantic score may become 0 if embedding is offline; deterministic review remains available if all AI services are offline.
8. Structured LLM output: cluster analysis is schema-constrained, validated locally, retried once, and safely degraded.
9. Reminder persistence: cooldown, snooze, and completion survive restart; completion is invalidated when new work becomes due.
10. Deferred close: the main window does not destroy running QThreads.
11. Explicit schema evolution: migration 1 uses SQLAlchemy metadata to create or adopt the original MVP schema; every later schema change must add the next consecutive migration. Structure changes and the stored version commit together, and an older app must reject a newer database.
12. Direct Ollama transport: localhost model calls ignore OS/environment proxies, while the separately configured OpenAI-compatible provider retains normal proxy behavior.
13. Cold-start tolerance: local Embedding uses a 60-second timeout because measured first load slightly exceeded 20 seconds.
14. Injectable reminder clock: time-dependent state coordination accepts a clock dependency; tests must not depend on the wall-clock date.
15. Conservative vocabulary licensing: generated data is distributed under CC BY-SA 3.0, with ECDICT MIT and FreeDict/WikDict/Wiktionary/DBnary attribution, exact version/hash provenance, and an explicit transformation record.
16. Dual-source vocabulary gate: ECDICT supplies display fields and CET metadata, while FreeDict independently confirms an open bilingual entry and pronunciation. A source mismatch removes the row instead of guessing.
17. Bounded initial workload: new open-data words are frequency-sorted and released independently per selected CET level at 20 per day. Level selection is a deterministic query filter, not an LLM decision.
18. Reproducible quality gate: direct dependency ranges remain human-maintainable while pip-tools lock files pin actual installs. Windows Python 3.11 and 3.13 are the CI compatibility bounds; lint, formatting, type checks, tests, dependency integrity, and an offscreen startup must all pass.
19. Explainable model routing: a pure domain policy combines normalized learning-intent, precise out-of-scope phrases, text size, and task complexity into a structured route. Scope refusal runs before complexity escalation, explicit language-learning context can override an ambiguous noun, and the UI never infers a route from a magic numeric threshold.
20. Explicit advanced-model opt-in: advanced chat is a separately configured Provider, disabled by default, and invoked only after the deterministic policy asks and the user chooses it. Its credentials and endpoint identity never replace or leak through the local Provider configuration.
21. Worst-case graph budget: scale validation uses identical deterministic embeddings and synchronized errors so all 4,950 possible edges survive, covering both O(n²) scoring and maximum SQLite persistence cost. The repeatable script uses an ephemeral database and a conservative five-second median guard.
15. Fail-fast configuration: graph and reminder settings are validated before use; invalid bounds, non-finite weights, unsafe candidate limits, and invalid reminder windows are not silently accepted.
16. Monotonic review history: a review cannot be committed at or before that word's previous review timestamp.
17. Cache self-repair: malformed Embedding cache rows are discarded and regenerated, and network/model waits never occur inside an open cache transaction.
18. Evidence alignment: Pydantic shape validation is necessary but not sufficient; structured AI explanations must also match the exact algorithm-selected word multiset.
19. Current-time statistics: future-dated events are excluded from dashboard calculations rather than being trusted as completed learning behavior.
20. Review-session ownership: entering an active review dismisses the in-app reminder immediately; reminder content must not remain visible with a stale due count while the user is reviewing.
21. SQLite write serialization: state-dependent review writes reserve the SQLite writer before reading; `with_for_update()` alone is not treated as protection on SQLite.
22. Concurrent cache convergence: Embedding uses database upsert and AI analysis resolves a unique-key race by returning the already committed, locally revalidated winner.
23. Official deterministic FSRS: scheduling delegates to pinned `py-fsrs` 6.3.2, with fuzzing disabled and reference-vector tests. The adapter keeps the application's stable Rating/result interface while schema v2 persists the library's card phase and step.

## 8. Development constraints

- Preserve the four-layer boundary and existing useful code.
- Do not introduce Electron, React, Vue, PostgreSQL, Redis, Docker microservices, Kubernetes, Celery, message queues, AutoGen, CrewAI, or a complex multi-agent framework for this MVP.
- Do not add login, social features, rankings, cloud sync, essays, listening, reading, OCR, speech recognition, or gamification unless the user explicitly expands scope.
- Do not let the LLM read the whole database or calculate statistics.
- Keep all prompts in `app/ai/prompts.py`.
- Keep secrets only in local `.env`; never put them in code, tests, logs, README, or this file.
- Use type hints, small single-purpose functions, PEP 8 naming, dataclasses/Pydantic where appropriate, and comments only where formulas or rationale need explanation.
- Aim to keep Python modules below roughly 300–400 lines; split responsibilities before a file becomes oversized.
- UI operations that can block must run off the GUI thread.
- Database updates that belong to one user action must share a transaction.
- New deterministic behavior requires deterministic tests.
- Prefer the smallest reliable implementation that fits the existing architecture.

## 9. Required agent workflow

For every implementation milestone:

1. Read this file, then inspect the related code and tests before editing.
2. Check for existing behavior and avoid duplicate implementations.
3. State the intended boundary and smallest coherent change.
4. Implement with small patches and preserve unrelated workspace changes.
5. Run focused tests, then the full suite when the milestone is complete.
6. Run offscreen smoke for startup/UI lifecycle changes.
7. Record real verification evidence in section 5.
8. Update sections 4–7 whenever behavior, architecture, decisions, or backlog changes.
9. Do not leave a completed task described as pending, and do not claim an unexecuted check passed.

When context is compacted or work is interrupted, this file—not conversational memory—must be enough to reconstruct the active project state and next safe action.
