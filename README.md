# Iris-Based Secure Authentication System for Web Applications

This repository contains a full-stack Django iris biometric authentication application prototype.

## Current status

The application includes:
- Student and staff biometric registration and authentication
- In-memory Daugman-style Gabor filter iris feature extraction and template matching (`gabor-eye-crop-v2`)
- 1:1 account verification and 1:N student identification modes with calibrated decision thresholds
- Protected student and staff dashboards with server-side role-based access control
- Secure administration via Django Admin
- Re-enrollment workflows with audit logging
- Bounded sliding-window rate limiting, client frame throttling, and header-based decompression bomb protection against denial-of-service attacks
- Quantitative biometric evaluation suite with FAR/FRR measurement and latency benchmarking

## Getting Started

### 1. Create and Activate Virtual Environment
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 2. Install Dependencies
```powershell
pip install -r requirements.txt
```

### 3. Environment Variables
Copy `.env.example` to `.env` and configure your settings:
```powershell
cp .env.example .env
```
Ensure `DJANGO_SECRET_KEY` is set.
- `DJANGO_DEBUG`: Set to `true` for local development; defaults securely to `false` in production.
- `IRIS_TRUST_PROXY_HEADERS`: Set to `true` only when deployed behind a trusted reverse proxy (e.g. Nginx) that sanitizes `X-Forwarded-For`.

### 4. Initialize Database Schema & Seed Demo Data
```powershell
python manage.py migrate
python manage.py seed_users --demo
```
The `seed_users` command creates:
- `alice` (Student demo account)
- `bob` (Student demo account)
- `charlie` (Student demo account)
- `staff_alice` (Staff demo account)

> **Security Note:** In non-debug production environments, biometric template enrollment via `synthetic_eye.png` is automatically skipped unless explicitly invoked with `--demo`.

### 5. Run the Server
```powershell
python manage.py runserver
```
Visit `http://127.0.0.1:8000/`.

---

## Running Tests

Run the full Django test suite:
```powershell
python manage.py test
```

Run Pytest biometric unit tests:
```powershell
pytest tests
```

---

## Biometric Evaluation & Threshold Calibration

In accordance with TRD FR-08, FR-13, and Section 8, the repository provides an automated evaluation suite to assess FAR, FRR, genuine/impostor distributions, and processing latency.

Run the evaluation:
```powershell
python manage.py evaluate
```
(For a faster smoke pass, append `--quick`).

The command executes statistical comparisons across multi-session subject cohorts and outputs an empirical report to [`docs/EVALUATION_REPORT.md`](docs/EVALUATION_REPORT.md).

### Key Measured Benchmark Metrics
- **Mean Genuine Distance:** `0.1039 ± 0.0449`
- **Mean Impostor Distance:** `0.4581 ± 0.0329`
- **Zero-FAR Threshold:** `0.32` (0.00% False Acceptance Rate)
- **1:N Match Threshold (`0.32`):** FAR: 0.00% | FRR: 0.00%
- **1:1 Verify Threshold (`0.35`):** FAR: 0.38% | FRR: 0.00%
- **Feature Extraction Latency:** ~148 ms / frame (compliant with NFR-08)
- **Pairwise Comparison Latency:** ~5.5 ms / comparison

---

## Data Deletion & Privacy Policy

In accordance with TRD NFR-04 and acceptance criteria:
1. **Raw Image Minimization:** Uploaded capture frames are decoded in memory, processed into 256x512 bitwise IrisCodes, and discarded immediately. No raw iris photographs or camera video feeds are stored on disk or database.
2. **Template Deletion by Users/Staff:**
   - Authorized staff members can delete or re-enroll biometric templates via the Staff Portal (`/staff/re-enroll/`).
   - Administrators can delete templates and user profiles directly via Django Admin (`/admin/`).
3. **Database Reset:**
   - To completely purge all stored credentials and templates in a test environment, remove `db.sqlite3` and re-run migrations:
     ```powershell
     rm db.sqlite3
     python manage.py migrate
     ```

---

## Security & Architecture Highlights

- **Fail-Closed Session Control:** Sessions are only created upon verified backend match. Ambiguous, missing, or mismatched templates result in immediate rejection without session elevation.
- **In-Memory Biometric Processing**: Feature extraction runs purely in memory without creating temporary debug files on disk during authentication.
- **Decompression Bomb Protection**: Image headers (PNG, JPEG, WebP) are validated for dimensions ($< 2048 \times 2048$) before passing byte streams to OpenCV.
- **Bounded Rate Limiting**: In-memory sliding-window limiter evicts expired keys to prevent memory leaks and returns HTTP 429 with `Retry-After` headers.
- **Proxy-Aware IP Detection**: By default, `REMOTE_ADDR` is used to prevent `X-Forwarded-For` spoofing. Header inspection is enabled only under trusted proxy flags.
- **Audit Logging**: Sensitive actions such as template re-enrollment are logged with actor and target IDs without logging raw biometric templates or sensitive credentials.
- **WCAG 2.1 AA Compliance**: UI colors, button contrasts, ARIA roles, and responsive camera viewports adhere to accessibility standards.

---

## Limitations & Disclaimer

- **No Presentation Attack Detection (PAD) / Liveness:** The pipeline evaluates 2D Gabor iris texture similarity and does not verify physical 3D depth, specular corneal reflection, or micro-pupillary oscillation.
- **Lighting and Camera Quality:** Requires clear, front-facing imagery with diffuse illumination. Heavy shadows or direct reflections on eyeglasses will degrade segmentation accuracy.
- **Academic Demonstration:** This software is an educational prototype and research demonstration. It is not intended for mission-critical enterprise identity infrastructure.

## License

Educational prototype for academic and demonstration purposes.
