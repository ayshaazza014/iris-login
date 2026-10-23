# Technical Requirements Document (TRD)

## 1. Purpose
Define the functional, technical, security, and testing requirements for a student mini-project that demonstrates iris-based verification for access to a protected web application.

## 2. System overview
The system uses a browser interface, Django backend, Python/OpenCV iris-processing pipeline, template matcher, and database. The initial implementation reuses the supplied `iris_extract.py` where tests show it is suitable. The pipeline is based on classical image processing and Gabor-filter feature encoding; it is not currently a trained deep-learning model.

## 3. Technology requirements
- Language: Python.
- Web framework: Django.
- Computer vision: OpenCV (`opencv-python`).
- Numeric arrays: NumPy.
- Database: SQLite for local development.
- Frontend: HTML, CSS, JavaScript.
- Browser camera: `navigator.mediaDevices.getUserMedia`.
- Testing: Django test framework and Python unit tests.
- Version control: Git with biometric data and secrets excluded.

Pin compatible dependency versions in `requirements.txt` after verifying the Python version and successful installation. Do not assume all latest versions are compatible.

## 4. Functional requirements

### FR-01: Home and login page
The system shall provide a clear landing page and an iris-login page.

### FR-02: Camera permission and capture
The browser shall request camera permission after explicit user action. If permission is denied or the camera is unavailable, the application shall show a useful retry message and shall not grant access.

### FR-03: Image validation
The backend shall validate image size, type, readability, and basic dimensions before processing. Invalid files shall be rejected safely.

### FR-04: Iris feature extraction
The system shall invoke the iris engine to extract an iris template from an accepted image. Extraction failure shall fail closed.

### FR-05: User enrollment
An authorized enrollment workflow shall associate a person's approved iris sample/template with a unique account. The system shall prevent accidental duplicate usernames and define controlled re-enrollment.

### FR-06: Template persistence
The system shall store a template using a documented, versioned format. The stored representation shall include or reference the code, mask, shape, dtype, and encoding version required for reconstruction.

### FR-07: Iris verification
The user shall identify the account they intend to access. The backend shall compare the captured template with that account's enrolled template using the validated matcher.

### FR-08: Decision threshold
The matcher shall use a threshold selected on validation data. A threshold shall not be described as universally correct or chosen solely from a source-code comment.

### FR-09: Access grant
Only a successful server-side verification shall create an authenticated Django session and grant access to protected pages.

### FR-10: Access denial
A mismatch, unknown account, missing template, poor capture, invalid mask, or processing error shall not grant access. User-facing messages shall not reveal stored biometric information or sensitive implementation details.

### FR-11: Protected dashboard
Protected routes shall verify authentication server-side. Client-side redirects or hidden buttons alone shall not count as access control.

### FR-12: Template management
The system shall support controlled enrollment, re-enrollment, and deletion of test accounts/templates.

### FR-13: Evaluation
The project shall provide a repeatable evaluation method and report genuine/impostor comparisons, threshold selection, FAR, FRR, and dataset limitations.

## 5. Non-functional requirements

### NFR-01: Usability
Instructions and error messages shall be understandable to a beginner and an ordinary test user.

### NFR-02: Maintainability
Image processing, matching, persistence, and views shall be separate modules with descriptive function names and tests.

### NFR-03: Reliability
Failures and malformed inputs shall fail closed. Exceptions shall be handled without exposing stack traces or biometric data to end users.

### NFR-04: Privacy
Collect only data needed for the demonstration, use consented data, minimize raw-image retention, and provide a deletion process.

### NFR-05: Security
Use CSRF protection, secure session handling, server-side authorization, upload validation, rate limiting, secret management, and HTTPS for non-local deployment.

### NFR-06: Portability
Provide setup instructions for Windows PowerShell and standard Python tooling.

### NFR-07: Testability
Important components shall be testable independently of the live camera and browser.

### NFR-08: Performance
Record practical capture-to-decision latency during evaluation. Do not promise a fixed response time until measured on target hardware.

## 6. Data requirements
Minimum account/template metadata:
- Unique account identifier.
- Display name or minimal user metadata.
- Template bytes or controlled template reference.
- Template shape and dtype.
- Encoding/algorithm version.
- Enrollment status and timestamp.

Do not expose template contents through frontend responses. Avoid storing raw images by default. Do not commit biometric data, populated databases, or camera captures to source control.

## 7. Security requirements
- Access is decided only on the backend.
- Unknown account and failed matching must not create a session.
- Enforce request size/type checks before image decoding.
- Rate-limit repeated attempts.
- Use CSRF protection for state-changing requests.
- Protect secrets with environment configuration.
- Do not log raw images, templates, or unnecessary matching details.
- Document that the matcher alone does not provide liveness or robust presentation-attack detection.
- Use consented test data and appropriate authorization for biometric collection.
- Treat the prototype as an academic demonstration, not production-ready identity infrastructure.

## 8. Accuracy and evaluation
The project shall not claim 100% accuracy. Evaluation must:
1. Separate enrollment/training, validation, and final test data as appropriate.
2. Avoid placing near-duplicate captures of the same session in different splits.
3. Include genuine comparisons and impostor comparisons.
4. Select the decision threshold on validation data.
5. Report FAR, FRR, genuine match rate, sample/comparison counts, and limitations.
6. State camera, lighting, image-quality, and dataset constraints.
7. Avoid treating a single successful login as evidence of high accuracy.

## 9. Acceptance criteria
- [ ] Project setup instructions work in a clean environment.
- [ ] Existing extractor can be invoked on a sample image or dataset, or documented failures are identified.
- [ ] A valid template can be enrolled and loaded without data-shape corruption.
- [ ] Duplicate enrollment is handled predictably.
- [ ] A genuine test comparison follows the expected decision path.
- [ ] A mismatching/invalid comparison is denied.
- [ ] Unknown users cannot access protected routes.
- [ ] Failed processing never grants access.
- [ ] CSRF and upload validation are enabled where applicable.
- [ ] Tests cover enrollment, template reconstruction, matching, and route access.
- [ ] Evaluation output reports measured metrics without unsupported claims.
- [ ] README documents setup, usage, evaluation, limitations, and data deletion.

## 10. Assumptions and open questions
- The exact dataset format and number of subjects must be confirmed.
- The Python version and dependency compatibility must be checked in the actual environment.
- Mobile camera quality may be insufficient for accurate iris extraction; this must be tested early.
- The current pipeline's segmentation and matching performance are not yet established.
- A live capture does not automatically provide liveness detection.
- A real college deployment would require institutional, privacy, security, and legal review beyond this prototype.
