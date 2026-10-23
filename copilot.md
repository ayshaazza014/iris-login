# Copilot Instructions for This Repository

## Read first
Before coding, read:
- `project.md`
- `architecture.md`
- `trd.md`
- `skill.md`

Then inspect the actual repository, especially `iris_extract.py`, before changing anything.

## Product goal
Build a demonstrable iris-based login website. An enrolled user visits the website, grants camera permission, captures an eye image using a mobile browser, and the backend extracts and compares an iris template. Access is granted only if the match passes a threshold selected and evaluated using data. Otherwise, access is denied or the user is asked to retry.

## Existing pipeline contract
The current `iris_extract.py`:
- Uses OpenCV and NumPy.
- Detects eye regions with a Haar cascade.
- Estimates iris and pupil boundaries.
- Normalizes the iris to a fixed-size representation.
- Enhances texture with CLAHE.
- Encodes features with Gabor filters.
- Produces a binary `code` and `mask`.
- Saves `.npz` files with keys `code` and `mask`.
- Provides a Hamming-distance function with circular-shift tolerance.

Do not assume this is a trained neural network. Do not silently change the encoding algorithm or template shape. Check the actual arrays and test matching before integrating with the database.

## Engineering rules
- Use Python and Django for the backend, SQLite for initial local development, and HTML/CSS/JavaScript for the interface.
- Keep modules separated: capture/input, preprocessing, feature extraction, matching, enrollment, persistence, and web views.
- Do not place all project logic inside `views.py`.
- Use Django ORM; do not construct SQL strings manually.
- Add model validation and clear error handling.
- Use CSRF protection for state-changing browser requests.
- Apply server-side access checks to every protected view; hiding a button is not authorization.
- Use Django sessions only after successful authentication.
- Rate-limit authentication attempts and avoid revealing sensitive matching details to the browser.
- Fail closed if a capture is poor, the template is missing, masks have no valid overlap, processing fails, or the result is uncertain.
- Never store passwords, biometric templates, or session secrets in logs.
- Never commit user biometric data, generated captures, `db.sqlite3`, `.env`, or credentials. Add suitable `.gitignore` entries.
- Avoid storing raw eye images by default. If raw images are required for testing, use a consented, access-restricted development dataset and define a deletion plan.
- Store template shape, encoding/version metadata, and mask information so stored templates can be reconstructed safely. Validate these fields before matching.
- Avoid duplicate enrollment. Define a clear update/re-enrollment workflow.
- Do not make a 100% accuracy claim. Report measured FAR, FRR, genuine/impostor comparison counts, threshold-selection method, and dataset limitations.
- Keep test subjects separated between training/validation/test where applicable; do not leak near-duplicate images across splits.
- Document that a normal image matcher is not liveness detection and can be vulnerable to photo/replay attacks.

## Code quality
- Use descriptive names and type hints for new non-trivial functions.
- Keep functions small and testable.
- Add tests for successful matching, failed matching, malformed templates, empty masks, unknown users, duplicate enrollment, and unauthorized access.
- Update `requirements.txt` when dependencies change.
- Prefer reproducible commands that work on Windows PowerShell as well as standard Python environments.
- Do not invent test results. If a command cannot be run, say so.

## User-facing explanations
The project owner is a beginner. Give exact filenames and paths, commands to run, what output to expect, and how to report errors. Work in stages and wait for confirmation when a task depends on results from the user's computer or data.
