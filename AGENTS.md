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
- Runtime stack: PySide6, SQLite, SQLAlchemy 2.x, py-fsrs 6.3.2, Pydantic, httpx, python-dotenv, and Windows-Toasts 1.3.1/WinRT 3.2.1 on Windows.
- Test runner: pytest.
- Main entry point: `main.py`.
- Source-mode runtime database: `data/cet_agent.db` (ignored by source control rules). Frozen Windows builds use `%LOCALAPPDATA%\CET-Agent\data\cet_agent.db`; logs and the local `.env`/template use the same writable application root.
- Ollama model storage observed on this machine: `D:\model`.
- Vocabulary: 13 curated demo words in `data/sample_words.csv` plus 4,598 validated open-data words in `data/cet_vocabulary_open.csv` (3,320 CET4 and 1,278 CET6); the two files do not overlap.
- Vocabulary/CI cleanup: downloaded ECDICT and FreeDict source archives, the deterministic rebuild copy, and the clean lock-validation virtual environment were removed from the system temp directory after verification. They are reproducible from committed URLs, hashes, lock files, and scripts; no agent-created vocabulary download partials remain.
- Logs: `logs/cet-agent.log`, rotating and never intended to contain secrets.
- Detailed Phase 1–9 audit snapshot: `docs/handoff/CET_AGENT_HANDOFF.md`. It is historical context; this `AGENTS.md` is authoritative when the two differ.
- Windows installer compiler: Inno Setup 6.7.3 at `C:\Users\Admin\AppData\Local\Programs\Inno Setup 6\ISCC.exe`; its downloaded installer had a valid Pyrsys B.V. Authenticode signature. The compiler remains installed for repeatable local builds, while its downloaded setup cache and all installer-validation runtimes were deleted.

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

- `app/bootstrap.py` configures logging, upgrades the database schema, validates and idempotently imports both bundled vocabulary files, creates missing LearningState rows, and activates the selected study level inside one serialized startup transaction. If any initialization step fails, it disposes the newly created Database/Engine before propagating the failure.
- `app/db/migrations.py` owns the explicit sequential schema registry, currently version 4. A single-row `schema_version` table tracks the current version; upgrades take a SQLite write reservation, update schema plus version in one transaction, adopt pre-versioning MVP databases without data loss, and reject databases newer than the application. Schema v3 adds persistent per-level activation state; schema v4 adds per-instance active-review leases.
- `app/config.py` loads the runtime `.env`, resolves relative SQLite paths from the writable runtime root, and owns all model, graph, reminder, and logging configuration.
- `app/paths.py` separates read-only bundled resources from writable runtime state. Source execution keeps both at the repository root; a frozen executable reads vocabulary/config templates from `_MEIPASS` and writes database/log/config state under the user's local application-data directory.
- Malformed environment values and unsafe model/graph/reminder configuration are rejected at startup: model endpoints must be absolute HTTP(S) URLs, thresholds are bounded, candidate count stays within 1–100, relation weights must be finite/non-negative and sum to 1, and reminder windows/cooldowns must be valid.
- `app/db/models.py` defines Word, LearningState, ReviewLog, ConfusionEdge, AIAnalysis, EmbeddingCache, StudyLevelActivation, ReminderRuntimeState, and ReminderReviewLease.
- UTC-aware values are converted through a custom SQLAlchemy type so stored SQLite timestamps are consistent and loaded values regain UTC awareness.
- SQLite review writes acquire `BEGIN IMMEDIATE` before reading LearningState because SQLite ignores `SELECT ... FOR UPDATE`; competing application windows therefore cannot both overwrite the same prior state.
- SQLite connections install a 15-second busy timeout and perform a bounded locked/busy retry while first negotiating WAL mode, so simultaneous first launches can converge on one fresh database instead of failing before the serialized migration transaction begins.
- `app/db/seed.py` validates an entire CSV before mutation, including its required columns, unique single-word English headwords, CET4/CET6 levels, nonempty meanings, and bounded numeric fields. Word seeding is idempotent, supports a per-row initial release delay, and applies corrected bundled metadata to existing words without replacing their LearningState or review history.
- `app/db/study_level_activation.py` persistently activates each selected CET level once. A never-used level rebases only untouched open-vocabulary cards from its activation time; curated words, reviewed cards, FSRS state, and ReviewLog history are never moved. Existing databases with open-word review history adopt the earliest such review as activation without rescheduling.
- `scripts/build_open_vocabulary.py` reproducibly builds the redistributable CET artifact from hash-pinned ECDICT and FreeDict sources. Only words with an ECDICT CET tag/phonetic/Chinese meaning and an independent FreeDict bilingual/pronunciation entry survive. The generated CSV hash, source hashes, versions, licenses, transformation, and counts are committed alongside the artifact.

### Review and learning loop

- `app/domain/fsrs_scheduler.py` is a deterministic adapter over the official MIT-licensed `py-fsrs` 6.3.2 implementation of FSRS-6. It uses 90% desired retention, one ten-minute learning step, one ten-minute relearning step, a 36,500-day maximum, and no interval fuzzing.
- LearningState persists FSRS Learning/Review/Relearning state and the active step. Schema migration 2 maps untouched legacy cards to Learning step 0 and reviewed legacy cards to Review without discarding their difficulty, stability, or history.
- `app/services/review_service.py` deterministically selects due words and atomically updates LearningState plus ReviewLog.
- `STUDY_LEVEL` is validated as CET4 or CET6. Review queues, due counts, reminder inputs, and every dashboard statistic are restricted to the selected level.
- The open wordbank stages each level independently from that level's first activation at no more than 20 newly due words per day; the 13 curated confusion examples remain immediately available and override any open-data duplicate.
- Review timestamps must advance monotonically for each word, preventing delayed or duplicate submissions from moving a learning state backwards.
- Due ordering prioritizes longest overdue, then higher lapse count, then higher error count.
- Review batches default to 30; completing one batch loads another when more words are already due.
- `app/services/learning_service.py` derives dashboard metrics from ReviewLog rather than trusting only aggregate LearningState values.
- Dashboard statistics ignore future-dated ReviewLog rows so clock/import anomalies cannot inflate completed counts, accuracy, streaks, or wrong-word rankings.
- `app/ui/review_page.py` supports reveal plus Again/Hard/Good/Easy with Space/1/2/3/4 shortcuts. Due-queue reads, review submissions, and post-batch queue reloads run through one page-owned `AsyncWorker`; controls remain guarded until each database operation completes.
- Starting a review session from sidebar navigation dismisses any visible reminder banner, preventing stale counts from remaining above an active review.
- `app/ui/dashboard_page.py` shows due count, completed today, seven-day accuracy, streak, and frequent wrong words. Statistics load off the GUI thread; refresh requests arriving during a load are coalesced into one follow-up refresh.

### Confusion analysis

- `app/domain/similarity.py` implements Levenshtein distance, bounded spelling similarity, clipped 0–1 cosine similarity, one-to-one co-error matching, and temporal exponential decay. Nearest temporal matches use sorted binary search instead of a quadratic history scan.
- `app/services/analysis_service.py` selects words with at least two errors in the configured recent window, limits candidates to 100, obtains optional embeddings, scores candidate pairs, replaces graph edges, and exposes clusters.
- The default relation formula is `0.30 semantic + 0.25 spelling + 0.30 co-error + 0.15 temporal`, threshold `0.65`.
- Candidate selection and cluster error counts use the same closed 30-day window; future-dated ReviewLog rows are excluded.
- Relation labels are inferred from normalized weighted contributions, so custom weights cannot produce a label that contradicts the score formula.
- `app/domain/clustering.py` uses connected components; clusters above eight words pass only their highest-weight core words to the LLM.
- The Analysis list defines an explicit readable selected-item style; selection no longer renders dark/white text invisibly against the platform theme.
- `scripts/create_demo_data.py` idempotently creates correlated errors for three groups. Latest deterministic demo result: 7 candidates, 5 edges, 3 clusters (`adapt/adopt/adept`, `economic/economical`, `complement/compliment`).
- `scripts/benchmark_confusion_graph.py` creates an ephemeral dense graph with 100 candidates, 100 synchronized errors per candidate, and 4,950 persisted edges; it asserts the exact result, runs three timed rebuilds, and fails if the median exceeds a configurable five-second budget. It never touches the runtime database.

### LLM and Embedding integration

- `app/ai/llm_provider.py` is the LLM abstraction.
- `app/ai/ollama_provider.py` uses Ollama `/api/chat`.
- `app/ai/openai_compatible_provider.py` supports OpenAI-compatible chat and normalizes `/v1` without duplication.
- `app/ai/embedding_provider.py` uses Ollama `/api/embed` behind an independent Embedding Provider and SQLite cache.
- Chat and Embedding adapters reject non-object JSON responses through their project-defined unavailable exceptions, preserving service-level degradation instead of leaking raw `AttributeError` failures.
- Ollama chat and embedding calls set `trust_env=False`, preventing Windows/HTTP proxy settings from capturing localhost traffic.
- The Embedding adapter allows a 60-second cold start; the observed first load was 20.159 seconds, so the old 20-second limit was too brittle.
- Chat and embeddings have separate provider, base URL, and model settings.
- Embedding cache identity includes provider type, base URL, and model.
- Invalid or non-finite cached vectors are deleted and regenerated. Model calls occur outside SQLite transactions so an Embedding cold start cannot hold a database transaction open.
- Embedding cache persistence uses SQLite conflict-update semantics, so simultaneous workers converge on one valid row instead of raising a unique-key error.
- `app/ai/prompts.py` is the only location for model prompts.
- `app/ai/schemas.py` strictly validates structured cluster analysis with Pydantic, forbids extra fields, caps every text field, permits at most eight word explanations and six bounded exercise options, and rejects raw structured responses above 32,000 characters.
- `app/services/ai_service.py` retries invalid structured JSON once, then returns a safe degraded result; normal chat also degrades without crashing.
- Local and advanced chat Providers have independent provider/model/base-URL/API-key settings. `create_advanced_llm_provider` returns `None` when disabled and constructs an Ollama or OpenAI-compatible adapter when explicitly configured; the UI enables the advanced choice only in the latter case.
- API-key fields are excluded from the Settings representation. Keys remain local to `.env` and are never rendered by the settings page or logged.
- Structured cluster output must explain every algorithm-selected input word exactly once; schema-valid output containing missing, duplicate, or unrelated words is rejected and retried.
- AI cache identity includes prompt version, provider type, model, base URL, cluster words, relation type, and major statistics.
- If another window stores the same AI analysis after the initial cache read, the losing writer reloads the winning validated row and returns it as a cache hit.
- `app/domain/query_routing.py` owns an injectable deterministic policy that normalizes input and returns an explainable `LOCAL`, `CONFIRM_ADVANCED`, or `REFUSE` decision with bounded confidence. English markers use word boundaries, and an off-topic marker is overridden only by explicit metalinguistic intent such as asking for a meaning or translation. Long or complex language tasks require explicit user choice; an LLM never selects the model.
- The local assistant rejects empty, general-chat, real-time, and professional out-of-scope requests without calling a model. The Chat UI consumes the structured route instead of comparing a magic confidence threshold.
- Questions above 4,000 normalized characters are refused before any Provider call. Providers request at most 2,048 output tokens, ordinary answers are bounded to 4,000 characters, model names to 200 characters, and the Chat/Analysis text documents retain only 200/300 blocks respectively.
- Chat keeps at most the four most recent successful in-session exchanges and applies a separate 6,000-character history budget before prompt construction. Failed, degraded, refused, and incomplete exchanges are never retained; history is intentionally memory-only and disappears when the application closes.

### Reminder and desktop lifecycle

- `app/domain/reminder_policy.py` is deterministic and independently tested.
- It suppresses reminders with no due words, during a review, during cooldown/snooze, before 08:00, after 23:00, or after the day's work is complete.
- `app/services/reminder_service.py` persists notification, snooze, and completion state across restarts.
- Reminder evaluation reloads the authoritative runtime row inside a serialized transaction. `evaluate_and_claim` records the cooldown in that same transaction, so concurrent application instances cannot both win the same notification opportunity.
- ReminderService accepts an injectable clock so constructor state and explicit evaluations use one deterministic time source; this prevents tests and state transitions from drifting across real midnight.
- A newly due word on the same day clears a stale completed state.
- A far-future persisted notification timestamp cannot suppress reminders indefinitely after a system-clock correction; only a small rollback within the configured cooldown remains suppressed.
- Main-window reminder evaluation, snooze persistence, and post-session completion checks share one FIFO `AsyncWorker` queue. Duplicate timer evaluations are coalesced, and no reminder database operation blocks Qt event handling.
- Snooze and notification claims return an absolute persisted cooldown-expiry time. A dedicated single-shot Qt timer schedules that exact re-evaluation while the five-minute heartbeat remains as recovery for restart, sleep, clock changes, and duplicate-instance races.
- Each application process owns a renewable 10-minute active-review lease. Entering/reviewing publishes it, leaving or closing releases it, expired leases are deleted during evaluation, and any live instance lease suppresses notifications across all windows.
- `app/infrastructure/notification_adapter.py` keeps the Qt system tray and prefers Windows-Toasts on Windows. Native Toast and the in-app banner both expose “start review” and “snooze 30 minutes”; native callbacks are queued through a Qt signal bridge before touching UI state. Native initialization/send failures degrade to the Qt tray bubble.
- Installer-marked frozen builds use the dedicated `CET.Agent.Desktop` AUMID created by the Start Menu shortcut. Source/portable runs cannot claim that identity merely because an installed shortcut also exists. Every process tracks and removes only its own Toast rows during close, so dead action buttons do not remain and one instance cannot clear another instance's notification history.
- `app/ui/widgets/reminder_banner.py` remains the always-visible in-app copy of both notification actions.
- `app/ui/main_window.py` waits for active dashboard, review, analysis, chat, and reminder QThreads before destroying the window. If a finishing task starts a chained reload during deferred close, the new worker is also watched before shutdown continues. Attaching a close watcher is followed by an `isRunning()` re-check, so a worker that finishes between discovery and signal connection cannot leave the hidden window waiting forever. The smoke path closes the real window instead of terminating the event loop around live workers, and deferred close explicitly ends the application after a hidden window has released its final lease.

### Resilience and diagnostics

- Model unavailable, embedding unavailable, invalid JSON, empty data, no clusters, and SQLite busy conditions have recoverable paths.
- Failed review-queue reloads clear and disable the stale card; dashboard and analysis refresh failures display safe state instead of leaking an exception through a Qt callback.
- Analysis refresh clears detached AI output and resets stale error status before presenting a new cluster snapshot.
- Unexpected UI and startup exceptions are logged with full detail but converted to stable generic user messages; filesystem, SQL, and transport details are not rendered.
- While chat is waiting for a low-confidence routing choice, its pending question and input controls are locked so a second send cannot silently replace the first question.
- Blocking dashboard, review-database, model, and network work runs in `AsyncWorker` QThreads, not on the UI thread.
- Detailed failures go to logs; user-facing messages remain concise.
- Root logging configuration is serialized within the process, preventing concurrent bootstrap calls from registering duplicate rotating-file and console handlers.
- pytest cacheprovider is disabled by `pytest.ini` to avoid cache-directory write failures in restricted environments.
- `scripts/validate_local_ai.py` is the repeatable P0 integration check for live chat, cached embeddings, semantic graph rebuild, structured cluster output, and AI cache reuse. Its latest cold and warm runs both exited successfully.

### Delivery engineering

- `requirements.txt` and `requirements-dev.txt` declare compatible direct dependencies; the corresponding `.lock` files pin the complete tested runtime and development dependency trees. Regenerate them with pip-tools 7.6.1 after changing a direct dependency.
- `pyproject.toml` centralizes the Python 3.11 Ruff and Mypy baselines. The entire Python tree is Ruff-formatted; CI rejects lint, format, or application/script type-check drift.
- `.github/workflows/ci.yml` runs on Windows for Python 3.11 and 3.13 with read-only repository permission. It installs the development lock, runs `pip check`, Ruff lint/format, Mypy, all tests, and the offscreen startup smoke. No Git remote is configured yet, so the workflow is locally validated but has not had a hosted run.
- `packaging/CET-Agent.spec` builds a windowed PyInstaller 6.22.0 onedir release, includes the Windows-Toasts/WinRT extensions and license metadata plus required vocabulary/config resources, and explicitly excludes the unused `fsrs.optimizer` scientific-training stack. CI builds and launches the package with isolated `LOCALAPPDATA`, then asserts writable database, log, and config-template paths.
- `packaging/CET-Agent.iss` and `scripts/build_windows_installer.py` create an unsigned current-user Inno Setup installer from the onedir tree. It uses a stable AppId, installs below `%LOCALAPPDATA%\Programs\CET-Agent`, creates a dedicated-AUMID Start Menu shortcut and optional desktop shortcut, and intentionally leaves `%LOCALAPPDATA%\CET-Agent` learning/config/log data intact on uninstall.

## 5. Verification ledger

Update this section after every material change. Never report a feature as verified based only on code inspection.

| Verification | Latest result | Evidence date |
|---|---:|---:|
| Full pytest suite | 175 passed in 6.62s | 2026-08-22 |
| Ruff static check | all checks passed | 2026-08-22 |
| Ruff format gate | 89 files already formatted | 2026-08-22 |
| Mypy application/scripts check | exit code 0; 57 source files | 2026-08-22 |
| Non-blocking dashboard/review UI | worker-thread identity, rendered dashboard result, refresh coalescing, safe failure state, asynchronous queue load/submission, batch reload, and active-worker tracking passed; 19 focused tests passed | 2026-08-22 |
| Serialized reminder tasks and atomic claim | two concurrent ReminderService instances produced exactly one notification winner; FIFO task order and non-GUI thread identity passed; snooze/day rollover and persisted completion regressions passed | 2026-08-22 |
| Exact reminder wake-up | persisted Snooze and claimed-notification cooldowns expose one absolute 30-minute expiry; UI millisecond conversion is exact, non-negative, and Qt-bounded; restart evaluation reconstructs the same target; focused reminder/UI tests passed | 2026-08-22 |
| Actionable Windows notifications | four focused tests passed: exact Start/Snooze action payloads, background-thread callback delivery on the Qt GUI thread, frozen install-marker/AUMID selection, native-send failure fallback, and per-process Toast cleanup. A live installed Toast was present under `CET.Agent.Desktop` with both exact action arguments; process close reduced that history from 1 to 0 | 2026-08-22 |
| Cross-instance active-review lease | independent owners coexist; releasing one preserves another; observer notifications are suppressed; expired leases are removed; hidden review-worker results cannot republish activity | 2026-08-22 |
| AI capacity budgets | oversized question refusal, 4,000-character chat truncation, 32,000-character structured raw guard, bounded schema fields/lists/options, 2,048-token Provider requests, and 200/300-block UI documents passed | 2026-08-22 |
| Bounded in-session chat context | four-exchange/6,000-character budgets, complete-pair retention, prompt role order, and second-question UI context propagation passed; history remains memory-only | 2026-08-22 |
| Concurrent fresh bootstrap | three repeated two-worker runs on separate fresh databases all returned 4,611 words and one activation per worker; regression test also passed | 2026-08-22 |
| Bootstrap/logging failure safety | forced schema-upgrade failure disposed its Database; simultaneous logging configuration registered exactly one file/console handler pair | 2026-08-22 |
| Per-level first activation | fresh CET4 rebased exactly 3,320 untouched open words once; later CET6 activation independently rebased 1,278; repeat startup preserved the original activation | 2026-08-22 |
| Legacy level adoption | open-word review history preserved every due time and adopted its earliest review timestamp; curated/demo-only history did not suppress first real level activation | 2026-08-22 |
| Deterministic chat routing | regression cases cover local vocabulary/grammar, Unicode normalization, advanced confirmation, empty/general/off-topic refusal, English word boundaries, guarded scope override, and zero-call refusal | 2026-08-22 |
| Provider response-shape degradation | non-object and malformed nested OpenAI-compatible chat JSON plus non-object Ollama Embedding JSON normalized to project unavailable exceptions | 2026-08-22 |
| Current-window confusion analysis | future-only repeat errors produced 0 candidates, 0 edges, and 0 clusters; current cluster counts remain window-aligned | 2026-08-22 |
| Bundled metadata upgrade | corrected phonetic/meaning/example/level/frequency applied to an existing word while its ID, review count, stability, and due time remained unchanged | 2026-08-22 |
| Advanced Provider bootstrap | disabled/default, independent OpenAI-compatible construction, invalid/incomplete configuration rejection, explicit advanced dispatch, and API-key repr redaction passed | 2026-08-22 |
| Live advanced-provider dispatch | explicit advanced choice returned a non-degraded 283-character response from independent `qwen2.5:3b` while the local Provider pointed to an unreachable endpoint | 2026-08-22 |
| 100-candidate graph performance | 100 errors per candidate and all 4,950 edges: 0.932s, 0.907s, 0.913s; median 0.913s; exact one-cluster invariant passed | 2026-08-22 |
| Locked dependency install | clean Python 3.13 virtual environment installed `requirements-dev.lock`; `pip check` passed; Python 3.11/win_amd64 wheel-resolution dry run passed | 2026-08-22 |
| GitHub Actions workflow | Windows Python 3.11/3.13 matrix defined with current official v7 checkout/setup actions; local-equivalent full gate passed; hosted run pending remote configuration | 2026-08-22 |
| Schema migration matrix | 7 focused tests passed: fresh, pre-version adoption, v1→v2 FSRS mapping, v2→v3 level activation, v3→v4 review leases, idempotency/newer-version guard, transactional rollback | 2026-08-22 |
| Official FSRS-6 reference vectors | initial Again/Hard/Good/Easy plus five-review sequence passed against py-fsrs 6.3.2 | 2026-08-22 |
| Deterministic randomized algorithm invariants | 6,000 checks passed | 2026-08-22 |
| Concurrent review/AI/Embedding focused regression | 15 tests passed in five consecutive runs; no lost update or cache exception | 2026-08-22 |
| Open vocabulary artifact | deterministic rebuild hash matched `1afc9925…9a16f`; 4,598 unique rows, 3,320 CET4 + 1,278 CET6, Chinese meaning and phonetic coverage 100%, no curated overlap | 2026-08-22 |
| Bundled vocabulary import | 4,611 total words/states; second import inserted 0; invalid/duplicate/out-of-range rows rejected before mutation | 2026-08-22 |
| Offscreen startup/shutdown smoke | 20 consecutive exit-code-0 runs; subprocess regression passed; real close path waits for lease-release worker and explicitly quits after hidden deferred close, eliminating the prior `0xC0000409` crash and post-close hang | 2026-08-22 |
| SQLite integrity and foreign keys | schema v4; 4,611 runtime words (3,329 CET4 + 1,282 CET6); `integrity_check=ok`; no foreign-key violations; no stale review leases | 2026-08-22 |
| Demo graph | 7 candidates, 5 edges, 3 clusters | 2026-08-22 |
| Ollama chat through project provider | cold 29.490s; warm 1.246s; non-degraded Chinese response | 2026-08-22 |
| Ollama embedding through cached provider | 2 vectors, dimension 768; cold 20.159s; cache rows 0→2→2 | 2026-08-22 |
| Semantic graph rebuild | 7 candidates, 5 edges, 3 clusters; `embedding_available=true` | 2026-08-22 |
| Structured cluster JSON and AI cache hit | first live result `cached=false`; second `cached=true`; Pydantic passed | 2026-08-22 |
| Latest warm full local-AI validation | exit code 0 on schema v4 repeat startup; chat 2.606s; embedding cache rows remained 7→7→7; graph 7 candidates/5 edges/3 clusters; structured analysis cached true→true | 2026-08-22 |
| Live uncached bounded structured output | `accept/except` analysis under the 2,048-token Provider limit returned non-degraded schema-valid output for both words; 829 JSON characters | 2026-08-22 |
| Frozen writable-path resolution | source/frozen/local-app-data/home-fallback/relative-database cases plus non-overwriting `.env.example` install passed | 2026-08-22 |
| Windows onedir package | final rebuild includes Windows-Toasts/WinRT binaries and distribution license metadata; isolated smoke exited 0, created schema v4 with 4,611 words and `integrity_check=ok`, installed `.env.example`, and left the package directory state-free | 2026-08-22 |
| Unsigned Windows installer | Inno Setup 6.7.3 compiled `CET-Agent-Setup-0.1.0.exe` (44.68 MiB, SHA-256 `6D72CBD2FD5734FBC36056FF87D67F90921878EDA984271C3E37C1DF97D2C1F9`, intentionally `NotSigned`). Current-user silent install created executable/uninstaller/install marker/Start shortcut/registry entry; installed smoke produced schema v4, 4,611 words and `integrity_check=ok`; silent uninstall removed program/shortcut/registry while preserving the learning database byte-for-byte | 2026-08-22 |
| Visible Windows desktop flow | navigation, reminder banner, Space reveal, `3=Good`, next-card load, cluster selection/readability, cached AI display, settings, close/restart passed; Snooze then immediate close exited with zero process/lease remnants; a controlled 15-second local Provider proved close began with two live workers before the response and exited automatically after completion; final installed build visibly rendered the actionable in-app reminder while the matching native Toast existed in Windows history | 2026-08-22 |

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
python -m PyInstaller --noconfirm --clean packaging/CET-Agent.spec
python scripts/build_windows_installer.py
python main.py
```

## 6. Known incomplete work

### Deferred delivery work

- Application icon, Windows executable version resources, digital/code signing and its pipeline, and Git remote/hosted CI execution are explicitly deferred by current user direction. The current installer is therefore intentionally unsigned and uses default generated executable/installer resources.
- The locally installed Inno Setup 6.7.3 compiler identifies itself as “Non-commercial use only”. This is sufficient for the present local/non-commercial validation; any commercial distribution must use an appropriately licensed Inno Setup compiler or replace the installer toolchain.
- A physical human click on both buttons in the real Windows notification flyout is not recorded. The system accepted a dedicated-AUMID Toast containing both exact action nodes, and callback routing/thread affinity is deterministically tested, but a future release checklist should retain a two-click manual acceptance check on each supported Windows version.

## 7. Key design decisions

1. Algorithm first: structured deterministic evidence is produced before any LLM call.
2. Provider separation: LLM and Embedding endpoints are independently configurable because real deployments commonly use different servers/models.
3. Cache namespacing: endpoint identity is part of cache identity so switching providers cannot silently reuse stale model output.
4. Window consistency: candidate selection and displayed cluster error counts refer to the same configured recent period and never accept events after the evaluation time.
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
19. Explainable model routing: a pure domain policy combines normalized learning intent, word-boundary-aware English markers, precise out-of-scope phrases, text size, and task complexity into a structured route. Only explicit metalinguistic intent can override an ambiguous off-topic noun, and the UI never infers a route from a magic numeric threshold.
20. Explicit advanced-model opt-in: advanced chat is a separately configured Provider, disabled by default, and invoked only after the deterministic policy asks and the user chooses it. Its credentials and endpoint identity never replace or leak through the local Provider configuration.
21. Dense graph budget: scale validation uses identical deterministic embeddings and 100 synchronized errors per candidate so all 4,950 possible edges survive, covering pair scoring, practical history density, and maximum SQLite persistence cost. The repeatable script uses an ephemeral database and a conservative five-second median guard.
22. Fail-fast configuration: malformed environment values, model endpoints, graph settings, and reminder settings are rejected before use; invalid inputs are not silently replaced with defaults.
23. Monotonic review history: a review cannot be committed at or before that word's previous review timestamp.
24. Cache self-repair: malformed Embedding cache rows are discarded and regenerated, and network/model waits never occur inside an open cache transaction.
25. Evidence alignment: Pydantic shape validation is necessary but not sufficient; structured AI explanations must also match the exact algorithm-selected word multiset.
26. Current-time statistics: future-dated events are excluded from dashboard and confusion-analysis calculations rather than being trusted as learning behavior.
27. Review-session ownership: entering an active review dismisses the in-app reminder immediately; reminder content must not remain visible with a stale due count while the user is reviewing.
28. SQLite write serialization: state-dependent review writes reserve the SQLite writer before reading; `with_for_update()` alone is not treated as protection on SQLite.
29. Concurrent cache convergence: Embedding uses database upsert and AI analysis resolves a unique-key race by returning the already committed, locally revalidated winner.
30. Official deterministic FSRS: scheduling delegates to pinned `py-fsrs` 6.3.2, with fuzzing disabled and reference-vector tests. The adapter keeps the application's stable Rating/result interface while schema v2 persists the library's card phase and step.
31. Bundled metadata ownership: validated bundled word metadata may be corrected on later startup, but importing vocabulary must never replace a user's LearningState, scheduling state, or ReviewLog history.
32. Provider response shape: a syntactically valid but structurally invalid HTTP response is an unavailable-provider condition and must cross the adapter boundary as the project-defined safe exception.
33. Safe presentation boundary: unexpected exception detail belongs in rotating logs; user-visible UI receives stable action-oriented text without filesystem, SQL, or transport internals.
34. Independent level activation: a CET level's open wordbank release anchor is created only on first real activation. Only cards with no ReviewLog, no last review, and zero review count may be rebased; curated words and any learned state are immutable under this operation.
35. Convergent bootstrap: connection-level WAL negotiation receives the same bounded busy tolerance as transactional writes, every first-start mutation remains serialized and idempotent, and the bootstrap function owns disposal whenever it cannot return a usable Database.
36. Page-owned background work: each interactive page permits at most one database/model worker at a time, renders results only on the Qt thread, and exposes its active worker to the main-window deferred-close coordinator. Dashboard refreshes coalesce; review submissions preserve the current card until persistence succeeds.
37. Atomic reminder claim: the persisted runtime row is authoritative at evaluation time. A process may present a notification only after it records the cooldown under the SQLite writer reservation; local startup snapshots never decide cross-process ownership. Reminder database actions are FIFO-serialized off the GUI thread.
38. Expiring review leases: active-review suppression is a per-instance lease table rather than a singleton flag. Multiple windows may coexist, each owner can release only itself, evaluations prune expired crash remnants, and the five-minute reminder heartbeat renews a ten-minute lease.
39. Layered AI capacity budgets: deterministic routing rejects oversized inputs, Provider requests cap generation tokens, Service output is truncated or rejected before construction/cache, Pydantic caps every structured field and collection, and Qt documents prune old blocks. No single layer is trusted as the only bound.
40. Frozen path ownership: packaged resources are immutable inputs, while every mutable artifact belongs under a per-user local application-data root. Source mode intentionally preserves repository-local paths for developer ergonomics; packaged smoke must override `LOCALAPPDATA` and prove the distribution tree stays unchanged.
41. Ephemeral bounded conversation: follow-up questions may use only recent complete successful exchanges, capped independently by count and characters. Conversation state belongs to the current Chat page, is never written to SQLite, and cannot turn a refused or degraded response into future prompt context.
42. Event-loop-owned shutdown: smoke and interactive close both enter the real window close path. Application exit occurs only after every page/reminder worker has finished and the process-owned review lease has been released, including when the window is already hidden during deferred close.
43. Lost-finish recovery: a close watcher must connect to `finished` before checking the worker state again. The signal covers future completion and the post-connection state check covers completion that raced ahead of the connection; duplicate deferred-close scheduling is harmless and preferable to a hidden hung process.
44. Absolute reminder wake-up: persisted cooldown state owns the target time and the UI owns only timer scheduling. Both heartbeat and one-shot paths re-evaluate through the same atomic policy; no UI timer is allowed to bypass the database claim or independently decide to notify.
45. Layered notification delivery: deterministic ReminderService state decides whether a reminder exists; the operating-system adapter decides only how to present it. Native callbacks must enter Qt through a queued signal, and any native backend failure falls back to the tray without changing notification claims or scheduling.
46. Notification identity ownership: only a frozen executable carrying the installer-only marker and matching Start shortcut may claim the dedicated AUMID. All source, portable, and installed processes remove their own tracked CET-Agent Toasts individually and never clear a whole identity, preserving reminders owned by concurrent instances.
47. Current-user installer ownership: the installer copies only immutable program files under the user's Programs directory. Mutable learning state remains in the separate application-data root and survives upgrades/uninstall. Stable AppId/AUMID values are release compatibility contracts even while icon, version-resource, signature, and remote-delivery work is deferred.

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
