# Detection Improvement Plan — Before Changing Code

**Date:** 2026-11-09
**Status:** Plan only — no code changed yet
**Scope:** Client quality gating (#1) + Real-data recalibration & privacy (#3). DNN detector deferred.

## 1. Baseline (verified on 2026-11-09 debug images)

Source: `debug_captures/captures_log.jsonl` + `raw_image` recomputation, filtered to real `960x540` login frames (n=185).

| Metric | Before strict filter | After strict filter (current HEAD) |
|---|---|---|
| Face detected | 154/185 (83%) | 152/185 (82%) |
| 2 eyes detected | 126/185 (68%) | 119/185 (64%) |
| False-positive eye pairs (`iod/fw` outside 0.25–0.60, inside-face, symmetry) | 1 (0.53%) — ceiling-fan frame `2026-11-07T09:57:40` | 0/185 |
| Anatomical `iod/fw` median | 0.35–0.45 (correct range) | same, outliers rejected |
| Macro crop `synthetic_eye.png` | passes (1 eye, 279px) | passes |

Hybrid fusion baseline:
- `services.py:18` `FUSION_FACE_WEIGHT=0.20` (was 0.50 — caused genuine `fused 0.44 > 0.35`)
- Adaptive: `0.50` only when `face_distance <= 0.35`, else `0.20`
- Thresholds: `MATCH 0.32` (1:N, strict), `VERIFY 0.35` (1:1)
- `iris_extract.py:48-95` now uses CLAHE gray + wider ROI `10-65%` + `minNeighbors 3` + cached cascades

## 2. Change #1 — Client-side quality gate (no new deps)

**Problem:** `camera.js:182-328` POSTs every 1.2s even when blurry / eyes < 40px. Server spends ~460ms OpenCV per frame, then fails with `no_match`, exhausting rate budget (`views.py:663-676`, 60/60s AJAX).

**Change:**
- In `scanCurrentFrame()`, compute Laplacian variance on downscaled canvas (already on client canvas) + use `detection.eyes_boxes` from previous server response to estimate eye width.
- Skip `fetch` unless: blur metric > threshold AND (no prior detection OR last eye width >= 40px).
- Keep server checks in `services.py:193` (`eye width < 40` → "move closer") and `0.20 mask` as authoritative gate — client is UX only.

**Files:** `iris_auth_app/static/iris_auth_app/camera.js` only. No API change. `Retry-After` handling unchanged.

**Acceptance:** Live scan sends ≤ 30% fewer wasted frames on blurry motion; no new false accepts (thresholds unchanged); operator sees "Move closer" earlier.

**Risk / rollback:** Threshold too strict could block valid dim-but-ok frames. Mitigate: conservative initial blur threshold, log skipped frames to console, easy revert by removing gate.

## 3. Change #3 — Real-data recalibration + privacy

**Problem A (correctness):** `docs/EVALUATION_REPORT.md` uses synthetic polar textures (`evaluate.py:73-126`), not webcam frames. `FAR 0.00%` claim is unproven on real `debug_captures/`.

**Change:**
- Add `--real-captures` mode to `iris_auth_app/management/commands/evaluate.py` that loads consented labeled samples from `debug_captures/labeled_samples/` + `face_*_enrolled.jpg`, runs genuine (same user, different timestamp) vs impostor (different user) Hamming + facial fusion, sweeps thresholds.
- Keep synthetic mode as smoke test (`--quick`). Output new `docs/EVALUATION_REPORT_REAL.md` alongside existing report; do not overwrite until reviewed.
- Re-export `0.32/0.35` only if real FAR/FRR support them; otherwise adjust and note.

**Problem B (privacy):** `iris_auth_app/debug_logger.py:12` `ENABLE_LOGGING=True` by default saves raw BGR frames + eye crops + JSON with distances to `debug_captures/` on every login/register. TRD §7 forbids unnecessary biometric retention.

**Change:**
- Default `IRIS_ENABLE_IMAGE_LOGGING` to `DEBUG` only (`getattr(settings, 'IRIS_DEBUG', settings.DEBUG)`).
- Add TTL / `manage.py clean_debug_captures --days 7` (manual, no auto-delete without review).
- Ensure `tests.py` sets logging off so test synthetics stop polluting `debug_captures/` (currently 1136 log lines, mostly 80x80 test artifacts).

**Files:** `evaluate.py`, `debug_logger.py`, `iris_auth_project/settings.py` (new `IRIS_DEBUG` flag), tests.

**Acceptance:** Real-data report shows N genuine/impostor counts, FAR/FRR table, limitations. Prod (`DEBUG=False`) writes 0 raw images. Existing 77 Django + 11 pytest still pass.

## 4. Deferred (not in this change)

- DNN YuNet face detector to replace Haar — higher recall, needs model file + license review. Left as follow-up.
- Head-pose / liveness PAD — out of scope for academic demo per README disclaimer.

## 5. Sequencing & safety

1. Merge this doc.
2. Implement #1, manual test with webcam distance sweep (30cm / 60cm / 90cm).
3. Implement #3 privacy gate, verify `debug_captures/` untouched in prod mode.
4. Run real recalibration offline, review table before changing thresholds.
5. Re-run `verify_face_correctness` on post-change frames; expect face ≥82%, false-positive pairs = 0, matched rate ≥ baseline.

No thresholds or DB schema change until step 4 review. Rollback: revert single file per step.
