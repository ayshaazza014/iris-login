# Iris-Based Secure Authentication System for Web Applications

This repository contains a Django-based iris authentication prototype.

## Current status

The application includes student registration, iris-only student and staff login, template matching, and protected dashboards. It is an educational prototype; it has not been validated for production biometric use.

## Goals

- Build a mobile-friendly iris login experience.
- Reuse the existing OpenCV and NumPy iris-processing logic where suitable.
- Store only minimal biometric template metadata in the database.
- Use Django sessions and server-side authorization.
- Validate the pipeline before integrating it into the web app.

The iris extraction pipeline is included in `iris_extract.py` and is loaded relative to the project, so a clone does not depend on a machine-specific absolute path.

## Important limitations

- This is an academic prototype, not a production biometric authentication system.
- Iris matching is not the same as liveness detection.
- Camera quality, lighting, and segmentation performance may affect recognition results.
- The project must be validated on real, consented sample data before claiming reliable accuracy.

## Setup

1. Create and activate a virtual environment.
2. Install dependencies:

   `py -m pip install -r requirements.txt`

3. Set the Django environment variables. `DJANGO_SECRET_KEY` must be a long random value and must not be committed. For local development, if it is omitted while `DJANGO_DEBUG=true`, Django creates a temporary key on startup.

   PowerShell example:

   ```powershell
   $env:DJANGO_DEBUG = "true"
   $env:DJANGO_SECRET_KEY = "replace-with-a-long-random-secret"
   ```

4. Initialize the database schema and start the development server:

   ```powershell
   py manage.py migrate
   py manage.py runserver
   ```

5. Open `http://127.0.0.1:8000/`. Run tests with `py manage.py test`.

Student iris images can be uploaded instead of using a live camera. Iris templates and account records are stored in the local SQLite database; do not commit that database.

## Security and privacy notes

- Do not commit biometric datasets, raw camera captures, or local databases.
- Keep credentials and secrets out of source control. `.env.example` is a template only; set your own `DJANGO_SECRET_KEY`.
- Never expose stored iris templates to the browser.
- Fail closed on invalid or missing images.
- Iris extraction and matching are not liveness detection and must not be treated as production-grade identity verification.

The repository ignores local databases, backups, uploaded photos, and generated iris/debug data. The `synthetic_eye.png` image is a synthetic test fixture.

## License

This project is intended for educational/demo use in a beginner-friendly environment.
