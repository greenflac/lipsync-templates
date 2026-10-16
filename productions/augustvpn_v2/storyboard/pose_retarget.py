"""Поза из эфирной записи, подогнанная под утверждённый ключевой кадр.

Снимает скелет (DWPose через rtmlib) с отрезка эфира и с ключевого кадра,
подбирает масштаб и сдвиг так, чтобы плечи и бёдра первого кадра записи
легли на плечи и бёдра персонажа в ключевом кадре, и рисует видео скелета
768x1344, 24 к/с — вход control_video для Fun ControlNet Union.

    python pose_retarget.py SRC.mp4 KEYFRAME.jpg OUT.mp4 FRAMES
"""

import sys

import cv2
import numpy as np
from rtmlib import Wholebody, draw_skeleton

src, kf_path, out, n_out = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
W, H = 768, 1344
ANCHORS = [1, 2, 5, 8, 11]  # шея, плечи, бёдра (OpenPose-18)

model = Wholebody(mode="performance", to_openpose=True, backend="onnxruntime", device="cuda")


def biggest(k, s):
    areas = [np.ptp(kk[ss > 0.3][:, 0]) * np.ptp(kk[ss > 0.3][:, 1]) if (ss > 0.3).sum() > 4 else 0 for kk, ss in zip(k, s)]
    i = int(np.argmax(areas))
    return k[i], s[i]


kf = cv2.resize(cv2.imread(kf_path), (W, H))
kk, ks = biggest(*model(kf))

cap = cv2.VideoCapture(src)
seq = []
while len(seq) < n_out:
    ok, f = cap.read()
    if not ok:
        break
    seq.append(biggest(*model(f)))
while len(seq) < n_out:  # короче нужного — держим последний кадр
    seq.append(seq[-1])

r0, rs0 = seq[0]
use = [j for j in ANCHORS if ks[j] > 0.3 and rs0[j] > 0.3]
a, b = r0[use], kk[use]
ca, cb = a.mean(0), b.mean(0)
scale = np.sqrt(((b - cb) ** 2).sum() / ((a - ca) ** 2).sum())
shift = cb - ca * scale
print(f"anchors {use} scale {scale:.3f} shift {shift.round(1)}")

vw = cv2.VideoWriter(out, cv2.VideoWriter_fourcc(*"mp4v"), 24, (W, H))
pv = cv2.VideoWriter(out.replace(".mp4", "_check.mp4"), cv2.VideoWriter_fourcc(*"mp4v"), 24, (W, H))
for k, s in seq:
    p = k * scale + shift
    vw.write(draw_skeleton(np.zeros((H, W, 3), np.uint8), p[None], s[None], openpose_skeleton=True, kpt_thr=0.3))
    pv.write(draw_skeleton(kf.copy(), p[None], s[None], openpose_skeleton=True, kpt_thr=0.3))
vw.release()
pv.release()
print("frames", len(seq))
