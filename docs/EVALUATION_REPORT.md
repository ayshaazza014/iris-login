# Iris Biometric Authentication — Empirical Evaluation Report

**Date of Evaluation:** 2026-10-26 09:33:48 UTC  
**Pipeline:** OpenCV Haar Eye Detection -> Circular Boundary Segmentation -> Daugman Rubber-Sheet Normalization (64x512) -> CLAHE Texture Enhancement -> 2D Log-Gabor Encoding (`gabor-eye-crop-v2`).  
**Evaluation Methodology:** In accordance with TRD FR-08, FR-13, and Section 8, this report measures statistical separation between genuine intra-subject comparisons and impostor cross-subject comparisons.

---

## 1. Executive Summary & Calibration Scorecard

| Metric | Measured Value | Standard / Requirement |
|---|---|---|
| **Subjects Evaluated** | 12 | Multi-subject cohort |
| **Enrolled IrisCodes** | 48 | (256, 512) uint8 arrays |
| **Genuine Comparisons** | 72 | Intra-subject sessions with rotational & sensor noise |
| **Impostor Comparisons** | 1056 | Cross-subject pairs |
| **Genuine Distance Distribution** | Mean: `0.1039` (Std: `0.0449`) | Range: `[0.0448, 0.2206]` |
| **Impostor Distance Distribution** | Mean: `0.4581` (Std: `0.0329`) | Range: `[0.3290, 0.5292]` |
| **Zero-FAR Threshold** | `0.32` | Highest threshold yielding 0.00% False Accepts |
| **Equal Error Rate (EER)** | `0.00%` | Occurs at threshold `T ≈ 0.23` |
| **Configured 1:N Match Threshold** | `T = 0.32` | FAR: `0.00%` \| FRR: `0.00%` |
| **Configured 1:1 Verify Threshold** | `T = 0.35` | FAR: `0.38%` \| FRR: `0.00%` |
| **Mean Frame Extraction Latency** | `148.87 ms` | Compliant with NFR-08 |
| **Mean Comparison Latency** | `5.526 ms` | Multi-shift circular Hamming match |
| **End-to-End Decision Latency** | `~154.40 ms` | Single 1:1 authentication request |

---

## 2. Threshold Sweep & Operating Characteristics

The table below illustrates error trade-offs across fractional Hamming distance thresholds ($T \in [0.15, 0.45]$):

| Threshold ($T$) | False Accept Rate (FAR) | False Reject Rate (FRR) | Genuine Match Rate (GMR) | Operating Suitability |
|---|---|---|---|---|
| `0.15` | 0.00% | 16.67% | 83.33% | Ultra-Strict |
| `0.20` | 0.00% | 5.56% | 94.44% | Ultra-Strict |
| `0.25` | 0.00% | 0.00% | 100.00% | Ultra-Strict |
| `0.28` | 0.00% | 0.00% | 100.00% | Ultra-Strict |
| `0.30` | 0.00% | 0.00% | 100.00% | Ultra-Strict |
| `0.32` | 0.00% | 0.00% | 100.00% | **Operational 1:N Identification** (FAR=0.00%) |
| `0.34` | 0.38% | 0.00% | 100.00% | Ultra-Strict |
| `0.35` | 0.38% | 0.00% | 100.00% | **Operational 1:1 Verification** (FAR=0.38%) |
| `0.38` | 5.30% | 0.00% | 100.00% | Ultra-Strict |
| `0.40` | 7.20% | 0.00% | 100.00% | High False-Accept Vulnerability |
| `0.45` | 29.26% | 0.00% | 100.00% | High False-Accept Vulnerability |

---

## 3. Threshold Calibration Justification (TRD FR-08 & FR-13)

* **1:N Identification Threshold (`0.32`):**
  When a scan is submitted without an account identifier, the system searches the entire non-staff database. Because the probability of at least one false accept scales with database size ($1 - (1 - \text{FAR})^N$), the identification threshold is calibrated strictly at `0.32`, keeping impostor false-match rate at **0.00%**.
* **1:1 Verification Threshold (`0.35`):**
  When a user provides their account identifier (e.g. username or student ID), the matcher only compares against that single account's enrolled template. Threshold `0.35` accommodates natural acquisition variations (eyelid occlusions, slight pupil shifts) while maintaining strict impostor rejection (FAR: **0.38%**).

---

## 4. Hardware, Lighting, and Presentation Attack Limitations (TRD §8)

1. **No Presentation Attack Detection (PAD) / Liveness:**
   The matcher evaluates geometric texture patterns. It does not measure corneal reflection dynamics, pupil reaction to light, or 3D liveness. High-resolution photos or video replays can match if not physically supervised.
2. **Environmental & Lighting Constraints:**
   Specular reflections from eyeglasses, direct sunlight, or overhead fluorescent lighting can corrupt iris segmentation. The acquisition environment must feature uniform, diffuse illumination.
3. **Sensor Quality:**
   Front-facing webcams must provide an iris diameter of at least ~100 pixels with minimal motion blur.
4. **Academic Demonstration Disclaimer:**
   This project is designed as an educational and research prototype demonstrating iris biometric workflows and fail-closed authentication. It is not approved for high-assurance or mission-critical enterprise identity management.
