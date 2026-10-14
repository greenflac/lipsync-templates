"""Поза нескольких людей из эфира, подогнанная под утверждённый ключевой кадр.

Как pose_retarget.py, но для сцены с N людьми (бойцы и рефери). Люди
сопоставляются слева направо: k-й слева в записи — k-й слева в кадре. Каждый
подгоняется своим масштабом и сдвигом по шее, плечам и бёдрам, поэтому
разница в росте персонажей сохраняется, даже если в записи люди одного роста.
Между кадрами люди ведутся по ближайшему центру тела.

    python pose_retarget_multi.py SRC.mp4 KEYFRAME.jpg OUT.mp4 FRAMES N
"""

import sys

import cv2
import numpy as np
from rtmlib import Wholebody, draw_skeleton

src, kf_path, out, n_out, N = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4]), int(sys.argv[5])
W, H = 768, 1344
ANCHORS = [1, 2, 5, 8, 11]
model = Wholebody(mode="performance", to_openpose=True, backend="onnxruntime", device="cuda")


def people(img):
    k, s = model(img)
    area = [np.ptp(kk[ss > 0.3][:, 0]) * np.ptp(kk[ss > 0.3][:, 1]) if (ss > 0.3).sum() > 4 else 0 for kk, ss in zip(k, s)]
    top = np.argsort(area)[::-1][:N]
    top = sorted(top, key=lambda i: np.median(k[i][s[i] > 0.3][:, 0]))  # слева направо
    return [k[i] for i in top], [s[i] for i in top]


def center(k, s):
    v = k[s > 0.3]
    return v.mean(0) if len(v) else np.array([np.nan, np.nan])


kf = cv2.resize(cv2.imread(kf_path), (W, H))
kk, ks = people(kf)

cap = cv2.VideoCapture(src)
frames = []
while len(frames) < n_out:
    ok, f = cap.read()
    if not ok:
        break
    frames.append(f)

# первый кадр: порядок слева направо; дальше — ведение по ближайшему центру
k0, s0 = people(frames[0])
tracks = [[(k0[j], s0[j])] for j in range(N)]
for f in frames[1:]:
    k, s = model(f)
    used = set()
    for j in range(N):
        prev = center(*tracks[j][-1])
        best, bd = None, 1e9
        for i in range(len(k)):
            if i in used:
                continue
            d = np.linalg.norm(center(k[i], s[i]) - prev)
            if d < bd:
                best, bd = i, d
        if best is None or bd > 250:
            tracks[j].append(tracks[j][-1])
        else:
            used.add(best)
            tracks[j].append((k[best], s[best]))
for t in tracks:
    while len(t) < n_out:
        t.append(t[-1])

xf = []
for j in range(N):
    a0, as0 = tracks[j][0]
    use = [i for i in ANCHORS if ks[j][i] > 0.3 and as0[i] > 0.3]
    a, b = a0[use], kk[j][use]
    ca, cb = a.mean(0), b.mean(0)
    sc = np.sqrt(((b - cb) ** 2).sum() / max(((a - ca) ** 2).sum(), 1e-6))
    xf.append((sc, cb - ca * sc))
    print(f"person {j}: anchors {use} scale {sc:.3f}")

vw = cv2.VideoWriter(out, cv2.VideoWriter_fourcc(*"mp4v"), 24, (W, H))
pv = cv2.VideoWriter(out.replace(".mp4", "_check.mp4"), cv2.VideoWriter_fourcc(*"mp4v"), 24, (W, H))
for t in range(n_out):
    P = np.stack([tracks[j][t][0] * xf[j][0] + xf[j][1] for j in range(N)])
    S = np.stack([tracks[j][t][1] for j in range(N)])
    vw.write(draw_skeleton(np.zeros((H, W, 3), np.uint8), P, S, openpose_skeleton=True, kpt_thr=0.3))
    pv.write(draw_skeleton(kf.copy(), P, S, openpose_skeleton=True, kpt_thr=0.3))
vw.release()
pv.release()
print("frames", n_out)
