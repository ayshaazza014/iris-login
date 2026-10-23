# Iris-Based Secure Authentication System for Web Applications

This repository contains a full-stack Django iris biometric authentication application prototype.

## Current status

The application includes:
- Student and staff biometric registration and authentication
- In-memory Daugman-style Gabor filter iris feature extraction and template matching
- Protected student and staff dashboards with role-based access control
- Secure administration via Django Admin
- Re-enrollment workflows with audit logging
- Rate limiting and decompression bomb protection against denial-of-service attacks

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
Copy `.env.example` to `.env` and set your configuration:
```powershell
cp .env.example .env
```
Ensure `DJANGO_SECRET_KEY` is populated. `DJANGO_DEBUG` defaults to `true` for local development.

### 4. Initialize Database Schema & Seed Demo Data
```powershell
python manage.py migrate
python manage.py seed_users
```
The `seed_users` command creates:
- `alice` (Student, enrolled with `synthetic_eye.png`)
- `bob` (Student)
- `charlie` (Student)
- `staff_alice` (Staff account)

### 5. Run the Server
```powershell
python manage.py runserver
```
Visit `http://127.0.0.1:8000/`. You can log in as `alice` immediately by uploading `synthetic_eye.png`.

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

## Security & Architecture Highlights

- **In-Memory Biometric Processing**: Feature extraction runs purely in memory without creating temporary debug files on disk during authentication.
- **Decompression Bomb Protection**: Image headers (PNG, JPEG, WebP) are validated for dimensions ($< 2048 \times 2048$) before passing byte streams to OpenCV.
- **Rate Limiting**: Sliding-window rate limiters prevent asymmetric CPU exhaustion attacks on computer vision endpoints.
- **Audit Logging**: Sensitive actions such as template re-enrollment are logged with actor and target IDs.
- **WCAG 2.1 AA Compliance**: UI colors, button contrasts, ARIA roles, and responsive camera viewports adhere to accessibility standards.

## License

Educational prototype for academic and demonstration purposes.
