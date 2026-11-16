# Login Fix & System Audit Report

**Date:** 2026-11-16
**Scope:** `iris-login` login/registration/runtime path, plus reuse review of
`FathimaReeha26/face-detection-`.
**Upstream:** includes merge of `7c183fc` ("Staff: add attendance editing
dashboard for student records") from `origin/main` before pushing.

## 1. Why login was failing

| # | Finding | Severity | Root cause |
|---|---|---|---|
| 1 | The seeded staff demo account could never log in | High | `staff_alice` was created with no iris template, and staff login is iris-only. |
| 2 | A fresh database gave a dead-end login experience | High | With zero enrolled templates the page only said "Iris not recognized"; there was no prompt to register, and the live scanner retried forever. |
| 3 | Normal phone photos were rejected | High | `_decode_capture` hard-rejected anything wider/taller than 2048 px, even though the pixel cap was 16 MP. A 3000x2000 or 4032x3024 photo failed before matching. |
| 4 | `.env` was only loaded by `manage.py` | Medium | WSGI/ASGI entry points ignored the documented `.env` file, so production/ASGI runs failed on `DJANGO_SECRET_KEY` or started with the wrong `DEBUG` value. |
| 5 | The missing-env error was unhelpful | Low | It only said "Set DJANGO_SECRET_KEY"; it did not say to copy `.env.example` or enable `DJANGO_DEBUG` for local work. |
| 6 | Haar-only eye localization was fragile | Medium | Glasses, head tilt, hijab/occlusion and webcam perspective often produced no eye box, so matching never ran. |
| 7 | The legacy facial descriptor could dominate matching | Medium | When the 259-D periocular distance was <= 0.35, it received 85% of the score. This was tuned on synthetic data and is weak evidence. |
| 8 | Re-enrollment could retain stale face features | Low | `ensure_iris_template_for_user` left old facial features in place when a new capture had none. |
| 9 | `IrisTemplate.create_for_user` default encoding drifted | Low | It defaulted to `gabor-v1` while the model default is `gabor-eye-crop-v2`. |
| 10 | Demo accounts had usable passwords | Low | The portal is iris-only, but seeded staff had a known password usable for Django admin. |
| 11 | Haar cascade XML was reloaded on every detection | Low | Four cascade files were constructed per call; live scanning paid that cost repeatedly. |

## 2. What changed

### Login and onboarding
- `seed_users --demo` now enrolls **both** `alice` (student) and `staff_alice`
  (staff) with `synthetic_eye.png`, and prints exact demo-login instructions.
- `/login/` and `/staff/login/` show an actionable banner when no compatible
  templates exist.
- AJAX scans receive `{"status": "no_templates", ...}` instead of a generic
  retry. `camera.js` stops the live scanner and shows a **Register your iris**
  link (student portal).
- Demo accounts are created with unusable passwords; use
  `python manage.py createsuperuser` for `/admin/`.

### Image handling
- Upload cap: **8 MB**, header cap **20 MP**, max edge **8192 px**.
- Images larger than **1600 px** on the longest edge are downscaled with
  `INTER_AREA` before detection, so ordinary phone photos (3000x2000,
  4032x3024) work without weakening the decompression-bomb guard.
- Existing oversized/corrupt image tests still fail closed.

### Environment
- New `iris_auth_project/env.py` loads `.env` once for `manage.py`, WSGI and
  ASGI. Real environment variables still take precedence.
- Missing-key error now explains the `.env.example` copy and `DJANGO_DEBUG`.

### Detection / matching
- Reused the MIT-licensed OpenCV Zoo models from `FathimaReeha26/face-detection-`:
  - `models/face_detection_yunet_2023mar.onnx` (233 KB)
  - `models/face_recognition_sface_2021dec.onnx` (37 MB)
- YuNet is now the preferred face detector. Its five landmarks produce eye
  ROIs, with the existing Haar cascades retained as the macro/close-up
  fallback.
- SFace produces a 128-D face embedding at enrollment and login.
- For **1:1** logins, if iris distance is above `0.35` but <= `0.46`, and SFace
  cosine similarity is >= `0.60`, the login is accepted on combined evidence.
  The 1:N path remains iris-only and fail-closed.
- If SFace models are absent, the app falls back to the previous iris/facial
  pipeline automatically.
- Cascade loading is cached; YuNet inference is locked for thread safety.

### Data model
- Added `IrisTemplate.face_embedding` (nullable binary), migration
  `0006_iristemplate_face_embedding`.
- Re-enrollment clears stale `facial_features` / `face_embedding`.
- `IrisTemplate.create_for_user` now defaults to `gabor-eye-crop-v2`.

## 3. Verification

| Check | Result |
|---|---|
| `python manage.py check` | 0 issues |
| `python manage.py test` | **89 tests, OK** |
| `pytest tests` | **11 passed** |
| `python manage.py makemigrations --check --dry-run` | No changes detected |
| `python manage.py migrate --check` | No pending migrations |
| `python manage.py check --deploy` with `DJANGO_DEBUG=false` + strong key | 0 issues |
| WSGI import with no env exported | `.env` loaded, `settings.DEBUG=True` |
| `manage.py check` with `.env` removed | Clear `ImproperlyConfigured` message |
| Playwright: student file-upload login | `/dashboard/` |
| Playwright: student large 3000x2000 photo | `/dashboard/` |
| Playwright: staff file-upload login | `/staff/dashboard/` |
| Playwright: student live fake-camera login | `/dashboard/` |
| Playwright: staff live fake-camera login | `/staff/dashboard/` |
| Duplicate/stale template check | `makemigrations --check` clean |

### Face-assist validation (local images, not committed)

A temporary enrollment was created from a face photo and verified against transformed
captures of the same face. The transaction was rolled back afterward.

| Capture | Iris distance | SFace similarity | Decision |
|---|---|---|---|
| Same image | 0.0000 | 1.000 | accepted (iris) |
| Darker exposure | 0.1541 | 0.990 | accepted (iris) |
| Slight blur | 0.1972 | 0.976 | accepted (iris) |
| Added sensor noise | 0.4067 | 0.966 | **accepted via face rescue** |
| Strong brightness shift | 0.4851 | 0.992 | rejected (outside 0.46 rescue bound) |
| Different person/photo | 0.4905 | 0.328 | rejected |

This confirms the rescue rule helps a genuine marginal capture without
accepting a different face.

## 4. What was reused from the face repo

- YuNet detector loading through `cv2.FaceDetectorYN`.
- SFace alignment via the 15-value YuNet landmark row and
  `cv2.FaceRecognizerSF`.
- Cosine similarity matching via `FaceRecognizerSF_FR_COSINE`.
- The 5-point landmark layout and eye-ROI idea.

Reviewed but **not** integrated:
- SCRFD/RetinaFace GPU backends (need `onnxruntime-gpu`, 17 MB+ SCRFD weights,
  non-commercial research weights).
- MediaPipe blink/head-movement liveness and FFT screen-replay heuristic
  (needs `mediapipe`, a 3.7 MB landmark model, and a multi-frame session).
- The MiniFASNet anti-spoof path (weights are not shipped).

## 5. Remaining risks / recommendations

1. **No liveness/PAD.** A photo or replay can still match. The face repo's
   blink/head-movement check is a useful next step but is heuristic only.
2. **1:N student login remains enabled by default.** Set
   `IRIS_REQUIRE_1_TO_1_IDENTIFIER=true` for a stricter 1:1 deployment.
3. **Face assist is a rescue, not a factor replacement.** Iris is still
   required within 0.46; tune `IRIS_FACE_ASSIST_*` against real captures.
4. **Real-world FAR/FRR are unmeasured.** The evaluation report uses synthetic
   iris textures. Collect consented, separate-split captures before making
   accuracy claims.
5. **Phone camera over LAN needs HTTPS.** File upload works over HTTP; mobile
   browser camera access generally requires a secure context. Use a local TLS
   certificate or a trusted tunnel for phone-camera testing.
6. **Model files add ~37 MB to the repository.** They are MIT-licensed, but if
   size matters, keep them out of git and document a download step.
