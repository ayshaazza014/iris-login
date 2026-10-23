"""
Iris structure extraction pipeline (Daugman-style)

Steps per image:
 1. Detect eye regions (Haar cascade; both eyes in close-ups are handled separately)
 2. Segment pupil (inner boundary) and iris (outer boundary)
 3. Normalise the annular iris into a fixed-size rectangle (rubber-sheet model)
 4. Enhance texture (CLAHE) -> this is the "iris structure" image
 5. Encode texture with Gabor filters -> binary IrisCode + mask
 6. Save debug overlays, normalised iris, and IrisCode; optional Hamming-distance matching

Usage:
    python iris_extract.py --input /path/to/images --output out
    python iris_extract.py --input a.jpg --output out
Requires: pip install opencv-python numpy
"""
import argparse
import glob
import os

import cv2
import numpy as np

NORM_H, NORM_W = 64, 512  # normalised iris size (radial x angular)


# --------------------------------------------------------------------------
# 1. Eye detection
# --------------------------------------------------------------------------
def detect_eyes(gray):
    """Return list of (x, y, w, h) eye boxes sorted left->right."""
    cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_eye.xml")
    h, w = gray.shape
    min_sz = max(40, int(min(h, w) * 0.08))
    eyes = cascade.detectMultiScale(gray, 1.1, 5, minSize=(min_sz, min_sz))
    eyes = sorted(eyes, key=lambda e: e[2] * e[3], reverse=True)[:2]
    return sorted([tuple(e) for e in eyes], key=lambda e: e[0])


# --------------------------------------------------------------------------
# 2. Segmentation  (iris first, then pupil inside it – robust for dark irises)
# --------------------------------------------------------------------------
def find_iris(eye_gray):
    """
    Outer (limbus) boundary: Hough candidates scored by contrast between the
    darker interior and the brighter ring just outside (sclera/skin).
    Returns (cx, cy, r) in ROI coordinates.
    """
    h, w = eye_gray.shape
    blur = cv2.GaussianBlur(eye_gray, (9, 9), 2)
    r_lo, r_hi = int(0.10 * w), int(0.32 * w)
    circles = cv2.HoughCircles(blur, cv2.HOUGH_GRADIENT, dp=1.2,
                               minDist=w // 8, param1=80, param2=18,
                               minRadius=r_lo, maxRadius=r_hi)
    yy, xx = np.mgrid[:h, :w]
    best, best_score = None, -1e9
    cands = [] if circles is None else circles[0][:40]
    for cx, cy, r in cands:
        d = np.hypot(xx - cx, yy - cy)
        inside = blur[d < 0.9 * r]
        ring = blur[(d > 1.05 * r) & (d < 1.35 * r)]
        if inside.size < 50 or ring.size < 50:
            continue
        # prefer dark interior, bright surround, and centred circles
        centre_pen = np.hypot(cx - w / 2, cy - h / 2) / w * 40
        score = ring.mean() - inside.mean() - centre_pen
        if score > best_score:
            best, best_score = (int(cx), int(cy), int(r)), score
    if best is None:  # fallback: darkest blob
        thr = np.percentile(blur, 8)
        m = (blur <= thr).astype(np.uint8)
        ys, xs = np.nonzero(m)
        if len(xs) == 0:
            return w // 2, h // 2, w // 6
        return int(xs.mean()), int(ys.mean()), max(r_lo, int(np.sqrt(len(xs) / np.pi) * 1.8))
    return best


def find_pupil(eye_gray, iris):
    """Pupil = darkest compact region inside the iris disk."""
    ix, iy, ir = iris
    h, w = eye_gray.shape
    blur = cv2.GaussianBlur(eye_gray, (7, 7), 0)
    yy, xx = np.mgrid[:h, :w]
    disk = np.hypot(xx - ix, yy - iy) < 0.7 * ir
    vals = blur[disk]
    thr = np.percentile(vals, 30)
    m = ((blur <= thr) & disk).astype(np.uint8) * 255
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return ix, iy, int(0.35 * ir)
    c = max(cnts, key=cv2.contourArea)
    (cx, cy), r = cv2.minEnclosingCircle(c)
    r = int(np.clip(r, 0.2 * ir, 0.5 * ir))   # physiological limits
    return int(cx), int(cy), r


# --------------------------------------------------------------------------
# 3. Normalisation (Daugman rubber sheet)
# --------------------------------------------------------------------------
def normalise(eye_gray, pupil, iris, out_h=NORM_H, out_w=NORM_W):
    px, py, pr = pupil
    ix, iy, ir = iris
    theta = np.linspace(0, 2 * np.pi, out_w, endpoint=False)
    rr = np.linspace(0, 1, out_h)[:, None]
    # points on pupil and iris boundaries for each angle
    xp, yp = px + pr * np.cos(theta), py + pr * np.sin(theta)
    xi, yi = ix + ir * np.cos(theta), iy + ir * np.sin(theta)
    X = ((1 - rr) * xp + rr * xi).astype(np.float32)
    Y = ((1 - rr) * yp + rr * yi).astype(np.float32)
    polar = cv2.remap(eye_gray, X, Y, cv2.INTER_LINEAR,
                      borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    valid = ((X >= 0) & (X < eye_gray.shape[1]) &
             (Y >= 0) & (Y < eye_gray.shape[0])).astype(np.uint8)
    return polar, valid


def noise_mask(polar, valid):
    """Mask eyelids / eyelashes / specular highlights (1 = usable)."""
    m = valid.copy()
    m[polar > 235] = 0                      # specular reflections
    m[polar < 20] = 0                       # lashes / shadow
    m[:, :] &= 1
    # rubber-sheet top & bottom sectors are often occluded by eyelids
    m[:, int(NORM_W * 0.20):int(NORM_W * 0.30)] = m[:, int(NORM_W * 0.20):int(NORM_W * 0.30)]
    return m


def enhance(polar):
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(4, 16))
    return clahe.apply(polar)


# --------------------------------------------------------------------------
# 4. Feature encoding (Gabor -> IrisCode)
# --------------------------------------------------------------------------
def gabor_bank(ksize=(9, 31), wavelengths=(8, 16)):
    bank = []
    for lam in wavelengths:
        sigma = lam * 0.56
        k = cv2.getGaborKernel(ksize, sigma, 0, lam, 1.0, 0, ktype=cv2.CV_32F)
        k_im = cv2.getGaborKernel(ksize, sigma, 0, lam, 1.0, np.pi / 2,
                                  ktype=cv2.CV_32F)
        bank.append((k, k_im))
    return bank


def encode(enhanced, mask):
    img = enhanced.astype(np.float32)
    img -= img.mean()
    bits, bmask = [], []
    for k_re, k_im in gabor_bank():
        re = cv2.filter2D(img, cv2.CV_32F, k_re, borderType=cv2.BORDER_WRAP)
        im = cv2.filter2D(img, cv2.CV_32F, k_im, borderType=cv2.BORDER_WRAP)
        bits += [re > 0, im > 0]
        bmask += [mask > 0, mask > 0]
    return np.concatenate(bits, 0).astype(np.uint8), np.concatenate(bmask, 0).astype(np.uint8)


def hamming(code1, mask1, code2, mask2, max_shift=8):
    """Normalised Hamming distance with circular shift for rotation tolerance."""
    best = 1.0
    for s in range(-max_shift, max_shift + 1):
        c2, m2 = np.roll(code2, s, 1), np.roll(mask2, s, 1)
        both = (mask1 & m2).astype(bool)
        if both.sum() == 0:
            continue
        best = min(best, np.logical_xor(code1, c2)[both].mean())
    return best


# --------------------------------------------------------------------------
# Driver
# --------------------------------------------------------------------------
def process_eye(eye_bgr, tag, out_dir):
    gray = cv2.cvtColor(eye_bgr, cv2.COLOR_BGR2GRAY)
    # upscale small ROIs for better boundary localisation
    scale = 1.0
    if gray.shape[1] < 300:
        scale = 300 / gray.shape[1]
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        eye_bgr = cv2.resize(eye_bgr, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)

    iris = find_iris(gray)
    pupil = find_pupil(gray, iris)
    polar, valid = normalise(gray, pupil, iris)
    mask = noise_mask(polar, valid)
    enh = enhance(polar)
    code, cmask = encode(enh, mask)

    # debug overlay
    vis = eye_bgr.copy()
    cv2.circle(vis, pupil[:2], pupil[2], (0, 255, 0), 2)
    cv2.circle(vis, iris[:2], iris[2], (0, 0, 255), 2)
    cv2.imwrite(os.path.join(out_dir, f"{tag}_segmented.png"), vis)
    cv2.imwrite(os.path.join(out_dir, f"{tag}_normalised.png"), polar)
    cv2.imwrite(os.path.join(out_dir, f"{tag}_structure.png"), enh)
    cv2.imwrite(os.path.join(out_dir, f"{tag}_iriscode.png"), code * 255)
    np.savez_compressed(os.path.join(out_dir, f"{tag}_code.npz"), code=code, mask=cmask)
    return code, cmask


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="image file or folder")
    ap.add_argument("--output", default="iris_out")
    ap.add_argument("--match", action="store_true",
                    help="print pairwise Hamming distance matrix")
    args = ap.parse_args()
    os.makedirs(args.output, exist_ok=True)

    files = (sorted(glob.glob(os.path.join(args.input, "*.[jp][pn]g")) +
                    glob.glob(os.path.join(args.input, "*.jpeg")))
             if os.path.isdir(args.input) else [args.input])

    templates = {}
    for f in files:
        img = cv2.imread(f)
        if img is None:
            print("skip (unreadable):", f)
            continue
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        eyes = detect_eyes(gray)
        if not eyes:
            print("no eye found:", os.path.basename(f))
            continue
        base = os.path.splitext(os.path.basename(f))[0]
        for i, (x, y, w, h) in enumerate(eyes):
            pad = int(0.15 * w)
            roi = img[max(0, y - pad):y + h + pad, max(0, x - pad):x + w + pad]
            tag = f"{base}_eye{i}"
            try:
                templates[tag] = process_eye(roi, tag, args.output)
                print("processed:", tag)
            except Exception as e:  # keep batch running
                print("failed:", tag, e)

    if args.match and len(templates) > 1:
        keys = list(templates)
        print("\nHamming distances (<0.32 ~ same iris):")
        for i, a in enumerate(keys):
            for b in keys[i + 1:]:
                d = hamming(*templates[a], *templates[b])
                print(f"{a} vs {b}: {d:.3f}")


if __name__ == "__main__":
    main()
