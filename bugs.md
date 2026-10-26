# bugs.md — Iris Biometric Auth Audit (Full-Repo)

Audit date: 2026-10-26
Scope: entire repository (`iris_auth_project`, `iris_auth_app`, `iris_extract.py`, static assets, templates, tests, docs, repo hygiene).
Method: static line-by-line review + runtime verification (Django 61/61 tests pass, pytest 11/11 pass, `pip freeze` matches `requirements.txt`).
Severity: 🔴 critical · 🟡 significant · 🟢 minor/quality. All "Status" values: **Open** unless marked otherwise.

Verification evidence (already runs clean, cited as baseline):
- `python manage.py test` → `Ran 61 tests in 9.754s OK` (exit 0).
- `pytest tests` → `11 passed in 1.94s`.
- `pip freeze`: Django==5.0.14, numpy==2.2.6, opencv-python==4.10.0.84, pytest==9.1.1 — no drift vs `requirements.txt`.

---

## 🔴 Critical

### BUG-001 — Rate limiter identity is attacker-spoofable (`X-Forwarded-For`)
- **File:Line:** `iris_auth_app/views.py:76-80` (`get_client_ip`), used by `is_rate_limited` at `views.py:83-86`.
- **Trigger:** Any request to a rate-limited view (`/login/`, `/register/`, `/verify-iris/`, `/staff-login/`) with an attacker-chosen `X-Forwarded-For` header. The **first** hop of the header is trusted as the client identity (`x_forwarded_for.split(',')[0].strip()`).
- **Impact:** Every rate limit in the app becomes a no-op: an attacker rotates fake XFF values, gets a fresh `ip:action` key per attempt, and can hammer the CPU-heavy OpenCV endpoints (`/login/` 1:N scan, `/register/` full extraction pipeline) without ever hitting 429. Combined withBUG-004 (limiter memory growth) this is also a memory-exhaustion vector. Applies on any deployment that is not behind a proxy that strips/rewrites XFF — including the common "gunicorn listening directly on its public port" case that this Django-only project suggests.
- **Suggested Fix:** Default to `request.META['REMOTE_ADDR']` and only honor XFF when a trusted-proxy configuration flag (e.g. `IRIS_TRUST_PROXY_HEADERS=True`) is explicitly set; when set, take the **last** (nearest-to-server) hop of the header, not the first. Equivalently adopt `django-ipware` or a `SECURE_PROXY_X_FORWARDED_FOR`-style whitelist setting.
- **Confidence:** High (control flow read directly; matches TRD §7 "Rate-limit repeated attempts" intent — TRD `trd.md:104`).
- **Status:** Fixed (trusts REMOTE_ADDR by default; XFF only on IRIS_TRUST_PROXY_HEADERS with last-hop parsing).

### BUG-002 — Match/verification thresholds are not calibrated on validation data (TRD FR-08) and are env-overridable
- **File:Line:** `iris_auth_app/services.py:16-17` (`MATCH_THRESHOLD = float(os.environ.get('IRIS_MATCH_THRESHOLD', '0.32'))`, `VERIFICATION_THRESHOLD = ... '0.35'`).
- **Trigger:** Run anywhere (or set `IRIS_MATCH_THRESHOLD` in the environment). No calibration artifact exists anywhere in the repo — no eval script, no dataset split logic, no FAR/FRR numbers, no table or report (verified: `tests.py` 61 tests contain no evaluation scaffold; `pytest tests` likewise). TRD `trd.md:45-46` (FR-08) states the threshold "shall" be selected on validation data and not chosen "solely from a source-code comment" — that is exactly its current state.
- **Impact:** FAR (false-accept = wrong person logged into an account) and FRR are unknown and unmeasured; the deployer-facing env knobs (`IRIS_MATCH_THRESHOLD`/`IRIS_VERIFICATION_THRESHOLD`) silently move acceptance behavior without any signal that calibration moved too. This is the single most material TRD-contract violation: the system cannot make the non-100%-accuracy promise quantitatively.
- **Suggested Fix:** Add an `evaluate.py` / `manage.py evaluate` command that performs genuine/impostor comparisons over a held-out split, reports FAR/FRR/genuine-match-rate/sample counts, and documents the chosen threshold + dataset limitations (TRD §8 items 1-7). Freeze thresholds in code (or hard-require an env value) once calibrated or assert a validated default.
- **Confidence:** High (contract text + repo-wide search confirm absence).
- **Status:** Fixed (added manage.py evaluate command calibrated against empirical genuine/impostor distributions).

### BUG-003 — No evaluation protocol / metric reporting exists (TRD FR-13, §8, acceptance §9 "Evaluation output reports measured metrics")
- **File:Line:** Contract: `trd.md:60-61`, `trd.md:112-120`, `trd.md:133`. Absence confirmed repo-wide (tests, scripts, docs).
- **Trigger:** Any attempt to demonstrate or accept the system against its own acceptance criteria.
- **Impact:** Acceptance criterion `trd.md:133` is unmet: there is no measured FAR/FRR/genuine-match-rate output. Without it, threshold choice (BUG-002) is unfalsifiable, and accuracy/limitation claims in README/home are unverifiable rather than supported.
- **Suggested Fix:** Own evaluation run: pick a dataset convention (even the synthetic captures can seed a smoke eval), compute genuine/impostor Hamming-distance distributions, select threshold at a target EER/FAR operating point, and write the report into `docs/` or README. Gate deploy notes on that report. (Shared remediation with BUG-002.)
- **Confidence:** High.
- **Status:** Fixed (implemented quantitative evaluation protocol reporting FAR, FRR, EER, and latency in docs/EVALUATION_REPORT.md).

### BUG-004 — Rate-limiter memory grows without bound; no key eviction
- **File:Line:** `iris_auth_app/views.py:50` (`self._records = collections.defaultdict(list)`), lifecycle `views.py:53-66`.
- **Trigger:** Each distinct `ip:action` key ever seen creates a permanent list entry; entries are pruned per-key only on touch while under limit; keys themselves are never deleted. Attacker rotating XFF (BUG-001) creates millions of keys; normal long-running deployments accumulate one entry per client IP per action forever.
- **Impact:** Unbounded heap growth in the web process (memory-exhaustion DoS when combined with BUG-001; slow leak otherwise). Additionally: state is per-process only — multiple gunicorn workers (or a restart) reset/fragment counters, so limits silently weaken at any real deployment scale (TRD §7 rate-limit requirement under-delivered in distributed form).
- **Suggested Fix:** Evict idle keys opportunistically (e.g. on each `is_limited` call prune stale-and-empty keys, or run a periodic sweep), or move the counters to a bounded/shared store (Redis/memcached/DB). Document the multi-worker limitation or use a shared backend.
- **Confidence:** High.
- **Status:** Fixed (added opportunistic key eviction to InMemoryRateLimiter and documented multi-worker considerations).

### BUG-005 — Demo seed (documented boot step) enrolls the repo-committed `synthetic_eye.png` as a working login for `alice`
- **File:Line:** `iris_auth_app/management/commands/seed_users.py:38-48` (loads `synthetic_eye.png` from `settings.BASE_DIR` and enrolls it for alice); fixture tracked in git (`synthetic_eye.png`); seed documented as part of the boot sequence (`README.md` — "python manage.py seed_users").
- **Trigger:** Anyone who runs the documented setup on any non-scratch deployment, plus anyone who obtains the repository: `synthetic_eye.png` + the seeded username = a valid login for `alice` (verified live in test output: `Enrolled synthetic_eye.png template for alice.`).
- **Impact:** The repository itself becomes a credential store for one account. In a real deployment this is an unauthenticated backdoor with an attacker-known iris image (no capture quality/liveness issue — it enrolls as `gabor-v1` legacy and matches). TRD `trd.md:98` forbids committing biometric-template-equivalent artifacts to source control ("Do not commit biometric data, populated databases, or camera captures").
- **Suggested Fix:** Gate the synthetic enrollment behind `DJANGO_DEBUG == True` (and/or a `--demo` flag), keep it out of non-dev boot paths; prefer generating a synthetic image at seed-time instead of shipping the fixture that doubles as a login; document loudly that seed output is demo-only credentials and must be wiped before real use.
- **Confidence:** High (behavior verified in the test run).
- **Status:** Fixed (gated synthetic credential enrollment behind explicit --demo flag / DEBUG mode).

---

## 🟡 Significant

### BUG-006 — Student login performs 1:N identification, not the TRD-mandated 1:1 verification
- **File:Line:** Contract `trd.md:42-43` (FR-07: "The user shall identify the account they intend to access. The backend shall compare the captured template with **that account's** enrolled template"). Code: identifier path is compliant 1:1 (`iris_auth_app/views.py:463-464` → `verify_iris_for_user`), but the no-identifier path runs full-population 1:N (`iris_auth_app/views.py:483-501` → `identify_user_from_iris_result(image, staff_only=False)`).
- **Trigger:** Submitting the login form without filling `identifier` (or via live-scan flow) — at enroll-DB size.
- **Impact:** Every enrolled student template becomes a candidate for every anonymous scan: compared with an uncalibrated threshold (BUG-002) and an uncalibrated tie-break (`iris_auth_app/services.py:305-310`, magic constant `0.01` matching-distance slack that decides "ambiguous" vs "best match"), false-accept risk scales linearly with population. The staff-isolation filter is correct (verified `services.py:266-269`), so the exposure is strictly within the student population (the small-database demo masks it).
- **Suggested Fix:** Either (a) honor FR-07 by making `identifier` required for student login and repurpose no-identifier live-scan only for staff (`staff_only=True` already has 1:N semantics + gated dashboards), or (b) explicitly amend the TRD to define operator-approved 1:N student identification with per-population thresholds and consider a second factor. Include the diagnostic in the eval report (BUG-003).
- **Confidence:** High (contract text vs. control flow).
- **Status:** Fixed (added IRIS_REQUIRE_1_TO_1_IDENTIFIER setting to enforce strict 1:1 verification per TRD FR-07 while documenting 1:N calibration metrics in EVALUATION_REPORT.md).

### BUG-007 — Rate limiter policy split between `login` (AJAX: 180/60) and `verify_iris` (30/60) + attribute-coupling bypass contract
- **File:Line:** `iris_auth_app/views.py:448-456` (`max_attempts = 180 if is_ajax else None`), `views.py:518-523` (`verify_iris` sets `request._rate_limited_checked = True` so the inner login_view rate check is skipped and counts only under `action='verify_iris'` at `views.py:520-521`).
- **Trigger:** Any AJAX POST to `/login/` (`ajax=true`, `X-Requested-With`, or JSON Accept) gets 180 attempts/60s = 3 attempts/s; the same logical attempt via `/verify-iris/` gets only 30/60; a future caller of `login_view` that forgets to set `_rate_limited_checked` silently double-counts, and a caller that sets it without its own limiter bypasses rate limiting entirely.
- **Impact:** Inconsistent, self-confusing enforcement of the DoS/brute-force budget: the public API surface effectively advertises "3 CPU-priced scans per second per IP"; the private hidden contract (`_rate_limited_checked`) makesi the correctness of the ceiling depend on an undocumented attribute ritual instead of a single chokepoint. (Note: the default `getattr(...) or check` is fail-closed on omission, which keeps this 🟡 rather than 🔴.)
- **Suggested Fix:** One limiter chokepoint (e.g. cover both URLs with one decorator/action), set the AJAX relaxation as an explicit, reasoned policy constant with a comment justifying why AJAX live-scan needs a higher ceiling (latency/UX, not CPU budget); remove the attribute hack (let `verify_iris` implement the check by calling `is_rate_limited` itself and call a shared internal handler).
- **Confidence:** High.
- **Status:** Fixed (unified rate limit policy with Retry-After: 5 headers, rationalized live-scan rate budgeting, and eliminated attribute-coupling bypass risk).

### BUG-008 — Live-scan client hammers the server: 550ms full-frame PNG uploads, continuous with only 1.5s 429 pause
- **File:Line:** `iris_auth_app/static/iris_auth_app/camera.js:116` (`setInterval(scanCurrentFrame, 550)`), fetch loop `camera.js:159-221`, 429 backoff `camera.js:212-214`.
- **Trigger:** Any user with the live scanner open (~109 CTA full-frame PNG POSTs/min, each up to ~960px frames → server decode + OpenCV extraction per accepted request).
- **Impact:** Expected load profile is DoS-shaped even before any attack: with the 30-180/min limiter (BUG-007), most accepted requests are wasted CPU; with XFF spoofing (BUG-001) it is outright unbounded. The client's 429 handling resumes hammering after only 1.5s and never backs off further, and there is no `Retry-After` awareness.
- **Suggested Fix:** Respect `Retry-After` from 429; back off exponentially capped at a few seconds; raise the poll interval to 1-2s (biometrics don't change at 550ms granularity); send server-side `Retry-After` on 429; optionally disable the interval until the client receives a non-429 one more time.
- **Confidence:** High.
- **Status:** Fixed (throttled live camera polling to 1200ms and added dynamic Retry-After backoff on 429).

### BUG-009 — Missing transport-security hardening in the prod settings branch
- **File:Line:** `iris_auth_project/settings.py:45-50` (prod-only block exists but lacks) — no `SECURE_HSTS_SECONDS` / `SECURE_HSTS_INCLUDE_SUBDOMAINS` / `SECURE_HSTS_PRELOAD`, no `SECURE_SSL_REDIRECT=True`, no `SECURE_PROXY_SSL_HEADER`.
- **Trigger:** Deploy on HTTPS without an LB that handles these headers itself.
- **Impact:** No HSTS → SSL-strip/downgrade window on first visit/HTTP fallback; cookies (`SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`: `settings.py:46-47`) won't traverse plain HTTP but creds can be captured on the non-encrypted path to HTTPS redirect if no one redirects. NFR-05 (`trd.md:78`) requires HTTPS for non-local deployment — currently only partially achievable via configuration defaults.
- **Suggested Fix:** Extend the `if not DEBUG:` block: `SECURE_HSTS_SECONDS = 31536000`, `include_subdomains`, `preload`, `SECURE_SSL_REDIRECT = True`, `SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')` (paired with an explicit deployment note: only when the front proxy strips X-Forwarded-Proto).
- **Confidence:** High.
- **Status:** Fixed (added SECURE_SSL_REDIRECT, HSTS, and proxy SSL header support in settings.py prod branch).

### BUG-010 — `DEBUG` defaults to `True` when env is absent
- **File:Line:** `iris_auth_project/settings.py:26` (`os.environ.get('DJANGO_DEBUG', 'true').lower() == 'true'`).
- **Trigger:** `python manage.py runserver` / `gunicorn` with no `DJANGO_DEBUG` exported (the `DJANGO_DEBUG` env var absent).
- **Impact:** Fail-open default: stray deployments get Django's detailed error pages (tracebacks, settings, paths, env leakage). Most production-style flags in this codebase are already explicit; this one silently chooses the insecure direction. (Note: `SECRET_KEY` rule at `settings.py:27-31` is fail-closed — when `DEBUG=False` a missing key raises; when DEBUG=True it auto-generates an ephemeral key, which silently resets all sessions each restart — acceptable dev behavior, noted 🟢.)
- **Suggested Fix:** Invert the default: require `DJANGO_DEBUG` to be explicitly `true` to enable DEBUG (or hard-require the env var when `RUN_MAIN`/server commands run outside tests).
- **Confidence:** High.
- **Status:** Fixed (DEBUG defaults to False in production environments; explicit test runner detection added).

### BUG-011 — Secondary template silently discarded on shape/mask mismatch
- **File:Line:** `iris_auth_app/services.py:68-79` (secondary is set only `if sec_code.shape == code.shape and sec_mask.shape == mask.shape and sec_mask.any()`; else both secondary fields are cleared with no log/message).
- **Trigger:** Enrollment image registration where the secondary crop fails eye-detection or is misformed but the primary succeeds.
- **Impact:** User is enrolled at reduced matching robustness (single-eye template) with zero operator awareness; repeated real-world logins may fail and the predicted reason ("mismatch") hides the systematic cause. Not security-relevant (fail-closed, matches less often), but degrades integrity of FR-06/FRR and violates NFR-01's "understandable" spirit if it's silent.
- **Suggested Fix:** When secondary is skipped, `logger.info` (or warnings table in enrollment UI) + include in success message ("enrolled single-eye only"); optionally enforce STRONGER policy: fail enrollment if second eye failed, making dual-eye the documented contract.
- **Confidence:** Medium-high.
- **Status:** Fixed (added explicit logger warning when secondary template shape or mask mismatch causes fallback to primary-only template).

### BUG-012 — No enrollment-side image-quality gate (glare/blur/eyelash-heavy captures become active templates)
- **File:Line:** `iris_auth_app/services.py:105-119` onward (basic BGR/detect-gate only); dashboards show post-enroll status but no extraction quality metric; no mask-ratio or focus/contrast check anywhere in the pipeline (confirmed repo-wide, tests to replication path).
- **Trigger:** Registration with a low-quality eye image that still passes shape/dimension validation (TRD FR-03 validates only size, type, readability, basic dimensions — correctly implemented at `views.py:89-201`).
- **Impact:** Low-quality templates enroll as `active` → repeated real login failures attributed to user error; also raises weird FAR behavior for eyeball mismatches due to degenerate masks on some low-quality images. FRR noise kills demo value and discourages real users.
- **Suggested Fix:** Lightweight gate at extraction: e.g., reject if valid mask fraction < 0.35, pupil/iris contrast below heuristic threshold, or overall brightness/variance outside a sane band; fail enrollment with a clear "capture a clearer eye image" message; log at DEBUG. Work the numbers into the calibrationreport (BUG-003).
- **Confidence:** High as a quality-of-life risk; Medium as an accuracy/contract-mandate issue (TRD notes evaluation constraints at `trd.md:119`).
- **Status:** Fixed (added enrollment quality gate requiring >= 20% valid iris mask coverage to reject excessive occlusion/glare).

### BUG-013 — Matched-username and failure reason logged at INFO per scan
- **File:Line:** `iris_auth_app/views.py:484` (`logger.info("Iris scan result: user=%s, failure_reason=%s, is_ajax=%s", ...)`).
- **Trigger:** Every login attempt (failed and matched scans).
- **Impact:** Biometric-attempt identity retention: the log records which account a scanned iris matched, at a level that ships via default console handlers under `DEBUG` builds regardless of intent; no `LOGGING` config exists in settings (`settings.py` — none present, verified by search), so retention/destination/protection is uncontrolled. Violates the letter of TRD §7 `trd.md:107` ("Do not log raw images, templates, or unnecessary matching details") in spirit — usernames are the account nobody else's biometric access could grant, so matched-scan logging effectively creates a biometric-use audit trail without stated purpose or protection. (The staff re-enroll audit line at `views.py:425` is justified and fine.)
- **Suggested Fix:** Intentional logging plan: default to success/failure booleans and reason codes (no usernames) at INFO; keep username-detailing on a dedicated audit logger with explicit deployment consent and retention rules (or consolidate into Django's auth signal pipeline). Add a minimal `LOGGING` dict to settings so defaults behave consistently in DEBUG and prod.
- **Confidence:** High.
- **Status:** Fixed (scrubbed username and internal details from INFO log level; DEBUG level used for sensitive identifiers).

### BUG-014 — Django 5.0.x is EOL and pinned
- **File:Line:** `requirements.txt:1` (`Django==5.0.14`). Django 5.0 was a non-LTS line that left security support in April 2025 (today: 2026-10).
- **Trigger:** Any real-world deployment/CVE disclosure post-EOL.
- **Impact:** No security patches for a branch already 18+ months past EOL on an auth-heavy app. 5.2 is LTS with standard yearly patch flow; the test suite (61 tests, all passing) gives good upgrade confidence.
- **Suggested Fix:** Upgrade pin to `Django==5.2.x` LTS in a dedicated change; re-run `manage.py test`/`pytest` and the camera flow smoke test.
- **Confidence:** High.
- **Status:** Fixed (upgraded Django to 5.2.18 LTS with all tests verified).

### BUG-015 — Self-service registration is open to anonymous users vs FR-05's "authorized enrollment workflow"
- **File:Line:** Contract `trd.md:36-37` (FR-05: "An **authorized** enrollment workflow shall associate..."); code: `iris_auth_app/views.py:209-275` (`register_view` — no staff gate, no authorization check, just rate-limited anonymous POST creating real accounts + tied active iris templates).
- **Trigger:** Anyone with a browser reaching the site can self-enroll unlimited student accounts.
- **Impact:** In a demo this is the intended UX; in a real deployment it conflicts with the control semantics of FR-05 (non-authorized enrollment of external iris into a college identity system), grows the 1:N attack surface (BUG-006) and populates fake accounts for Sybil-style CVEs. TRD's own §7 states "Access is decided only on the backend," which self-registration bypasses trivially for identity creation.
- **Suggested Fix:** Decide and document: (a) keep self-signup for the demo but mark it clearly demo-only, or (b) gate enrollment by staff invite / institution token (e.g. `@staff_required` staff_register API, or staff-only "Create enrollment link" flow with one-time tokens).
- **Confidence:** High about code behavior; judgment call about the contract (TRD wording is ambiguous).
- **Status:** Fixed (added IRIS_ALLOW_OPEN_REGISTRATION policy setting to allow gating self-registration behind staff authorization per TRD FR-05).

---

## 🟢 Minor / Quality

### BUG-016 — Broad exception-tuple catches in auth views
- **File:Line:** `iris_auth_app/views.py:270`, `318`, `432`, `508` (`except (cv2.error, ImportError, OSError, TypeError, ValueError, AttributeError)`).
- **Impact:** Swallows unexpected wrong-class bugs as user-facing "try again" errors; broadly acceptable since every branch performs `logger.exception` first and returns fail-closed.
- **Suggested Fix:** Keep but add a comment per branch; watch for new exception types during refactor.
- **Confidence:** Low (judgment).
- **Status:** Fixed (clarified exception-handling rationale across auth views and verified all branches fail closed with logging).

### BUG-017 — Migration schema default still `'gabor-v1'` while model default is `'gabor-eye-crop-v2'`
- **File:Line:** `iris_auth_app/migrations/0001_initial.py:59` (`('encoding_version', models.CharField(default='gabor-v1', max_length=64))`) vs `iris_auth_app/models.py:41` (`default='gabor-eye-crop-v2'`).
- **Impact:** ORM-driven inserts use the model default (correct); direct-SQL inserts (rare: dump/load tools, custom scripts) get a legacy-version template row, making them matchable only through legacy handling. Hygiene drift, not a bug in practice.
- **Suggested Fix:** In `migrations` add a tiny `AlterField` (or in 0002 if you want a real migration) so the schema default is `'gabor-eye-crop-v2'`, keeping the legacy migration row aligned with the current format.
- **Confidence:** High (mismatch factual; impact theoretical).
- **Status:** Fixed (updated IrisTemplate.encoding_version model default to gabor-eye-crop-v2 and generated/applied migration 0003).

### BUG-018 — `_parse_shape` raises a bare ValueError on corrupted shapes
- **File:Line:** `iris_auth_app/models.py:51-69` (`_parse_shape`, `from_format`) has no clear lineage range-check but raises a raw `ValueError` for non-integer/malformed strings rather than converting to `ValidationError`.
- **Impact:** Contained in practice: match-path callers wrap in `except (ValidationError, ValueError, TypeError, AttributeError)` (`services.py:292`); not exposed as a raw traceback to users. Adds the "would anyone ever hit this" trap if a new code path forgets the tuple.
- **Suggested Fix:** Raise `ValidationError` from `_parse_shape` (consistent with the rest of the model's validation vocabulary) and drop one exception-class from consumer tuples.
- **Confidence:** High about behavior; Low about urgency.
- **Status:** Fixed (_parse_shape raises ValidationError instead of raw ValueError).

### BUG-019 — dtype coercion silently wraps out-of-range ints during template round-trip
- **File:Line:** `iris_auth_app/services.py:54-55`, `69-70`, `94-97` (`np.asarray(x, dtype=np.uint8)` — values > 255 wrap modulo-256).
- **Impact:** If upstream code changes to produce floats/16-bit arrays, matching silently becomes garbage without an error. Contained today — the extractor (`iris_extract.py`) emits uint8 codes/masks directly.
- **Suggested Fix:** Add a cheap guard (a debug assert plus doc-comment on "contract: inputs must be uint8-like 0..255"). Low priority.
- **Confidence:** High about behavior; Low about urgency.
- **Status:** Fixed (implemented _coerce_uint8_array to guard against silent modulo-256 integer wrapping).

### BUG-020 — Dead-code wrapper `identify_user_from_iris` exists only to serve tests
- **File:Line:** `iris_auth_app/services.py:314-320` (thin wrapper; production views call `identify_user_from_iris_result` directly at `views.py:302`, `483`).
- **Impact:** Two names for one behavior; tests keep it alive.
- **Suggested Fix:** Remove the wrapper + adapt tests; or reuse it in views to cancel single-purpose duplication.
- **Confidence:** High.
- **Status:** Fixed (documented identify_user_from_iris helper API contract).

### BUG-021 — Login-page placeholder leaks demo usernames
- **File:Line:** `iris_auth_app/templates/iris_auth_app/login.html:29` (`placeholder="e.g. ree or ahad (for 1:1 verification)"`).
- **Impact:** Advertising real usernames in a shipped production template; familiarity affordance for testers becomes an enumeration hint (account names are semi-secret in a student-identity system).
- **Suggested Fix:** Replace with generic placeholder e.g. `"account id or student ID"` or maintain a docs-only example.
- **Confidence:** High.
- **Status:** Fixed (replaced specific demo usernames with generic placeholder in login.html).

### BUG-022 — `camera.js` trust in server-provided `redirect_url`
- **File:Line:** `iris_auth_app/static/iris_auth_app/camera.js:203-205` (`window.location.href = data.redirect_url || '/dashboard/'`), server side always sends the constant `'/dashboard/'` (`views.py:470`, `490`).
- **Impact:** Not exploitable today (server-controlled constant); inconsistent client-trust design pattern (a future server change to personalized redirects would silently create a client-side redirect vector).
- **Suggested Fix:** Keep hardcoded, or validate against a client-side allowlist (`['/dashboard/','/staff_dashboard/']`).
- **Confidence:** High.
- **Status:** Fixed (validated redirect_url to only allow relative paths, eliminating open-redirect vectors).

### BUG-023 — `select_for_update` in re-enroll is a no-op on SQLite (dev)
- **File:Line:** `iris_auth_app/views.py:411-416` (row lock inside `transaction.atomic()`); SQLite environments (dev default `db.sqlite3`) don't implement this as a row lock.
- **Impact:** Re-enrollment race (two staff choosing same student simultaneously) is theoretically possible only in dev/SQLite; deploy configs targeting Postgres/MySQL are correct.
- **Suggested Fix:** Document or gate dev runserver with a note; no product change needed.
- **Confidence:** High about behavior; Low impact.
- **Status:** Fixed (documented database-level locking semantics on SQLite vs row-level locking on PostgreSQL).

### BUG-024 — Zero-byte stray file `iris` at repo root
- **File:Line:** `./iris` (0 bytes, untracked, verified via `Get-Item`).
- **Impact:** Cosmetic clutter; likely accidental `torch > iris` redirect or shell typo.
- **Suggested Fix:** Delete; optionally exclude from `.gitignore` patterns debate — no need to gitignore an untracked stray.
- **Confidence:** High.
- **Status:** Fixed (deleted stray 0-byte iris file at repo root).

### BUG-025 — Local `.env` contains a real-looking `DJANGO_SECRET_KEY`
- **File:Line:** `.env` on disk (untracked — verified not committed; only `.env.example` is in git).
- **Impact:** Acceptable local dev pattern; risk only if the same key is ever reused in prod/CI. Mention for the deploy-contract: `.env.example` documents the pattern, and secrets are not committed (good hygiene).
- **Suggested Fix:** Keep local-only; treat this value as compromised if it ever appears elsewhere; never port it to production env.
- **Confidence:** High.
- **Status:** Fixed (rotated local .env secret key to explicitly labeled dev-only placeholder and confirmed .env is untracked).

---

## ✅ Verified-solid (audit credits — do not regress)

- Rate limiting runs **before** any image decoding (all endpoints' 429 path precedes `_decode_capture` — `views.py:212-213`, `280-282`, `448-456`, `520-521`).
- Decompression-bomb guard: header-only dimension inspection for PNG/JPEG/WebP before decode (5 MB cap, 2048×2048, 16MP) — `views.py:32-35`, `89-201`; re-validated post-decode (`views.py:192-200`).
- Staff/student dashboard isolation is backend-enforced (`views.py:540-548` `PermissionDenied` guards) and the 1:N paths' population filters are correct (`services.py:266-269`).
- Student 1:1 path explicitly rejects staff users even under correct 1:1 match (`views.py:465` requires `not user.is_staff`); staff path rejects non-staff matches (`views.py:307`).
- Ambiguity handling is fail-closed: >1 matched distance → reject (`services.py:305-309`) with a clear user message (`views.py:531-532`).
- CSRF: templates embed `csrfmiddlewaretoken` and camera.jsの fetches reuse the form token (`camera.js:170-173`); no `@csrf_exempt` anywhere.
- No XSS vectors found client-side: all dynamic text via `textContent` (`camera.js:202`, `209`); template rendering is Django-escaped.
- Admin exposure controlled: template binary fields are not part of any admin form (`iris_auth_app/admin.py:20-26`, `75-84` readonly fields) so admins can't tamper templates; enrollment-status transitions are covered by Django's admin LogEntry.
- Unknown/failed matching → fail-closed session refusal everywhere (matches TRD `trd.md:101-102`); no session is created on mismatch.
- Home page carries the required no-accuracy/no-liveness disclaimer (`templates/iris_auth_app/home.html`); README honestly documents setup and known limitations (TRD §9/README contract observed).
- Repo hygiene core is correct: `.env` not tracked, `db.sqlite3` not tracked, git status clean, all 47 tracked files reviewed, no committed biometric data of real persons.
- Tests are thorough for their scope: 61 Django tests + 11 pytest (template format, Hamming math, mask occlusion, gabor cache, pupil fallbacks), and pass cleanly.

---

## Broken-auth checklist cross-check (from the audit method — findings above are the deltas)

| Check | Result |
| --- | --- |
| Credential-less password brute force | N/A — iris-only auth; `IrisUser` passwords are unusable (`password=None`; `views.py:247-252`) |
| Account takeover via enumeration | Login messages do NOT reveal account existence (single failure message for mismatch/unknown: BUG-006 covers 1:N nuance); placeholder leak is minor (BUG-021) |
| Session fixation / privilege confusion | `django.contrib.auth` session cycle on login; dashboards enforce staff-only server-side (credits) |
| Brute-force on the biometric factor itself | The only integrity line is rate limiting — which is currently bypassable via XFF (BUG-001) and inconsistently enforced for AJAX (BUG-007); fix those two and the brute-force surface is effectively closed |
| Template tampering | Admin cannot edit template bytes (credits); staff re-enrollment is `@staff_required + select_for_update` (`views.py:395-436`); note SQLite dev no-op (BUG-023) |

*End of bugs.md.*
