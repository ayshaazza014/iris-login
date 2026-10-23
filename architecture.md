# Architecture: Iris-Based Secure Authentication System

## 1. High-level view

```text
Mobile/desktop browser
  ├── HTML/CSS pages
  └── JavaScript camera capture (getUserMedia)
             |
             | image upload over same-origin HTTPS in deployment
             v
Django views / request validation
  ├── enrollment workflow
  ├── verification workflow
  ├── session and authorization checks
  └── generic user-facing result
             |
             v
Iris service layer
  ├── image validation and quality checks
  ├── eye/iris preprocessing
  ├── feature encoding
  ├── template reconstruction/version checks
  └── matcher + calibrated threshold
             |
             v
Django ORM / SQLite (development)
  ├── account record
  ├── iris template bytes
  ├── array shape, dtype and encoding version
  ├── enrollment timestamps/status
  └── minimal audit metadata (no biometric content)
```

## 2. Recommended repository layout

```text
iris_authentication/
├── manage.py
├── requirements.txt
├── README.md
├── .gitignore
├── .env.example
├── iris_project/
│   ├── settings.py
│   ├── urls.py
│   ├── asgi.py
│   └── wsgi.py
├── authentication/
│   ├── models.py
│   ├── admin.py
│   ├── urls.py
│   ├── views.py
│   ├── forms.py
│   ├── services/
│   │   ├── __init__.py
│   │   ├── enrollment.py
│   │   ├── verification.py
│   │   └── access_control.py
│   ├── tests/
│   │   ├── test_enrollment.py
│   │   ├── test_verification.py
│   │   └── test_access_control.py
│   └── migrations/
├── iris_engine/
│   ├── __init__.py
│   ├── iris_extract.py
│   ├── capture_validation.py
│   ├── preprocessing.py
│   ├── matcher.py
│   └── template_io.py
├── templates/
│   ├── home.html
│   ├── enroll.html
│   ├── login.html
│   └── dashboard.html
├── static/
│   ├── css/style.css
│   └── js/camera.js
├── evaluation/
│   ├── README.md
│   └── evaluate_matcher.py
└── test_data/  # local-only, consented data; never commit real biometric data
```

This is the target layout. Copilot must inspect the actual repository and create files incrementally rather than assuming this structure already exists.

## 3. Component responsibilities

### Frontend
- Render enrollment and login pages.
- Request camera permission only after a user action.
- Capture an image and send it to Django using a CSRF-protected request.
- Show generic progress, retry, success, or failure messages.
- Never decide access on the client side.

### Django request layer
- Validate authentication state, CSRF, file size, file type, and request rate.
- Associate enrollment with an authorized account and consented data.
- Call service functions rather than implementing image processing in views.
- Create a session only after the server verifies a successful match.
- Enforce access control on every protected endpoint.

### Iris engine
- Adapt the existing extraction pipeline behind stable functions.
- Validate image readability, dimensions, and supported format.
- Reject missing/invalid/empty templates and inadequate valid-mask overlap.
- Preserve a template schema containing shape, dtype, encoding version, and mask.
- Return a structured result; do not decide authorization by itself.

### Matcher
- Calculate the masked Hamming distance using the existing implementation where validated.
- Treat invalid comparisons as failures, not matches.
- Use a threshold chosen on validation data and frozen before final test evaluation.
- Keep detailed distance values in restricted development/evaluation output, not public responses.

### Database
- Use Django ORM.
- Store account linkage, template bytes, array shape/dtype, encoding version, enrollment status, and timestamps.
- Add uniqueness constraints and controlled re-enrollment.
- Never return template bytes in normal API responses.
- For production-like use, assess encryption at rest, key management, backup protection, and deletion.

## 4. Template serialization
The supplied extractor writes compressed `.npz` files containing `code` and `mask`. For database storage, define a versioned serialization format. Store the array shape, dtype, encoding version, and bytes, or store a safe, access-controlled template file reference. Reconstruct arrays only after validating the metadata. Do not assume shape or dtype from byte length alone.

## 5. Authentication flow
1. Browser requests login page.
2. User provides an account identifier and explicitly starts camera capture.
3. Browser captures an image and posts it to Django with CSRF protection.
4. Django validates the request and applies rate limits.
5. Iris service validates the image and extracts a template.
6. Matcher compares it with the account's enrolled template.
7. Invalid capture or processing error: deny/retry.
8. Match meets calibrated threshold: Django logs the user in using a server-side session.
9. Protected dashboard checks authenticated session and authorization server-side.
10. Failed attempt: return a generic denial/retry message.

## 6. Enrollment flow
1. Confirm the account is authorized and data collection is consented.
2. Capture or import an approved sample and explicitly associate it with the account.
3. Validate image quality and run extraction.
4. Reject failed or invalid extraction.
5. Serialize the template and metadata in the documented versioned format.
6. Save through the ORM, preventing accidental duplicate enrollment.
7. Test loading and matching the saved template.
8. Provide controlled re-enrollment and deletion.

## 7. Security boundaries
- Browser code is untrusted; server decides access.
- Camera permission is not proof of liveness.
- A matching image is not proof that it was captured from a live eye.
- Protect against CSRF, brute-force attempts, oversized uploads, malformed files, session fixation, unauthorized template access, and accidental data exposure.
- Use HTTPS outside localhost.
- Avoid storing raw captures unless required for consented evaluation.
- Do not promise protection against all spoofing attacks.

## 8. Development and deployment
- Local: Django development server and SQLite.
- Phone testing: use localhost on the same device or a properly configured HTTPS development environment; mobile browser camera access generally requires a secure context and user permission.
- Deployment: use HTTPS, secure cookies, environment-managed secrets, production server settings, database/backup protection, and reviewed privacy/security controls.
