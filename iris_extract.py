"""
Iris and facial multi-feature extraction pipeline (Daugman iris + periocular facial geometry)

Steps per image:
 1. Detect facial context & ocular regions (Haar face + eye cascades; eyeglasses tolerant)
 2. Segment pupil (inner boundary) and iris (outer boundary)
 3. Normalise the annular iris into a fixed-size rectangle (rubber-sheet model)
 4. Enhance texture (CLAHE) -> this is the "iris structure" image
 5. Encode texture with Gabor filters -> binary IrisCode + mask
 6. Extract facial geometry & periocular feature descriptors for multi-modal fusion
 7. Save debug overlays, normalised iris, and IrisCode; optional Hamming-distance matching

Usage:
    python iris_extract.py --input /path/to/images --output out
    python iris_extract.py --input a.jpg --output out
Requires: pip install opencv-python numpy
"""
import argparse
import functools
import glob
import os

import cv2
import numpy as np

NORM_H, NORM_W = 64, 512  # normalised iris size (radial x angular)


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
# 1. Eye and Face detection
# --------------------------------------------------------------------------
def detect_face_and_iris(image_or_gray):
    """
    Unified multi-scale Face and Iris detection pipeline.
    Detects face bounding box, ocular regions, and pupil/iris limbus circles.
    """
    if image_or_gray is None or image_or_gray.size == 0:
        return {
            'face_detected': False,
            'face_box': None,
            'eyes_detected': 0,
            'eyes': [],
            'irises': [],
            'iris_detected': False,
        }

    if image_or_gray.ndim == 3:
        gray = cv2.cvtColor(image_or_gray, cv2.COLOR_BGR2GRAY)
    else:
        gray = image_or_gray

    h, w = gray.shape
    min_sz = max(40, int(min(h, w) * 0.08))

    face_default = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    face_alt2 = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_alt2.xml")
    eye_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_eye.xml")
    glasses_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_eye_tree_eyeglasses.xml")

    # 1. Face detection (primary + alt2 fallback)
    min_face = max(70, int(min(h, w) * 0.18))
    faces = face_default.detectMultiScale(gray, 1.1, 4, minSize=(min_face, min_face))
    if len(faces) == 0:
        faces = face_alt2.detectMultiScale(gray, 1.1, 3, minSize=(min_face, min_face))

    face_box = None
    eyes = []

    if len(faces) > 0:
        faces = sorted(faces, key=lambda f: f[2] * f[3], reverse=True)
        fx, fy, fw, fh = faces[0]
        face_box = (int(fx), int(fy), int(fw), int(fh))

        # Restrict ocular search to upper anatomical band (18% - 58% of face)
        y0 = max(0, int(fy + 0.18 * fh))
        y1 = min(h, int(fy + 0.58 * fh))
        x0 = max(0, int(fx + 0.05 * fw))
        x1 = min(w, int(fx + 0.95 * fw))
        ocular_roi = gray[y0:y1, x0:x1]

        if ocular_roi.size > 0:
            eye_min = max(25, int(fw * 0.10))
            detected_in_face = eye_cascade.detectMultiScale(ocular_roi, 1.1, 4, minSize=(eye_min, eye_min))
            if len(detected_in_face) == 0:
                detected_in_face = glasses_cascade.detectMultiScale(ocular_roi, 1.1, 3, minSize=(eye_min, eye_min))
            for (ex, ey, ew, eh) in detected_in_face:
                eyes.append((x0 + ex, y0 + ey, ew, eh))

    if not eyes:
        # Fallback to direct eye detection across whole frame (for macro crops or occluded faces)
        detected = eye_cascade.detectMultiScale(gray, 1.1, 5, minSize=(min_sz, min_sz))
        if len(detected) == 0:
            detected = glasses_cascade.detectMultiScale(gray, 1.1, 3, minSize=(min_sz, min_sz))
        eyes = [tuple(e) for e in detected]

    eyes = sorted(eyes, key=lambda e: e[2] * e[3], reverse=True)[:2]
    eyes = sorted([tuple(e) for e in eyes], key=lambda e: e[0])

    # If eyes are present but face was not detected (e.g. mask or hijab), reconstruct upper face box
    if face_box is None and len(eyes) >= 2:
        e1, e2 = eyes[0], eyes[1]
        cx1, cy1 = e1[0] + e1[2] / 2.0, e1[1] + e1[3] / 2.0
        cx2, cy2 = e2[0] + e2[2] / 2.0, e2[1] + e2[3] / 2.0
        iod = np.hypot(cx2 - cx1, cy2 - cy1)
        est_fw = int(iod * 2.2)
        est_fh = int(est_fw * 1.3)
        est_fx = max(0, int((cx1 + cx2) / 2.0 - est_fw / 2.0))
        est_fy = max(0, int((cy1 + cy2) / 2.0 - 0.38 * est_fh))
        face_box = (est_fx, est_fy, min(w - est_fx, est_fw), min(h - est_fy, est_fh))

    # 2. Iris and Pupil localization for each detected eye
    irises = []
    for ex, ey, ew, eh in eyes:
        pad = int(0.15 * ew)
        crop = gray[max(0, ey - pad):min(h, ey + eh + pad), max(0, ex - pad):min(w, ex + ew + pad)]
        if crop.size > 0:
            scale = 1.0
            if crop.shape[1] < 300:
                scale = 300 / crop.shape[1]
                crop_sc = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
            else:
                crop_sc = crop
            iris = find_iris(crop_sc)
            pupil = find_pupil(crop_sc, iris)
            irises.append({
                'eye_box': (ex, ey, ew, eh),
                'iris_circle': (int(iris[0] / scale), int(iris[1] / scale), int(iris[2] / scale)),
                'pupil_circle': (int(pupil[0] / scale), int(pupil[1] / scale), int(pupil[2] / scale)),
            })

    return {
        'face_detected': face_box is not None,
        'face_box': face_box,
        'eyes_detected': len(eyes),
        'eyes': eyes,
        'irises': irises,
        'iris_detected': len(irises) > 0,
    }


def detect_eyes(gray):
    """
    Return list of (x, y, w, h) eye boxes sorted left->right.
    Preserves 100% backward compatibility for all pipeline callers.
    """
    return detect_face_and_iris(gray)['eyes']


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
    r_lo, r_hi = int(0.10 * w), int(0.35 * w)
    circles = cv2.HoughCircles(blur, cv2.HOUGH_GRADIENT, dp=1.2,
                               minDist=w // 8, param1=80, param2=18,
                               minRadius=r_lo, maxRadius=r_hi)
    if circles is None:
        # Fallback to lower threshold for soft ambient smartphone lighting
        circles = cv2.HoughCircles(blur, cv2.HOUGH_GRADIENT, dp=1.2,
                                   minDist=w // 8, param1=60, param2=14,
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
        return int(xs.mean()), int(ys.mean()), min(int(0.40 * w), max(r_lo, int(np.sqrt(len(xs) / np.pi) * 1.8)))
    return best


def find_pupil(eye_gray, iris):
    """Pupil = darkest compact region inside the iris disk."""
    ix, iy, ir = iris
    h, w = eye_gray.shape
    blur = cv2.GaussianBlur(eye_gray, (7, 7), 0)
    yy, xx = np.mgrid[:h, :w]
    disk = np.hypot(xx - ix, yy - iy) < 0.7 * ir
    vals = blur[disk]
    if vals.size == 0:
        return ix, iy, int(0.35 * ir)
    thr = np.percentile(vals, 30)
    m = ((blur <= thr) & disk).astype(np.uint8) * 255
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return ix, iy, int(0.35 * ir)
    c = max(cnts, key=cv2.contourArea)
    M = cv2.moments(c)
    if M["m00"] > 0:
        cx, cy = int(M["m10"] / M["m00"]), int(M["m01"] / M["m00"])
    else:
        (cx, cy), _ = cv2.minEnclosingCircle(c)
        cx, cy = int(cx), int(cy)
    _, r = cv2.minEnclosingCircle(c)
    if np.hypot(cx - ix, cy - iy) > 0.3 * ir:
        cx, cy = ix, iy
    r = int(np.clip(r, 0.2 * ir, 0.5 * ir))   # physiological limits
    return cx, cy, r


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
    m[:, int(NORM_W * 0.20):int(NORM_W * 0.30)] = 0
    m[:, int(NORM_W * 0.70):int(NORM_W * 0.80)] = 0
    return m


def enhance(polar):
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(4, 16))
    return clahe.apply(polar)


# --------------------------------------------------------------------------
# 4. Feature encoding (Gabor -> IrisCode)
# --------------------------------------------------------------------------
@functools.lru_cache(maxsize=1)
def gabor_bank(ksize=(9, 31), wavelengths=(8, 16)):
    bank = []
    for lam in wavelengths:
        sigma = lam * 0.56
        k = cv2.getGaborKernel(ksize, sigma, 0, lam, 1.0, 0, ktype=cv2.CV_32F)
        k_im = cv2.getGaborKernel(ksize, sigma, 0, lam, 1.0, np.pi / 2,
                                  ktype=cv2.CV_32F)
        bank.append((k, k_im))
    return tuple(bank)


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


def hamming(code1, mask1, code2, mask2, max_shift=16):
    """Normalised Hamming distance with circular shift for rotation tolerance."""
    best = 1.0
    for s in range(-max_shift, max_shift + 1):
        c2 = np.roll(code2, s, 1)
        m2 = np.roll(mask2, s, 1)
        both = mask1 & m2
        both_count = np.count_nonzero(both)
        if both_count < 64:
            continue
        diff_count = np.count_nonzero((code1 ^ c2) & both)
        score = diff_count / both_count
        if score < best:
            best = score
    return float(best)


# --------------------------------------------------------------------------
# 5. Facial and Periocular Multi-Feature Processing
# --------------------------------------------------------------------------
def extract_facial_features(image_bgr_or_gray, eyes=None):
    """
    Extract complementary facial and periocular features:
      1. Facial geometry: Inter-ocular distance ratio, facial tilt angle, and relative eye size.
      2. Periocular texture: 256-D gradient orientation descriptor covering eyebrow, eye contour,
         and orbital margin.
    Returns a normalized 259-D np.float32 vector, or None if eye localization is impossible.
    """
    if image_bgr_or_gray is None or image_bgr_or_gray.size == 0:
        return None

    if image_bgr_or_gray.ndim == 3:
        gray = cv2.cvtColor(image_bgr_or_gray, cv2.COLOR_BGR2GRAY)
    else:
        gray = image_bgr_or_gray

    h, w = gray.shape

    if eyes is None or len(eyes) == 0:
        eyes = detect_eyes(gray)

    if not eyes:
        return None

    eyes = sorted(eyes, key=lambda e: e[0])  # sort left to right

    # Facial geometry feature vector (3 elements)
    geo_features = []
    face_cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    )
    faces = face_cascade.detectMultiScale(gray, 1.1, 4, minSize=(60, 60))
    face_box = faces[0] if len(faces) > 0 else None

    ref_w = float(face_box[2]) if face_box is not None else float(w)
    ref_h = float(face_box[3]) if face_box is not None else float(h)

    if len(eyes) >= 2:
        e1, e2 = eyes[0], eyes[1]
        c1 = (e1[0] + e1[2] / 2.0, e1[1] + e1[3] / 2.0)
        c2 = (e2[0] + e2[2] / 2.0, e2[1] + e2[3] / 2.0)
        dx = c2[0] - c1[0]
        dy = c2[1] - c1[1]
        interocular_dist = np.hypot(dx, dy)
        interocular_ratio = interocular_dist / max(1.0, ref_w)
        tilt_angle = np.arctan2(dy, max(1.0, dx))  # tilt in radians
        avg_eye_ratio = ((e1[2] + e2[2]) / 2.0) / max(1.0, ref_w)
        geo_features = [interocular_ratio, tilt_angle, avg_eye_ratio]
    else:
        e = eyes[0]
        geo_features = [0.0, 0.0, float(e[2]) / max(1.0, ref_w)]

    # Periocular texture descriptor (256 elements)
    # Target largest/primary eye box
    primary_eye = sorted(eyes, key=lambda e: e[2] * e[3], reverse=True)[0]
    px, py, pw, ph = primary_eye

    pad_t = int(0.35 * ph)
    pad_b = int(0.20 * ph)
    pad_s = int(0.25 * pw)

    y_start = max(0, py - pad_t)
    y_end = min(h, py + ph + pad_b)
    x_start = max(0, px - pad_s)
    x_end = min(w, px + pw + pad_s)

    peri_roi = gray[y_start:y_end, x_start:x_end]
    if peri_roi.size > 0:
        peri_resized = cv2.resize(peri_roi, (64, 32))
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4, 4))
        peri_enh = clahe.apply(peri_resized)

        gx = cv2.Sobel(peri_enh, cv2.CV_32F, 1, 0, ksize=3)
        gy = cv2.Sobel(peri_enh, cv2.CV_32F, 0, 1, ksize=3)
        mag, ang = cv2.cartToPolar(gx, gy, angleInDegrees=True)

        n_bins = 8
        hists = []
        for r in range(4):
            for c in range(8):
                c_mag = mag[r * 8:(r + 1) * 8, c * 8:(c + 1) * 8]
                c_ang = ang[r * 8:(r + 1) * 8, c * 8:(c + 1) * 8]
                b_idx = (c_ang / 45.0).astype(np.int32) % n_bins
                hist = np.zeros(n_bins, dtype=np.float32)
                for b in range(n_bins):
                    hist[b] = np.sum(c_mag[b_idx == b])
                hists.append(hist)
        tex_vec = np.concatenate(hists)
        t_norm = np.linalg.norm(tex_vec)
        if t_norm > 1e-6:
            tex_vec /= t_norm
    else:
        tex_vec = np.zeros(256, dtype=np.float32)

    # Dense multi-zone Macro Face Structure descriptor (177 elements)
    # Extracts multi-zone anatomical structures: forehead/brow, left/right eye orbits,
    # nasal bridge, cheekbones, and lower facial contours.
    if face_box is not None:
        fx, fy, fw, fh = face_box
    elif len(eyes) >= 2:
        e1, e2 = eyes[0], eyes[1]
        min_x = min(e1[0], e2[0])
        max_x = max(e1[0] + e1[2], e2[0] + e2[2])
        span = max_x - min_x
        fx = max(0, int(min_x - 0.25 * span))
        fw = min(w - fx, int(span * 1.5))
        fy = max(0, int(min(e1[1], e2[1]) - 0.5 * e1[3]))
        fh = min(h - fy, int(fw * 1.2))
    else:
        e = eyes[0]
        fx = max(0, int(e[0] - 0.75 * e[2]))
        fw = min(w - fx, int(2.5 * e[2]))
        fy = max(0, int(e[1] - 0.5 * e[3]))
        fh = min(h - fy, int(2.5 * e[3]))

    face_crop = gray[fy:fy + fh, fx:fx + fw]
    if face_crop.size > 0:
        face_norm = cv2.resize(face_crop, (96, 96), interpolation=cv2.INTER_AREA)
        clahe_face = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(6, 6))
        face_enh = clahe_face.apply(face_norm)

        # 6 anatomical structural zones:
        zones = [
            face_enh[0:24, :],       # Brow / Forehead band
            face_enh[24:54, 0:48],   # Left eye / orbital contour
            face_enh[24:54, 48:96],  # Right eye / orbital contour
            face_enh[35:70, 30:66],  # Nasal bridge & root
            face_enh[54:80, :],      # Mid-face & zygomatic arches
            face_enh[80:96, :],      # Lower face & chin
        ]
        zone_descriptors = []
        for z in zones:
            zgx = cv2.Sobel(z, cv2.CV_32F, 1, 0, ksize=3)
            zgy = cv2.Sobel(z, cv2.CV_32F, 0, 1, ksize=3)
            zmag, zang = cv2.cartToPolar(zgx, zgy, angleInDegrees=True)
            zb_idx = (zang / 45.0).astype(np.int32) % 8
            zhist = np.zeros(8, dtype=np.float32)
            for b in range(8):
                zhist[b] = np.sum(zmag[zb_idx == b])
            znorm = np.linalg.norm(zhist)
            if znorm > 1e-6:
                zhist /= znorm
            zone_descriptors.append(zhist)

        # 4x4 spatial grid gradient descriptors across full face
        grid_descriptors = []
        for r in range(4):
            for c in range(4):
                cell = face_enh[r * 24:(r + 1) * 24, c * 24:(c + 1) * 24]
                cgx = cv2.Sobel(cell, cv2.CV_32F, 1, 0, ksize=3)
                cgy = cv2.Sobel(cell, cv2.CV_32F, 0, 1, ksize=3)
                cmag, cang = cv2.cartToPolar(cgx, cgy, angleInDegrees=True)
                cb_idx = (cang / 45.0).astype(np.int32) % 8
                chist = np.zeros(8, dtype=np.float32)
                for b in range(8):
                    chist[b] = np.sum(cmag[cb_idx == b])
                cnorm = np.linalg.norm(chist)
                if cnorm > 1e-6:
                    chist /= cnorm
                grid_descriptors.append(chist)

        aspect_feat = np.array([float(fw) / max(1.0, float(fh))], dtype=np.float32)
        struct_vec = np.concatenate([aspect_feat] + zone_descriptors + grid_descriptors)
    else:
        struct_vec = np.zeros(177, dtype=np.float32)

    full_vector = np.concatenate([np.array(geo_features, dtype=np.float32), tex_vec, struct_vec])
    return full_vector.astype(np.float32)


def compare_facial_features(feat_a, feat_b):
    """
    Compute normalized biometric distance between two facial/periocular feature vectors.
    Supports both legacy (259-D) and enhanced dense face structure (436-D) templates.
    Returns float in [0.0, 1.0].
    """
    if feat_a is None or feat_b is None:
        return None
    fa = np.asarray(feat_a, dtype=np.float32).flatten()
    fb = np.asarray(feat_b, dtype=np.float32).flatten()
    if fa.size < 4 or fb.size < 4:
        return None

    geo_a, tex_a = fa[:3], fa[3:259]
    geo_b, tex_b = fb[:3], fb[3:259]

    # Periocular texture cosine distance
    norm_a = np.linalg.norm(tex_a)
    norm_b = np.linalg.norm(tex_b)
    if norm_a > 1e-6 and norm_b > 1e-6:
        cos_sim = float(np.dot(tex_a, tex_b) / (norm_a * norm_b))
        d_tex = max(0.0, min(1.0, (1.0 - cos_sim)))
    else:
        d_tex = 0.5

    # Geometric ratios distance (only valid when BOTH captures detected 2 eyes)
    has_two_eyes_a = geo_a[0] > 0.05
    has_two_eyes_b = geo_b[0] > 0.05

    d_geo = None
    if has_two_eyes_a and has_two_eyes_b:
        d_geo_val = float(np.linalg.norm(geo_a - geo_b))
        d_geo = min(1.0, d_geo_val * 1.5)

    # Dense Macro Face Structure distance (when available in both vectors)
    d_struct = None
    if fa.size >= 436 and fb.size >= 436:
        struct_a = fa[259:436]
        struct_b = fb[259:436]
        aspect_diff = abs(float(struct_a[0]) - float(struct_b[0]))
        desc_a = struct_a[1:]
        desc_b = struct_b[1:]
        sn_a = np.linalg.norm(desc_a)
        sn_b = np.linalg.norm(desc_b)
        if sn_a > 1e-6 and sn_b > 1e-6:
            s_cos = float(np.dot(desc_a, desc_b) / (sn_a * sn_b))
            d_struct_cos = max(0.0, min(1.0, 1.0 - s_cos))
        else:
            d_struct_cos = 0.5
        raw_struct = float(0.85 * d_struct_cos + 0.15 * min(1.0, aspect_diff * 2.0))
        d_struct = min(1.0, raw_struct * 3.0)

    # Composite multi-level fusion:
    if d_struct is not None:
        if d_geo is not None:
            fused_dist = 0.50 * d_struct + 0.35 * d_tex + 0.15 * d_geo
        else:
            fused_dist = 0.60 * d_struct + 0.40 * d_tex
    else:
        if d_geo is not None:
            fused_dist = 0.75 * d_tex + 0.25 * d_geo
        else:
            fused_dist = d_tex

    return float(max(0.0, min(1.0, fused_dist)))


# --------------------------------------------------------------------------
# Driver
# --------------------------------------------------------------------------
def process_eye(eye_bgr, tag, out_dir=None):
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

    if out_dir is not None:
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
