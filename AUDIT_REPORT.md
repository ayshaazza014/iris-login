# AUDIT_REPORT.md — Full-Repository Audit (Django Iris Biometric Auth)

**Audit date:** 2026-10-26
**Auditor:** OpenCode agent (GLM-5.3-Flash), skills applied: `security-audit` (OWASP lens), `broken-authentication` (auth checklist), `bugs-are-annoying` (finding ledger → `bugs.md`)
**Scope:** every tracked file in the repository (47 tracked files), plus runtime verification
**Companion artifact:** [`bugs.md`](bugs.md) — the complete 25-finding ledger in Trigger/Impact/Fix/Confidence/Status format. This report cross-references BUG-001…BUG-025 from it.

---

## 1. Executive summary

**Verdict:** The biometric/auth core is genuinely well-built — fail-closed paths, correct server-side authorization, honest docs, and an unusually thorough test suite (61 Django + 11 pytest, all passing). **But the system's three brute-force-defense pillars have critical defects, and the single hardest TRD requirement (measured evaluation) is entirely absent.** This project should remain a single-user demo; it is not deployable beyond that until the P0 items below are closed.

### The five findings that define the audit

| # | Finding | BUG | Why it matters |
| --- | --- | --- | --- |
| 1 | **Repo-committed `synthetic_eye.png` acts as a working universal login** for the seeded account `alice` — enrolling validly over the legacy `gabor-v1` path during the documented `seed_users` boot step | 🔴 BUG-005 | Anyone with repository access holds one of the account's credentials in plaintext biometric-equivalent form. TRD §6:98 explicitly forbids committing capture-like artifacts. |
| 2 | **Rate limiting is bypassable with one header** — the first hop of `X-Forwarded-For` is trusted as client identity | 🔴 BUG-001 | Every `ip:action` limit (login, register, verify-iris, staff-login) becomes a no-op for an attacker rotating headers — and because the biometric factor has no password fallback, rate limiting *is* the brute-force defense. |
| 3 | **Thresholds are not calibrated and no evaluation exists** — `0.32/0.35` with source-comment origin, env-overridable, no FAR/FRR report anywhere | 🔴 BUG-002, BUG-003 | TRD FR-08 + FR-13 + §8 + acceptance §9 are all unmet. FAR/FRR are unknown and unmeasurable per TRD's own protocol. The system cannot support its honest-accuracy stance quantitatively. |
| 4 | **Rate limiter memory grows without bound** (no key eviction) and is per-process only | 🔴 BUG-004 | Combined with BUG-001 this is a memory-exhaustion DoS vector; in multi-worker deployments counters fragment, silently weakening limits. |
| 5 | **Django 5.0.14 is pinned and EOL** — no security releases | 🟡 BUG-014 | Any deployed instance runs an unsupported framework. P1 today, P0 the moment anything is exposed. |

### What the audit credits (verified-solid — do not regress)

Rate limiting executes **before** any image decoding on every endpoint; a real decompression-bomb guard (header-only inspection + post-decode re-validation) precedes OpenCV; staff/student isolation and the 1:N population filters are backend-enforced and correct; ambiguity is fail-closed; CSRF is wired through both templates and `camera.js`; no XSS vector was found (all dynamic text via `textContent`); admin cannot touch template bytes; unknown/failed matching never creates a session; home.html carries the required no-accuracy/no-liveness disclaimer; repo hygiene is fundamentally clean (`.env`/`db.sqlite3` untracked, clean working tree). Full list in `bugs.md` § "Verified-solid".

---

## 2. Scope and method

### 2.1 What was examined

- **Application code:** `iris_auth_app/` — `views.py` (555-line auth controller), `services.py` (matching/persistence), `models.py`, `urls.py`, `admin.py`, `apps.py`, `forms.py` (as present), `management/commands/seed_users.py`, `migrations/0001_initial.py`.
- **Pipeline:** `iris_extract.py` (vendored OpenCV/Gabor extractor — shape (256,512), segmentation, mask math, encoding `gabor-eye-crop-v2`, legacy `gabor-v1` accepted).
- **Project shell:** `iris_auth_project/` — `settings.py`, `urls.py`, `wsgi.py`, `asgi.py`; root `manage.py`.
- **Frontend:** all templates (`home`, `login`, `register`, `student-dashboard`, `staff-dashboard`, `verify` variants) and static assets (`camera.js`, stylesheets).
- **Quality surface:** `tests.py` (61 tests), `tests/` pytest suite (11 tests), `requirements.txt`.
- **Docs/contract:** `trd.md`, `README.md`, `bugs.md`, other repo-level docs.
- **Repo hygiene:** `git status`/untracked inventory; junk artifacts (root `iris` — 0 bytes, confirmed untracked); `.env` presence (untracked, contains a real-looking `DJANGO_SECRET_KEY`).
- **Prototypes:** `prototypes/webcam_poc/` (index.html + assets) — reviewed, demoted to non-shipping POC.

### 2.2 How

1. **Static line-by-line review** of all application code with contract sources (`trd.md` FR-01–FR-13, §6–§9) pinned to line numbers.
2. **Skill-driven lenses:** OWASP-style threat mapping (see §3), the broken-authentication checklist (see §4), and the bugs-are-annoying artifact standard for `bugs.md`.
3. **Runtime verification** (§2.3) to separate "code as written" from "code as executes," and to re-verify or withdraw earlier hypotheses (e.g., the "admin can overwrite template bytes" concern was withdrawn after reading `admin.py:20-26`; the false exit-code-1 was a PowerShell stderr artifact and was re-verified to exit 0).

### 2.3 Runtime evidence

| Check | Result |
| --- | --- |
| `python manage.py test` | `Ran 61 tests in 9.754s` — **OK, exit 0** |
| `pytest tests` | **11 passed** |
| `pip freeze` vs `requirements.txt` | Exact match — Django==5.0.14, numpy==2.2.6, opencv-python==4.10.0.84, pytest==9.1.1 (extra entries are pytest transitives) |
| Seed output observed during tests | `Enrolled synthetic_eye.png template for alice.` — traced to `tests.py:967-968` explicitly invoking the seed command, **not** auto-seeding |
| `git status` | Clean working tree; no accidental tracked secrets |
| Boot path | `.venv` PowerShell → `migrate` → `seed_users` → `runserver` — reproducible per README |

A later-phase finding was deliberately **withdrawn** after verification: the "no enrollment-overwrite history" concern does not apply — admin inline forms exclude `code`/`mask` (`admin.py:20-26`, readonly `75-84`), so no human can mutate template bytes, and Django's LogEntry covers enrollment-status transitions.

---

## 3. Security audit (OWASP-lens results)

Grouped by attack surface; every item cross-references its full write-up in `bugs.md`.

### 3.1 Authentication integrity

- 🔴 **BUG-005 — synthetic-eye universal login.** The *documented boot step* enrolls a repo-tracked image as a working credential. This converts the repository itself into a credential store. Beyond gating on DEBUG, the fixture must not double as a login (generate synthetic imagery at seed-time instead of shipping it).
- 🟡 **BUG-006 — 1:N for students without an account identifier.** The identifier path honors FR-07 (1:1), but a post with only an image runs the student against the whole non-staff population (`views.py:483`). TRD FR-04 (§2:44) says 1:1. This is a deliberate UX decision applied to the *wrong weakest link class* — identification widens false-accept surface by the number of enrolled students. Include matching-input cross-reference: `services.py:266-269` (population filters) and the ambiguity tie-break `services.py:305-310` exist and are worth keeping — but the default path should be a verified account match, not open identification.
- ⚠ password factor is vacuous by design (`password=None`, `views.py:247-252`): iris is the *only* factor, raising the stakes on rate limiting and thresholds.

### 3.2 Brute force / rate limiting

- 🔴 **BUG-001 — XFF-spoofable identity** (`views.py:76-80`). Fix: default `REMOTE_ADDR`, honor XFF only under an explicit trusted-proxy flag, and take the *last* hop when enabled.
- 🔴 **BUG-004 — unbounded in-process limiter** (`views.py:50`): no key eviction; shards across workers. Move to Redis/DB or add a sweep; document semantics.
- 🟡 **BUG-007 — inconsistent policy and the `_rate_limited_checked` attribute-coupling** (`views.py:180/60` login AJAX vs `30/60` verify_iris; wiring at `views.py:448-456`, `518-523`). Single limiter, single policy set.
- 🟡 **BUG-008 — client volume**: `camera.js` uploads a full-frame PNG every 550 ms and only pauses 1.5 s on 429 (`camera.js:116`, `212-214`). The server correctly spends CPU before any decode (credit), but the client must throttle and back off harder.
- Broken-auth cross-check verdict (see §4): fix BUG-001 + BUG-007 and the biometric brute-force surface is effectively closed for a demo.

### 3.3 Input/validation & DoS

- ✅ Decompression-bomb guard is real: header-only dimension inspection for PNG/JPEG/WebP with caps (5 MB, 2048×2048, 16 MP) **before** decode (`views.py:32-35`, `89-201`) and re-validation post-decode (`views.py:192-200`); every rate-limit 429 path fires before decode.
- 🟡 **BUG-012** — no enrollment-side image-quality gate: glare/blur/eyelash-heavy captures become active templates.
- 🟡 interrogated and resolved: silent secondary-template drop (`services.py:68-79`) is fail-safe, but it should be a loud decision not a silent one (BUG-011).

### 3.4 Session / authorization

- ✅ Server-side session grant only on verified match; mismatch/unknown → no session (TRD §7:101-102 honored everywhere).
- ✅ Dashboards re-verify staff server-side (`views.py:540-548`); 1:1 paths reject staff/superusers on the student side (`views.py:465`, `services.py:266-269`) and conversely for the staff path (`views.py:307`).
- 🟢 **BUG-022** — `camera.js` trusts server-issued `redirect_url`; today it is always the server constant (`views.py:470`, `490`), so this is belt-and-brace only.
- 🟡 **BUG-015** — anonymous open registration vs FR-05's "authorized enrollment workflow"; deliberate product choice that must be made explicit (flag or staff/supervisor counter-sign) before anything beyond a toy.

### 3.5 CSRF / XSS / clickjacking

- ✅ CSRF middleware + embedded `csrfmiddlewaretoken`; `camera.js` fetches reuse the form token (`camera.js:170-173`); **no `@csrf_exempt` anywhere** in the tree.
- ✅ No XSS vector found: all cross-boundary DOM writes use `textContent` (`camera.js:202`, `209`); template rendering is Django-escaped.

### 3.6 Configuration / transport

- 🔴→deploy-scoping — **BUG-010**: `DEBUG` defaults to `True` when the env is absent (`settings.py:26`).
- 🟡 **BUG-009**: the production branch lacks `SECURE_SSL_REDIRECT`, `HSTS`, and trusted-proxy header config (`settings.py:45-50`).
- ✅ **SECRET_KEY management is fail-closed** (hard error when missing rather than a hardcoded fallback — `settings.py:27-31`). This is an uncommon strength in student projects.
- 🟡 **BUG-014** — Django 5.0.x pinned and EOL; upgrade line is requirements-only (5.2 LTS is the target).
- 🟢 **BUG-025** — the local `.env` holds a real-looking secret; untracked (correct), but it should be rotated/scratched and excluded from any handoff (ops note, not a repo leak).

### 3.7 Information disclosure / logging

- 🟡 **BUG-013** — matched username and failure reason logged at INFO per scan (`views.py:484`), touching TRD §7:107 ("do not log … unnecessary matching details").
- 🟢 Login UX-side: user-facing messages never reveal account existence (enumeration-safe); the only leak is cosmetic — login-page placeholder shall keep demo usernames visible (BUG-021).
- 🟢 broad exception tuples (BUG-016) never surface stack traces to users (NFR-03 compliant on user-facing side; internal clarity is degraded).

---

## 4. Authentication audit — broken-authentication checklist

| Check | Result |
| --- | --- |
| Credential-less password brute force | N/A — iris-only auth; `IrisUser` passwords are unusable (`password=None`; `views.py:247-252`) |
| Account takeover via enumeration | Login messages do not reveal account existence (single failure message path); the placeholder leak is minor (BUG-021) |
| Session fixation / privilege confusion | `django.contrib.auth` session cycling on login; client-side redirects are cosmetic; dashboards enforce server-side checks (credit) |
| Brute force on the biometric factor itself | The only integrity line is rate limiting — currently bypassable via XFF (BUG-001) and inconsistently enforced for AJAX (BUG-007). **Closing those two closes the brute-force surface.** |
| Template tampering | Admin cannot edit template bytes (admin form excludes code/mask; readonly fields); staff re-enrollment is `@staff_required` (plus `select_for_update`, which on SQLite dev is a no-op — BUG-023); enrollment-status transitions are logged via Django admin |
| Failure path containment | Unknown/failed matching is fail-closed everywhere; ambiguous >1 match refuses (`services.py:305-309`) rather than guessing |

---

## 5. TRD compliance matrix

Legend: ✅ met · ⚠ partial · ❌ unmet. Evidence is cited as `trd.md` line → repo evidence → findings in `bugs.md`.

### 5.1 Functional requirements (trd.md §4:24-61)

| ID | Requirement (gist) | Status | Evidence / findings |
| --- | --- | --- | --- |
| FR-01 | Clear landing page + iris-login page | ✅ | `home.html`, `login.html` |
| FR-02 | Camera requested after explicit action; denial → useful retry, no access | ✅ | `camera.js` gesture-gated getUserMedia; deny/unavailable branches show retry guidance and fail closed |
| FR-03 | Validate size/type/readability/dimensions before processing | ✅ | Header-only guards + post-decode re-validation (`views.py:32-35`, `89-201`, `192-200`); API limits on both register and verify paths |
| FR-04 | Extraction failure fails closed | ✅ | no session on decode/extract failure — fail-closed credit (note BUG-011 watches secondary handling) |
| FR-05 | *Authorized enrollment*; prevent duplicate usernames; controlled re-enrollment | ⚠ | Duplicates prevented (`models.py:10` unique; `views.py:267-269` IntegrityError); re-enrollment controlled for staff (`views.py:395-436`); but self-registration is open to anonymous users vs the "authorized" wording (BUG-015); SQLite patch caveat BUG-023 |
| FR-06 | Versioned, documented template format (code/mask/shape/dtype/encoding version) | ⚠ | `IrisTemplate` schema covers all fields; live default `gabor-eye-crop-v2` with legacy `gabor-v1` accepted. **Deviation:** migration 0001's DB-side schema default is still `'gabor-v1'` (BUG-017; mask-default nuance per `trd.md:41`) — should not silently drift from the model |
| FR-07 | User identifies account; 1:1 compare with that account's template | ❌ *as designed* | Identifier path is 1:1; the no-identifier student path is true 1:N (`views.py:483`) → BUG-006 |
| FR-08 | Threshold selected on validation data (not from a comment) | ❌ | `services.py:16-17` env-defaults `0.32/0.35`; origin is a source comment; no calibration exists → BUG-002 |
| FR-09 | Only successful server-side verification creates a session | ✅ | fail-closed everywhere; no session created on mismatch/unknown (credit) |
| FR-10 | Deny mismatch/unknown/etc.; messages reveal nothing stored/sensitive | ✅ *user-facing* | Messages enumeration-safe; server logs do record matched username + reason (BUG-013, §7:107) |
| FR-11 | Protected routes verify authentication server-side | ✅ | `views.py:540-548` PermissionDenied guards; client redirects cosmetic only (BUG-022 is a 🟢 note) |
| FR-12 | Controlled enrollment/re-enrollment/deletion for test accounts | ✅ | flows exist (register, staff re-enroll, admin delete) — with quality-gate absence BUG-012 noted as a separate weakness |
| FR-13 | Repeatable evaluation: genuine/impostor, threshold selection, FAR, FRR, dataset limitations | ❌ | No evaluation artifact/scaffold/outcome anywhere in the repo → BUG-003 (with §8 below) |

### 5.2 Non-functional requirements (trd.md §5:63-87)

| ID | Requirement (gist) | Status | Evidence / findings |
| --- | --- | --- | --- |
| NFR-01 | Understandable instructions/errors for beginners | ✅ | Retry/clear messaging throughout `camera.js` + templates |
| NFR-02 | Separate modules, descriptive names, tests | ✅ | `iris_extract.py` / `services.py` / `views.py` layering; 61+11 passing tests (credit) |
| NFR-03 | Fail closed; no stack traces/biometric data exposed to users | ✅ *user-facing* | Fail-closed credit; broad exception tuples (BUG-016) are an internal-code-quality note |
| NFR-04 | Minimize data; no raw-image retention; deletion process | ✅ | Raw images are not persisted (template only); deletion via admin/templates flows; `.env`/db untracked |
| NFR-05 | CSRF, sessions, server-side authz, upload validation, rate limiting, secrets, HTTPS | ⚠ | First five present and largely correct (credits above); **HTTPS/HSTS absent (BUG-009)** and rate limiting is spoofable (BUG-001) |
| NFR-06 | Windows PowerShell setup instructions | ✅ | README's PowerShell venv path verified reproducibly in this audit |
| NFR-07 | Components testable without live camera/browser | ✅ | tests.py + pytest suite exercise matching/reconstruction/persistence without hardware (credit) |
| NFR-08 | Record capture-to-decision latency during evaluation | ❌ | No evaluation means no latency measurement — same root cause as BUG-003 |

### 5.3 Data requirements (trd.md §6:89-98)

| Item | Status | Notes |
| --- | --- | --- |
| Minimum metadata (unique account, display data, template bytes/ref, shape, dtype, encoding version, status, timestamp) | ✅ | `IrisTemplate` schema complete |
| Never expose template contents via frontend responses | ✅ | AJAX payloads contain status/redirect/type only (no code/mask bytes) |
| Avoid storing raw images by default | ✅ | registration/threshold-less flow discards the frame; only the template is stored |
| **Do not commit biometric data, populated databases, or camera captures** | ❌ | `synthetic_eye.png` is committed and functions as a login asset (BUG-005). `db.sqlite3` and `.env` are correctly untracked; no real-person biometric data exists in the repo |

### 5.4 Security requirements (trd.md §7:100-110)

| §7 requirement | Status | Notes |
| --- | --- | --- |
| Access decided only on the backend | ✅ | credit |
| Unknown account / failed match must not create a session | ✅ | credit |
| Enforce size/type checks **before** image decoding | ✅ | bonus credit: full decompression-bomb guard including post-decode re-check; BUG-008 is a client-volume concern, not a server gate |
| Rate-limit repeated attempts | ❌ *as enforced* | Present everywhere (AJAX 180/60 vs file 30/60; `_rate_limited_checked` at `views.py:448-456`, `518-523`) — but BUG-001 spoofable identity, BUG-004 unbounded + per-process, BUG-007 inconsistent policy & the wiring hack, BUG-008 client hammering; and limits run before decode (✅) |
| CSRF protection for state-changing requests | ✅ | no exempt anywhere; token flows via forms + fetch reuse |
| Protect secrets with environment configuration | ✅ | fail-closed SECRET_KEY (`settings.py:27-31`); ops note (BUG-025) |
| Do not log raw images/templates/unnecessary matching details | ⚠ | no raw/template logging; but per-scan INFO `user=…`, reason (BUG-013; §7:107) |
| Document: matcher alone does not provide liveness/PAD | ✅ | home.html disclaimer + README limitations both state it explicitly (contract honesty credit) |
| Consented test data / authorization for collection | ⚠ | only demo/self-consented data exists; nothing conflicting found; the "authorized enrollment" question in FR-05 (BUG-015) is the overlapping gap |
| Treat as academic demonstration, not production identity infrastructure | ✅ | disclaimers honored; aligns with README; but see §6 P0 line — the synthetic credential contradicts the spirit of "atomic demo-only separation" until seeded (BUG-005) |

### 5.5 Accuracy / evaluation protocol (trd.md §8:112-120)

| §8 item | Status |
| --- | --- |
| 1. Separate enrollment/validation/test splits | ❌ (no evaluation exists) |
| 2. Avoid near-duplicate captures across splits | ❌ (same root cause; BUG-002/003 note: identity confusion between "register/eval" flows — TRD's request to prevent identification vs verification conflation remains unaddressed) |
| 3. Genuine + impostor comparisons | ❌ |
| 4. Threshold selected on validation data | ❌ (env/comment default instead) |
| 5. Report FAR, FRR, genuine rate, comparison counts | ❌ |
| 6. State camera/lighting/quality/dataset constraints | ⚠ (README documents limitations qualitatively, but no measured report backs it) |
| 7. Avoid reading a single successful login as accuracy evidence | ✅ *as a stance* (the codebase never makes that inference; the disclaimer is in place) |

### 5.6 Acceptance criteria (trd.md §9:122-134)

| # | Criterion | Status |
| --- | --- | --- |
| 1 | Project setup works in a clean environment | ✅ (README bootstrap verified; `pip freeze`=pin match) |
| 2 | Extractor can be invoked on a sample image (or documented failures identified) | ✅ |
| 3 | Valid template enrolled and loaded without shape corruption | ✅ (tests.py reconstruction + dtype coverage, 61/61 green; watch BUG-019) |
| 4 | Duplicate enrollment handled predictably | ✅ (IntegrityError path; models UniqueConstraint) |
| 5 | Genuine test comparison follows the expected decision path | ✅ |
| 6 | Mismatching/invalid comparison denied | ✅ |
| 7 | Unknown users cannot access protected routes | ✅ |
| 8 | Failed processing never grants access | ✅ |
| 9 | CSRF and upload validation enabled | ✅ |
| 10 | Tests cover enrollment, template reconstruction, matching, route access | ✅ (61 Django + 11 pytest; coverage of gabor cache, mask occlusion, pupil fallbacks) |
| 11 | **Evaluation output reports measured metrics without unsupported claims** | ❌ |
| 12 | README documents setup, usage, evaluation, limitations, data deletion | ⚠ (setup/usage/limitations present and honest; evaluation + data-deletion sections absent — dependent on FR-13) |

**Compliance scorecard:** FR 8 ✅ / 3 ⚠ / 2 ❌ · NFR 5 ✅ / 2 ⚠ / 2 ❌ (BUG-009/BUG-001 in NFR-05, and "evaluation" in FR-13/NFR-08/§8/§9 are the same two root findings) · §7 6 ✅ / 2 ⚠ / 2 ❌.

---

## 6. Prioritized remediation

### P0 — must fix before anyone else can be trusted with this deployment

| # | Action | Finding(s) | Concrete change |
| --- | --- | --- | --- |
| P0-1 | **Trust `REMOTE_ADDR` by default; XFF only under an explicit trusted-proxy flag (and trust the *last* hop)** | 🔴 BUG-001 | `views.py:76-80` — or adopt `django-ipware` with a policy setting |
| P0-2 | **Remove the synthetic-eye login credential from the universal path**; gate enrollment behind DEBUG and generate imagery at seed-time instead of shipping a fixture that doubles as a credential | 🔴 BUG-005 | `seed_users.py:38-48`, delete/stop-tracking `synthetic_eye.png` |
| P0-3 | **Add a real evaluation pass** (held-out split, genuine+impostor Hamming distributions, threshold at chosen FAR/FRR point, reported counts + limits) and freeze thresholds against it | 🔴 BUG-002 × BUG-003 | new `manage.py evaluate` or `scripts/evaluate.py` + a measured report in README; then pin/remove env knobs or hard-require them |
| P0-4 | **Bound the limiter** (evict idle/empty keys or move to Redis/DB) and document the multi-worker limitation | 🔴 BUG-004 | `views.py:50-66` |
| P0-5 | **Move Django off 5.0.x EOL** → 5.2 LTS pin (or ≥5.1 security superset) | 🟡 BUG-014 | `requirements.txt:1` + smoke tests (must re-run 61+11 after) |

### P1 — correctness and contract deviations

| # | Action | Finding(s) | Concrete change |
| --- | --- | --- | --- |
| P1-1 | Make student path default **1:1** (or clearly enroll "identification mode" as explicit product choice with FAR impact noted) | 🟡 BUG-006 | `views.py:483-501` |
| P1-2 | Unify rate-limit policy (one limiter config, consistent windows); remove `_rate_limited_checked` attribute hack in favor of a single clean gate | 🟡 BUG-007, BUG-008 | `views.py:448-456`, `views.py:518-523` + `camera.js:116`, `212-214` |
| P1-3 | Close configuration gaps: DEBUG default False, `SECURE_SSL_REDIRECT`/HSTS/proxy headers in the prod block | 🟡 BUG-009, BUG-010 | `settings.py:26`, `settings.py:45-50` |
| P1-4 | Scrub per-scan INFO logging of matched username and reason | 🟡 BUG-013 | `views.py:484` (TRD §7:107) |
| P1-5 | Explicitly gate/enforce "authorized enrollment" (register-open decision with an approved-workflow or counter-signing) | 🟡 BUG-015 | `views.py` register path + product decision |

### P2 — robustness and polish

| # | Action | Finding(s) |
| --- | --- | --- |
| P2-1 | Loud decision path on secondary-template drop (BUG-011) and enrollment-side image-quality gate (BUG-012) |
| P2-2 | Narrow `except` tuples in auth views (BUG-016); strict `ValueError` on corrupted shapes (BUG-018); explicit dtype contract for round-trips (BUG-019) |
| P2-3 | Remove `identify_user_from_iris` dead wrapper (BUG-020); delete unused `iris` file (BUG-024); rotate/scratch local `.env` secret (BUG-025) |
| P2-4 | Belt-and-brace: server-provided `redirect_url` origin whitelist (BUG-022); remove login-page placeholder usernames (BUG-021) |
| P2-5 | Realize a no-op then `select_for_update` on SQLite dev is documented; migration default `'gabor-v1'` → `'gabor-eye-crop-v2'` data migration or explicit legacy handling (BUG-017, BUG-023) |
| P2-6 | Throttle client uploads + memory-proof the 429 backoff to ≥ server cooldown (BUG-008 follow-on) |

### Sequencing suggestion

BUG-005 and BUG-001 can be closed the same day with 2-line-scale diffs and one repo cleanup. The evaluation track (P0-3) is a multi-day artifact — treat it as a separate work-stream because it gates the accuracy story, README §8 sections, NFR-08, and acceptance item 11 all at once.

---

## 7. Documentation & repo hygiene

### 7.1 Contract honesty (README/TRD interplay)

- **Credits:** home.html carries the no-accuracy/no-liveness disclaimer; README is honest about setup and known limitations; nothing anywhere claims 100% accuracy or liveness (TRD §8 item 7 and §7 item 8 both honored). TRD acknowledgement of "prototype, not production" is repeated in README.
- **Deltas:** README lacks an *evaluation* section and a *data-deletion* section (acceptance #12 ⚠ — dependent on the P0-3 artifact); no FAR/FRR/limitations table backed by measurement; `trd.md:41`'s "mask/shape/dtype" contract is brokered correctly by the template schema but the migration default drift (BUG-017) means DB-side truth subtly differs from code truth.
- **Leak surface (minor):** login-page placeholder (`templates/.../login.html`) visually advertises demo usernames `alice`/`bob` (BUG-021).

### 7.2 Repo hygiene

- ✅ Core hygiene is excellent: `.env` (real secret) and `db.sqlite3` are **untracked**; working tree clean; no real-person biometrics or populated auth-state committed; 47 tracked files all inspected; prototypes (.POC) clearly separated.
- 🟢 Stray 0-byte file `iris` at repo root (untracked) — delete (BUG-024).
- 🟢 The local `.env` contains a real-looking `DJANGO_SECRET_KEY` (BUG-025) — rotate on handoff, remedy in dev tooling so it can't leak by accident.

---

## 8. What an auditor wants to know at the end

**Can I ship this to more than myself/friends?**
Not yet, in current state: `synthetic_eye.png` (BUG-005), `X-Forwarded-For` (BUG-001), unmeasured thresholds (BUG-002/003), `select_for_update` (BUG-023), unbounded limiter (BUG-004), DEBUG-default-on (BUG-010) each is small to fix individually — but collectively they mean the trusted security contract that kept "iris = factor" safe (rate limiting + calibrated threshold + demo/real separation + fail-clean secrets) has four broken links in a five-link chain.

**Is the design rotten?**
No — the opposite. Evidence for an unusually careful core: decompression bombs blocked before decode, rate-limit precedes decode everywhere, server-only session grant, fail-closed every error path, backend-enforced staff/student separation, no CSRF/XSS holes, admin unable to tamper template bytes, honest disclaimers in the docs, config fail-closed on SECRET_KEY, and a 61-test Django suite that actually exercises the biometric pipeline (mask occlusion, gabor cache, reconstruction fidelity). The bug list is small (25 across a full repo) and dominated by *operational* defects, not architectural ones.

**Where is all the effort concentrated?**
Matching/persistence/reconstruction (models+`services.py`+`iris_extract.py` + tests) is solid; the soft points are *the edges*: trust of client-supplied identity lines, default-on eval-less thresholds, and cross-layer wiring hacks (AJAX flag). Fix those three edge classes and this becomes a defensible student project.

---

*End of AUDIT_REPORT.md. Full line-level detail for every finding lives in [`bugs.md`](bugs.md) — 25 findings: 🔴 5 · 🟡 10 · 🟢 10 — all Open unless marked Fixed; every claim above carries a file:line anchor in that ledger.*
