"""Choose the 9:16 framing from what is actually in the shot (approach from openshorts' camera_inset).

- webcam inset in a corner (gameplay / trading screen + facecam): screen on top, the camera enlarged below;
- a person filling the shot (IRL, podcast): full-screen 9:16 crop that follows the main person;
- "blur" variant (or nobody found): the whole 16:9 frame over a blurred copy of itself.
Half the clips use each style (A/B test); the manifest records which one so views can be compared.
Face detection is OpenCV's YuNet (MIT, 230 KB), so no GPU or extra download is needed.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODEL = ROOT / "assets" / "models" / "face_detection_yunet_2023mar.onnx"
OUT_W, OUT_H = 1080, 1920

CORNER_OFFSET = 0.18      # inset face sits at least this far left/right of centre (fraction of width)
MAX_INSET_FACE_H = 0.22   # an inset face is small; a talking head is not
MAX_CENTRE_SPREAD = 0.05  # an inset is pinned; a presenter moves
INSET_PAD = 2.6           # face box -> webcam box (head + shoulders)


def _faces(frame, detector):
    h, w = frame.shape[:2]
    detector.setInputSize((w, h))
    _, found = detector.detect(frame)
    if found is None:
        return []
    return [(float(f[0]), float(f[1]), float(f[2]), float(f[3]), float(f[14])) for f in found]


def _pick_main(faces: list, prev_cx: float | None, w: float):
    """The person who matters: the biggest face, but stay on the one we were following while it is still
    a comparable size, so the crop does not ping-pong between two people."""
    biggest = max(faces, key=lambda f: f[2] * f[3])
    if prev_cx is not None:
        near = [f for f in faces if abs(f[0] + f[2] / 2 - prev_cx) < 0.12 * w]
        if near:
            cand = max(near, key=lambda f: f[2] * f[3])
            if cand[2] * cand[3] >= 0.55 * biggest[2] * biggest[3]:
                return cand
    return biggest


def _smooth(track: list[tuple[float, float]], w: float) -> list[tuple[float, float]]:
    """Moving average + dead zone: a steady camera that only moves when the person really moves."""
    if not track:
        return track
    xs = [c for _, c in track]
    avg = [sum(xs[max(0, i - 2):i + 3]) / len(xs[max(0, i - 2):i + 3]) for i in range(len(xs))]
    out, cur = [], avg[0]
    for (t, _), a in zip(track, avg):
        if abs(a - cur) > 0.04 * w:
            cur = a
        out.append((t, cur))
    return out


def analyse(video: str, start: float, end: float, step: float = 0.5) -> dict:
    """Detect faces every `step` s between start and end (source seconds).

    Returns {'kind': 'inset'|'face'|'none', 'w', 'h', 'box' (inset px), 'track' [(t_abs, cx)]}.
    """
    import cv2
    import numpy as np

    cap = cv2.VideoCapture(video)
    w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    info = {"kind": "none", "w": w, "h": h}
    if not w or not MODEL.exists():
        cap.release()
        return info
    scale = min(1.0, 1280 / w)  # detect at <=1280 px wide: fast, still finds facecam-sized faces
    sw, sh = int(w * scale), int(h * scale)
    det = cv2.FaceDetectorYN.create(str(MODEL), "", (sw, sh), 0.6, 0.3, 50)
    hits, prev, samples = [], None, 0
    t = start
    while t < end:
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, frame = cap.read()
        t_now = t
        t += step
        if not ok:
            continue
        samples += 1
        faces = [(x / scale, y / scale, fw / scale, fh / scale, sc)
                 for x, y, fw, fh, sc in _faces(cv2.resize(frame, (sw, sh)) if scale < 1 else frame, det)]
        if faces:
            x, y, fw, fh, _ = _pick_main(faces, prev, w)
            prev = x + fw / 2
            hits.append((t_now, x, y, fw, fh))
    cap.release()
    if len(hits) < max(3, samples // 3):
        return info

    arr = np.array([hh[1:] for hh in hits])
    cx = arr[:, 0] + arr[:, 2] / 2
    cy = arr[:, 1] + arr[:, 3] / 2
    face_h = float(np.median(arr[:, 3])) / h
    offset = abs(float(np.median(cx)) / w - 0.5)
    mid_x, mid_y = np.median(cx), np.median(cy)
    pinned = float(np.mean((np.abs(cx - mid_x) < MAX_CENTRE_SPREAD * w) & (np.abs(cy - mid_y) < MAX_CENTRE_SPREAD * w)))
    if face_h <= MAX_INSET_FACE_H and offset >= CORNER_OFFSET and pinned >= 0.7:
        fx, fy, fw, fh = (float(np.median(arr[:, k])) for k in range(4))
        bw, bh = fw * INSET_PAD * 1.25, fh * INSET_PAD
        bx = min(max(0, fx + fw / 2 - bw / 2), w - bw)
        by = min(max(0, fy + fh / 2 - bh / 2.4), h - bh)
        info.update(kind="inset", box=(int(bx), int(by), int(bw), int(bh)))
        return info
    info.update(kind="face", track=_smooth([(hh[0], float(c)) for hh, c in zip(hits, cx)], w))
    return info


def _even(v: float) -> int:
    v = int(round(v))
    return v - v % 2


def filtergraph(info: dict, inp: str = "[0:v]", out: str = "[base]", t_off: float = 0.0, t_end: float = 1e9,
                sfx: str = "", style: str = "vertical") -> str:
    """Graph from `inp` to `out` (1080x1920, sharpened and graded).

    style "vertical": full-screen 9:16 (webcam stack for facecam streams, person-tracking crop otherwise).
    style "blur": the whole horizontal frame centred over a blurred, darkened copy of itself.
    `t_off`/`t_end` are the source times this trimmed input covers (it restarts at t=0), so the face track
    stays aligned; `sfx` keeps internal labels unique when several segments are built.
    """
    w, h = info["w"] or 1920, info["h"] or 1080
    grade = "unsharp=5:5:0.9:3:3:0.3,eq=contrast=1.07:saturation=1.22:gamma=0.98"
    if style == "blur":
        bg = (f"scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=increase,crop={OUT_W}:{OUT_H},"
              "boxblur=30:3,eq=brightness=-0.15:saturation=1.3")
        return (f"{inp}split=2[a{sfx}][b{sfx}];[a{sfx}]{bg}[bg{sfx}];"
                f"[b{sfx}]scale={OUT_W}:-2:flags=lanczos,{grade}[fg{sfx}];"
                f"[bg{sfx}][fg{sfx}]overlay=(W-w)/2:(H-h)/2{out}")
    if info["kind"] == "inset":
        x, y, bw, bh = info["box"]
        cam_h = min(_even(OUT_W * bh / bw), _even(OUT_H * 0.42))
        # Widen the crop to the band's aspect so the scale stays uniform (no stretched faces).
        aspect = OUT_W / cam_h
        if bw / bh < aspect:
            nw = min(w, bh * aspect)
            x, bw = x + bw / 2 - nw / 2, nw
        else:
            nh = min(h, bw / aspect)
            y, bh = y + bh / 2 - nh / 2, nh
        x, y = max(0, min(x, w - bw)), max(0, min(y, h - bh))
        # Screen band: centre crop slightly zoomed so HUD text reads on a phone.
        scr_h = OUT_H - cam_h
        scr_crop_w = min(w, h * OUT_W / scr_h)
        return (f"{inp}split=2[s{sfx}][c{sfx}];"
                f"[s{sfx}]crop={_even(scr_crop_w)}:{_even(h)}:(iw-{_even(scr_crop_w)})/2:0,"
                f"scale={OUT_W}:{scr_h}:force_original_aspect_ratio=increase:flags=lanczos,crop={OUT_W}:{scr_h},{grade}[scr{sfx}];"
                f"[c{sfx}]crop={_even(bw)}:{_even(bh)}:{_even(x)}:{_even(y)},scale={OUT_W}:{cam_h}:flags=lanczos,{grade}[cam{sfx}];"
                f"[scr{sfx}][cam{sfx}]vstack=inputs=2{out}")
    crop_w = _even(h * OUT_W / OUT_H)
    if info["kind"] == "face":
        # 9:16 column that follows the main person; positions interpolated between samples of this segment.
        pts = [p for p in sorted(info["track"]) if t_off - 1 <= p[0] <= t_end + 1] or sorted(info["track"])
        xs = [min(max(0, c - crop_w / 2), w - crop_w) for _, c in pts]
        tt = f"(t+{t_off:.2f})"
        expr = f"{xs[-1]:.0f}"
        for (t0, _), (t1, _), x0, x1 in reversed(list(zip(pts, pts[1:], xs, xs[1:]))):
            expr = f"if(lt({tt},{t1:.2f}),{x0:.0f}+({x1 - x0:.0f})*({tt}-{t0:.2f})/{max(t1 - t0, 0.01):.2f},{expr})"
        expr = f"if(lt({tt},{pts[0][0]:.2f}),{xs[0]:.0f},{expr})"
    else:
        expr = f"{(w - crop_w) / 2:.0f}"  # nobody detected: centre column
    return (f"{inp}crop={crop_w}:{_even(h)}:'{expr}':0,"
            f"scale={OUT_W}:{OUT_H}:flags=lanczos,{grade}{out}")
