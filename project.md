# Project Brief: Iris-Based Secure Authentication System for Web Applications

## 1. Overview
This mini-project aims to demonstrate a web login flow that uses iris features as the primary biometric verification step instead of relying on a conventional username/password login alone. A registered user opens the login page, allows camera access, captures an eye image, and the system compares extracted features with that account's enrolled template.

## 2. Problem statement
Conventional password-based authentication can be affected by weak, reused, shared, or stolen passwords. This project explores iris-feature matching as an alternative verification mechanism for a controlled college-website prototype. The project must evaluate performance and security limitations rather than assume biometric authentication is infallible.

## 3. Objectives
- Inspect and reuse the supplied `iris_extract.py` pipeline where suitable.
- Enroll a user and persist a reproducible iris template in a database.
- Capture an eye image through a browser camera, especially on a mobile phone.
- Process the image and compare its iris template with the enrolled template.
- Grant access to a protected dashboard only after successful verification.
- Deny access safely on mismatch, poor image quality, missing template, or processing error.
- Evaluate matching performance using documented experiments and test data.
- Provide a clear, beginner-friendly interface and setup instructions.

## 4. Scope for the first demonstrator
### In scope
- Django website and session-based access control.
- Local development using SQLite.
- Browser camera capture using JavaScript and explicit user permission.
- Python image processing with OpenCV and NumPy.
- Template enrollment and verification for a claimed account.
- Basic enrollment administration suitable for a controlled academic demo.
- Automated tests and a performance evaluation report.

### Out of scope for the first demonstrator
- Claiming guaranteed 100% accuracy.
- Production deployment for a real college or use with real student accounts.
- Replacing institutional identity management.
- Guaranteed liveness detection or resistance to all presentation attacks.
- One-to-many national-scale biometric identification.
- Collecting or storing real biometric data without informed consent and appropriate approval.

## 5. Existing starting point
The supplied `iris_extract.py` implements a classical image-processing pipeline: Haar-cascade eye detection, approximate iris/pupil boundary estimation, rubber-sheet-style normalization, CLAHE enhancement, Gabor-based binary feature encoding, and optional Hamming-distance comparison. It writes `.npz` templates with `code` and `mask` arrays. The existing code should be inspected and tested before integration; extraction success alone does not prove reliable identity recognition.

## 6. Intended user journey
1. An authorized operator creates or approves an account.
2. The user enrolls one or more suitable iris samples with consent and verified account association.
3. The system processes samples and saves a template plus metadata.
4. The user opens the login page on a supported device.
5. The user enters/selects their account identifier and grants camera permission.
6. The browser captures an image and sends it securely to the backend.
7. The backend validates the upload, processes the image, and compares the template.
8. On successful verification, Django creates an authenticated session.
9. The protected dashboard checks the session server-side.
10. On failure, the user receives a generic retry/denial message; the system does not expose stored templates or detailed matching internals.

## 7. Success criteria
- A new test user can be enrolled through the defined process.
- The saved template can be loaded and reconstructed without shape/dtype corruption.
- A genuine test capture can be compared against the correct enrolled template.
- An impostor comparison does not automatically receive access.
- Protected routes deny unauthenticated requests.
- Camera, upload, processing, and database failures fail closed.
- Automated tests cover key success and failure paths.
- A repeatable evaluation reports the number of genuine and impostor comparisons, FAR, FRR, the selected threshold, and limitations.
- The README explains installation, startup, enrollment, testing, and cleanup.

## 8. Accuracy and security statement
No fixed accuracy is promised. Performance depends on data quality, sensor/camera, segmentation, encoding, user variation, and threshold. The project must measure performance on separate evaluation data and report false acceptance and false rejection. Iris matching alone does not establish liveness; presentation-attack detection is a separate security concern.

## 9. Privacy principles
- Use consented data and only for the stated project purpose.
- Minimize collection and retention.
- Do not store raw images unless there is a justified testing need.
- Restrict template access and never expose templates through frontend responses.
- Exclude datasets, captures, databases, and secrets from version control.
- Provide a way to remove an enrolled test account and its template.
