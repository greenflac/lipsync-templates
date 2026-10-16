"""Склейка и речь: где в рендере звучат слова, и не режет ли их монтаж.

НАБЛЮДЕНО 2026-10-08. Сначала точки in/out ставились по битам сценария и
вырезали имена бойцов: «Adgar Fribetov» звучит на 3,35–6,2 с исходника, а в
монтаж брались 1,0–3,4. Потом точки переставили по спектрограмме, и владелец
сказал: «монтаж рваный, обрезается ровно в конце фразы». Значит, правило нужно
в обе стороны: склейка не режет слово, и после слова звук не обрывается.
Второе закрывают звуковые ручки (`edit.Clip.audio_tail`), первое — эта проверка.

Тайминги слов даёт faster-whisper. Это необязательная зависимость: без неё
проверка отвечает «не смогли», а не «годно». Слова кэшируются рядом с рендером
в `<рендер>.words.json`, чтобы монтаж не гонял распознавание при каждой сборке.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

#: Слово, задетое склейкой меньше чем на столько секунд, — не обрыв: границы
#: слов у Whisper плавают примерно на эту величину.
SLACK = 0.06
#: Рёв толпы Whisper «распознаёт» словами. НАБЛЮДЕНО 2026-10-08: в S06 «sneeze»
#: на 0–2,68 с, в S07 «Angels!» на 0,36–4,04 с — при живой речи слово короче
#: секунды. Такие «слова» и слова с низкой уверенностью в проверку не идут.
MIN_PROB = 0.5
MAX_WORD_S = 1.3


@dataclass(frozen=True)
class Word:
    text: str
    start: float
    end: float
    prob: float = 1.0

    @property
    def speech(self) -> bool:
        return self.prob >= MIN_PROB and self.end - self.start <= MAX_WORD_S


def sidecar(video: Path) -> Path:
    return video.with_suffix(".words.json")


def words(video: Path) -> list[Word] | None:
    """Слова рендера: из кэша, иначе через faster-whisper. None — распознать нечем."""
    cache = sidecar(video)
    if cache.exists():
        return [Word(**w) for w in json.loads(cache.read_text(encoding="utf-8"))]
    try:
        import numpy as np
        from faster_whisper import WhisperModel
    except ImportError:
        return None
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(video), "-ac", "1", "-ar", "16000", "-f", "f32le", "-"],
        capture_output=True,
        check=True,
    ).stdout
    model = WhisperModel("base.en", device="cpu", compute_type="int8")
    segs, _ = model.transcribe(np.frombuffer(raw, np.float32), word_timestamps=True)
    out = [
        Word(w.word.strip(), round(w.start, 3), round(w.end, 3), round(w.probability, 3))
        for s in segs
        for w in (s.words or [])
    ]
    cache.write_text(
        json.dumps([w.__dict__ for w in out], ensure_ascii=False, indent=0), encoding="utf-8"
    )
    return out


def cut_problems(
    shot: str, src_in: float, src_out: float, lead: float, tail: float, ws: list[Word]
) -> list[str]:
    """Что склейки плана делают со словами. Ручки звука в счёт: слово, которое
    договаривается в ручке под соседней картинкой, — это L/J-cut, а не обрыв."""
    out: list[str] = []
    for w in (w for w in ws if w.speech):
        if w.start + SLACK < src_in < w.end - SLACK and src_in - lead > w.start + SLACK:
            out.append(
                f"{shot}: вход {src_in:.2f} с режет «{w.text}» ({w.start:.2f}–{w.end:.2f}), "
                f"ручка до {lead:.2f} с его не покрывает"
            )
        if w.start + SLACK < src_out < w.end - SLACK and src_out + tail < w.end - SLACK:
            out.append(
                f"{shot}: выход {src_out:.2f} с режет «{w.text}» ({w.start:.2f}–{w.end:.2f}), "
                f"ручка после {tail:.2f} с его не покрывает"
            )
    return out
