"""Финальный рендер v2: каждый план — H3 FL2VA от утверждённого ключевого кадра.

Формат промпта — как в примере вендора для first-frame режима (карточка
MiniMaxAI/MiniMax-H3): преамбула «<Picture 1> … is fully referenced», затем
integrated_multimodal_description, overall_soundscape, non_diegetic_music;
реплики — тегом <d>[English] …</d>.

    python render_final.py OUT_DIR [S05 S07 ...]
"""

import json
import subprocess
import sys
import time
from pathlib import Path

import requests

URL = "https://95ukq3ajnnl2f3-8188.proxy.runpod.net"
SB = Path(__file__).parent
KF = Path("/tmp/claude-0/-home-user-lipsync-templates/1e036219-dc10-53a7-8a45-91e1fc6e693e/scratchpad/sb")
OUT = Path(sys.argv[1])
ONLY = set(sys.argv[2:])

AUG = "the lean blond fighter with a very short buzzcut in the black fight jersey with the yellow АвгустVPN print"
ADG = "the giant bearded super-heavyweight in the dark red and black fight jersey with the white freevpn print"
REF = "the bald referee in black"
LOOK = ("This is real live pay-per-view MMA broadcast footage, not a commercial: bright even overhead TV lighting, "
        "a white octagon canvas with only the SECURITY ARENA marking, black padded posts, black chain-link fence, "
        "a dark packed arena beyond. Everything moves at real-time speed with natural weight; faces and bodies stay "
        "exactly as in <Picture 1>.")

# id, ключевой кадр, кадров (17k+5), описание, звук
SHOTS = [
    ("S01", "kf/K01.jpg", 124,
     "[Shot 1] The broadcast camera slowly tilts down over the roaring crowd toward the brightly lit octagon; "
     "spotlights sweep through haze and pyrotechnic sparks fountain up around the cage; the ring announcer in a tuxedo "
     "stands in the center.",
     "A huge crowd roar and a deep bass hit as the pyrotechnics fire."),
    ("S02", "kf/K02.jpg", 124,
     "[Shot 1] A Steadicam arcs slowly around the ring announcer in the center of the octagon. He lifts the microphone "
     "and sweeps his free arm toward the stands, then booms: <d>[English] Ladies and gentlemen… this is the MAIN EVENT "
     "of the evening!</d>",
     "His voice through the arena PA with natural reverb; the crowd erupts on the last word."),
    ("S03", "kf/K03.jpg", 124,
     f"[Shot 1] A telephoto camera holds {AUG} standing calmly in his corner. He rolls his neck and looks across the "
     "octagon at his opponent with a faint smile, then gives a small nod. The arena PA announces: <d>[English] In the "
     "black corner… standing five feet ten, weighing in at one hundred seventy pounds… undefeated… AUGUST… "
     "POBEDINSKY!</d>",
     "The announcer's voice through the arena PA, the crowd cheering."),
    ("S04", "kf/K04.jpg", 141,
     f"[Shot 1] A low handheld camera looks up at {ADG}. He pounds his chest with both fists and roars at the crowd. "
     "The arena PA announces: <d>[English] And in the red corner… standing six feet nine, weighing in at three hundred "
     "thirty-one pounds… the biggest fighter in Europe… ADGAR… FRIBETOV!</d>",
     "The announcer's voice through the arena PA, the crowd roaring and booing."),
    ("S05", "kf2/K05.jpg", 124,
     f"[Shot 1] A tight telephoto shot through the cage fence: {AUG} looks up into the eyes of {ADG}, who looms over "
     f"him; {REF} stands between them with his hands between their chests and says: <d>[English] Protect yourselves "
     "at all times. Touch gloves.</d> They touch gloves briefly. A commentator in the broadcast mix says quietly: "
     "<d>[English] Seventy-three kilos between them.</d>",
     "The crowd hushes; a low heartbeat-like thump under the arena murmur."),
    ("S06", "kf2/K06.jpg", 124,
     "[Shot 1] The main camera on a raised platform holds the whole octagon: the fighters stand in their corners, the "
     "referee in the center drops his hand to start the round, and the fighters step out.",
     "A single loud bell ring, then a rising roar."),
    ("S07", "kf3/K07.jpg", 175,
     f"[Shot 1] The main camera on a raised platform holds the octagon. {AUG} bounces lightly on his toes toward the "
     f"center. {ADG} stays completely frozen in his fighting stance like a paused video, while a glowing white "
     f"circular loading spinner icon floats just above his head. {REF} walks up and waves a hand in front of his face. "
     "A commentator says: <d>[English] Uhh… is he okay?</d> At 00:04.500, without bending at all, the giant falls "
     "straight backward like a wooden plank and lands flat on his back on the canvas.",
     "An old dial-up modem screech over a confused crowd murmur; then an electronic power-down tone, a heavy thud on "
     "the canvas and a collective gasp from the crowd: 'Ooh!'"),
    ("S09", "kf3/K09.jpg", 124,
     f"[Shot 1] The same wide shot: {ADG} lies flat on his back and his body breaks apart into square digital pixels "
     "that scatter upward; a small grey 8-bit pixel-art dinosaur, like the offline dinosaur from a web browser game, "
     f"hops over the referee's foot and runs out of the cage. {AUG} and {REF} stare at it.",
     "An 8-bit jump beep and the crowd bursting into laughter."),
    ("S10", "kf/K10.jpg", 124,
     f"[Shot 1] A handheld close-up of {AUG} inside the cage. He looks down at the empty canvas and slowly raises one "
     "eyebrow ironically.",
     "A heavy impact hit, the crowd cheering."),
    ("S11", "kf/K11.jpg", 124,
     "[Shot 1] A static camera in the commentary booth, the glowing cage behind the glass. The commentator in the dark "
     "suit holds his forehead and shakes his head: <d>[English] Well…</d> The bald commentator in the black polo says "
     "drily into his headset: <d>[English] Some fighters work fast. Others work for free.</d>",
     "A quiet booth, muffled arena noise through the glass."),
]


def prompt(desc: str, sound: str) -> str:
    return (
        "For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully "
        f"referenced.\n\nintegrated_multimodal_description: {LOOK} {desc}\n\n"
        f"overall_soundscape: {sound}\n\nnon_diegetic_music: None."
    )


def graph(img: str, text: str, frames: int, seed: int, prefix: str) -> dict:
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "minimax_h3_fl2va_pruned_fp8_scaled.safetensors", "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors", "type": "minimax", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": "minimax_h3_video_vae_fp16.safetensors"}},
        "4": {"class_type": "VAELoader", "inputs": {"vae_name": "minimax_h3_audio_vae_fp32.safetensors"}},
        "5": {"class_type": "LoadImage", "inputs": {"image": img}},
        "10": {"class_type": "MiniMaxH3ImageToVideo", "inputs": {"clip": ["2", 0], "vae": ["3", 0], "prompt": text, "width": 768, "height": 1344, "length": frames, "first_frame": ["5", 0]}},
        "11": {"class_type": "BasicGuider", "inputs": {"model": ["1", 0], "conditioning": ["10", 0]}},
        "12": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "res_multistep"}},
        "13": {"class_type": "BasicScheduler", "inputs": {"model": ["1", 0], "scheduler": "simple", "steps": 20, "denoise": 1.0}},
        "14": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}},
        "15": {"class_type": "SamplerCustomAdvanced", "inputs": {"noise": ["14", 0], "guider": ["11", 0], "sampler": ["12", 0], "sigmas": ["13", 0], "latent_image": ["10", 1]}},
        "16": {"class_type": "VAEDecode", "inputs": {"samples": ["15", 0], "vae": ["3", 0]}},
        "17": {"class_type": "VAEDecodeAudio", "inputs": {"samples": ["15", 0], "vae": ["4", 0]}},
        "18": {"class_type": "CreateVideo", "inputs": {"images": ["16", 0], "audio": ["17", 0], "fps": 24}},
        "19": {"class_type": "SaveVideo", "inputs": {"video": ["18", 0], "filename_prefix": prefix, "format": "mp4", "codec": "auto"}},
    }


OUT.mkdir(parents=True, exist_ok=True)
jobs = {}
for i, (sid, kf, frames, desc, sound) in enumerate(SHOTS):
    if ONLY and sid not in ONLY:
        continue
    p = KF / kf
    name = f"v2_{sid}_{p.name}"
    requests.post(f"{URL}/upload/image", files={"image": (name, p.read_bytes())}, data={"overwrite": "true"}, timeout=120)
    text = prompt(desc, sound)
    (OUT / f"{sid}.prompt.txt").write_text(text, encoding="utf-8")
    r = requests.post(f"{URL}/prompt", json={"prompt": graph(name, text, frames, 500 + i, f"final/{sid}")}, timeout=60).json()
    jobs[sid] = r.get("prompt_id")
    print(sid, "queued", r.get("prompt_id"), r.get("node_errors") or "", flush=True)

t0 = time.time()
while jobs and time.time() - t0 < 7200:
    for sid, pid in list(jobs.items()):
        h = requests.get(f"{URL}/history/{pid}", timeout=60).json()
        if pid not in h:
            continue
        vids = [v for n in h[pid]["outputs"].values() for v in n.get("images", []) + n.get("videos", [])]
        for v in vids:
            data = requests.get(f"{URL}/view", params={"filename": v["filename"], "subfolder": v.get("subfolder", ""), "type": "output"}, timeout=300).content
            (OUT / f"{sid}.mp4").write_bytes(data)
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(OUT / f"{sid}.mp4"), "-vf", "fps=1.5,scale=192:-2,tile=12x1", "-frames:v", "1", str(OUT / f"{sid}.sheet.jpg")])
        st = h[pid]["status"]
        print(sid, st.get("status_str"), round(time.time() - t0), "s", "" if vids else json.dumps(st.get("messages", [])[-1:])[:400], flush=True)
        del jobs[sid]
    time.sleep(10)
