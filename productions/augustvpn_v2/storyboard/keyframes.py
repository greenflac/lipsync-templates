"""Ключевые кадры раскадровки v2: H3 ref2va, короткие отрывки (22 кадра), те же рефы."""

import dataclasses
import json
import subprocess
import sys
import time
from pathlib import Path

import requests

from studio.shoot.compile import compile_shot
from studio.shoot.h3graph import build
from studio.shoot.spec import Beat, Placement, Shot, load

URL = "https://95ukq3ajnnl2f3-8188.proxy.runpod.net"
OUT = Path(sys.argv[1])
ONLY = set(sys.argv[2:])
prod = load("productions/augustvpn_main_event/production.json")


def P(who, screen, faces):
    return Placement(who, screen, faces)


def shot(i, scene, rig, framing, blocking, action, camera, seed, sound="Arena ambience, the crowd murmuring."):
    return Shot(
        id=f"K{i:02d}", scene=scene, seconds=5, rig=rig, framing=framing, blocking=tuple(blocking),
        beats=(Beat(0, "action", action), Beat(0.2, "camera", camera)), soundscape=sound, seed=seed,
    )


SHOTS = [
    shot(1, "octagon", "high_wide_tele", "very wide high shot over the packed dark arena toward the brightly lit octagon",
         [P("announcer", "center", "camera")],
         "Spotlights sweep through haze over the crowd, pyrotechnic sparks fountain up around the cage; {announcer} stands tiny in the center of the octagon.",
         "The operator tilts down from the lighting rig over the crowd to the octagon; no camera equipment is visible in the frame.", 102),
    shot(2, "announce", "steadicam_orbit", "medium shot of the announcer in the center of the octagon, the cage and the dark crowd behind him",
         [P("announcer", "center", "camera")],
         "{announcer} raises the microphone to his lips and sweeps his free arm toward the stands.",
         "The Steadicam operator arcs slowly around him, keeping him framed.", 13),
    shot(3, "octagon", "cage_side_tele", "telephoto waist-up shot of the fighter standing in his corner of the octagon, the black cage padding behind him",
         [P("august", "center", "right")],
         "{august} stands calmly in his corner, rolls his neck and looks across the octagon at his opponent with a faint smile.",
         "The operator holds the telephoto frame with small manual zoom adjustments.", 42),
    shot(4, "octagon", "in_cage_handheld", "low-angle medium shot from below of the giant fighter in his corner, he fills the frame",
         [P("adgar", "center", "camera")],
         "{adgar} pounds his chest with both fists and roars at the crowd.",
         "The operator crouches low and tilts up at him, steadying the shoulder camera.", 33),
    shot(5, "octagon", "cage_side_tele", "tight telephoto waist-up shot through the cage fence: the two fighters face to face, the referee between them",
         [P("august", "left", "right"), P("referee", "center", "camera"), P("adgar", "right", "left")],
         "{august} looks up into the eyes of {adgar}, who looms over him; {referee} holds both hands between their chests. The canvas carries only the SECURITY ARENA marking, no other words.",
         "The operator holds the tight two-shot through the fence.", 53),
    shot(6, "octagon", "high_wide_tele", "wide high shot of the whole octagon from the main camera platform behind the cage",
         [P("august", "left", "right"), P("referee", "center", "camera"), P("adgar", "right", "left")],
         "The fighters stand in their corners ready, {referee} in the center drops his hand to start the round. The canvas carries only the SECURITY ARENA marking, no other words.",
         "The operator holds the wide frame with a slight pan.", 62),
    shot(7, "octagon", "high_wide_tele", "wide high shot of the octagon from the main camera platform behind the cage",
         [P("august", "left", "right"), P("referee", "center", "right"), P("adgar", "right", "left")],
         "{august} bounces lightly on his toes in the center; {adgar} stands perfectly still in his fighting stance near his corner, frozen; {referee} walks up to {adgar} and waves a hand in front of his face.",
         "The operator pans slightly toward {adgar} and zooms in a little.", 71),
    shot(8, "octagon", "high_wide_tele", "wide high shot of the octagon from the main camera platform behind the cage",
         [P("august", "left", "right"), P("referee", "center", "right"), P("adgar", "right", "left")],
         "{adgar} topples backward stiff as a plank, halfway down to the canvas, arms still up in his stance; {august} and {referee} step back in surprise.",
         "The operator follows the fall with a quick tilt down.", 81),
    shot(9, "octagon", "high_wide_tele", "wide high shot of the octagon from the main camera platform behind the cage",
         [P("august", "left", "right"), P("referee", "center", "right"), P("adgar", "right", "camera")],
         "{adgar} lies flat on his back on the canvas, completely still; {referee} stands over him; {august} looks down at him.",
         "The operator holds the wide frame.", 91),
    shot(10, "octagon", "in_cage_handheld", "close-up of the fighter's face inside the cage after the fight",
         [P("august", "center", "left")],
         "{august} looks down at the canvas and raises one eyebrow ironically.",
         "The operator steps in close and reframes on his face.", 104),
    shot(11, "booth", "booth_locked", "medium two-shot of the two commentators at their desk, the glowing cage visible through the booth glass behind them",
         [P("caster_a", "left", "right"), P("caster_b", "right", "camera")],
         "{caster_a} holds his forehead and shakes his head; {caster_b} speaks drily into his headset microphone.",
         "Static framing.", 111, "A quiet commentary booth, muffled arena noise through the glass."),
]

OUT.mkdir(parents=True, exist_ok=True)
uploaded: dict[str, str] = {}
jobs = {}
for s in SHOTS:
    if ONLY and s.id not in ONLY:
        continue
    c = compile_shot(prod, s)
    for ref in c.refs:
        if ref not in uploaded:
            p = Path("productions/augustvpn_main_event") / ref if not Path(ref).exists() else Path(ref)
            r = requests.post(f"{URL}/upload/image", files={"image": (p.name, p.read_bytes())}, data={"overwrite": "true"}, timeout=120)
            uploaded[ref] = r.json()["name"]
    g = build(c, f"sb/{s.id}", uploaded=uploaded,
              unet="minimax_h3_ref2va_pruned_fp8_scaled.safetensors",
              clip="qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors")
    g["10"]["inputs"]["length"] = 22
    r = requests.post(f"{URL}/prompt", json={"prompt": g}, timeout=60).json()
    jobs[s.id] = r.get("prompt_id")
    (OUT / f"{s.id}.prompt.txt").write_text(c.prompt, encoding="utf-8")
    print(s.id, "queued", r.get("prompt_id"), r.get("node_errors") or "")

t0 = time.time()
pending = dict(jobs)
while pending and time.time() - t0 < 3600:
    for sid, pid in list(pending.items()):
        h = requests.get(f"{URL}/history/{pid}", timeout=60).json()
        if pid not in h:
            continue
        st = h[pid]["status"]
        vids = [v for n in h[pid]["outputs"].values() for v in n.get("images", []) + n.get("videos", [])]
        for v in vids:
            data = requests.get(f"{URL}/view", params={"filename": v["filename"], "subfolder": v.get("subfolder", ""), "type": v.get("type", "output")}, timeout=300).content
            (OUT / f"{sid}.mp4").write_bytes(data)
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-sseof", "-0.05", "-i", str(OUT / f"{sid}.mp4"), "-frames:v", "1", str(OUT / f"{sid}.jpg")])
        print(sid, st.get("status_str"), round(time.time() - t0), "s", "" if vids else json.dumps(st.get("messages", [])[-1:])[:400], flush=True)
        del pending[sid]
    time.sleep(10)
