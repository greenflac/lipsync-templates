"""Round-14 integration: the per-shot length (r14-steps) feeds the single-take note (r14-models).

The planner prints `run_limit` when ONE shot is longer than the chosen model's
recorded run; `checklist.run_over_priors` turns that line into the prior the
single-take note follows. The shot length is the clip divided by the shots
when no per-shot length is named — so a 3 x 8 s ad on an 8 s model gets no
"24 s take" note, while a single 20 s (or 12 s) take on that model does.
Paraphrases written for this file (EN and RU); no network.
"""

from __future__ import annotations

import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("STUDIO_NO_JOURNAL", "1")

from studio import brief_spec as bs  # noqa: E402
from studio import planner as pn  # noqa: E402
from studio import realtime as rt  # noqa: E402
from studio.recipes import checklist as cl  # noqa: E402

EIGHT_S = SimpleNamespace(model="acme-video-8s", run_s=8.0, dur_note="limit 8 s: max_seconds=8")
GEN = {"task": "generate", "inputs": [], "outputs": ["video"], "people": []}


def _spec(brief: str, **raw: object) -> bs.Spec:
    spec, errors = bs.parse_spec({**GEN, **raw})
    assert not errors, errors
    return bs.with_defaults(spec, ролик=True, текст=brief)


def _notes(brief: str, en: bool, **raw: object) -> list[str]:
    spec = _spec(brief, **raw)
    _всего, шот = pn.длительности_плана(brief, spec)
    # The planner prints the line only when the shot is over the recorded run.
    строки = [pn.run_limit_line(EIGHT_S, шот.секунды, en)] if шот.секунды and шот.секунды > EIGHT_S.run_s else []
    return [i for i, _ in cl.fire(spec, ["генерация_видео"], text=brief, priors=cl.run_over_priors(строки))]


class ShotLengthMeetsSingleTake(unittest.TestCase):
    def test_multi_shot_ad_is_not_one_long_take(self) -> None:
        for brief, en in (
            ("A 24-second spot for our tea, three shots", True),
            ("Ролик на 24 секунды для нашего чая, три шота", False),
        ):
            with self.subTest(brief=brief):
                self.assertNotIn("single_take_limit", _notes(brief, en, duration_s=24, shots=3))

    def test_single_take_over_the_chosen_run(self) -> None:
        for brief, seconds, en in (
            ("One continuous 20-second take of a cyclist crossing a bridge", 20, True),
            ("Один непрерывный дубль на 12 секунд: велосипедист едет по мосту", 12, False),
        ):
            with self.subTest(brief=brief):
                self.assertIn("single_take_limit", _notes(brief, en, duration_s=seconds, shots=1))

    def test_two_long_shots_each_over_the_run(self) -> None:
        self.assertIn("single_take_limit", _notes("Two shots, 24 seconds in total", True, duration_s=24, shots=2))


class LiveBroadcastInAnyLanguage(unittest.TestCase):
    """A live broadcast / stream / video call is live work in the brief's own language.

    Round 14 (steps) made a bare speed word live only with an interactive cue; the live-system
    nouns must then be known beyond EN/RU, or a live-streamed avatar becomes a 3-hour render.
    """

    AVATAR = {"task": "avatar", "outputs": ["video"]}

    def test_live_nouns(self) -> None:
        for brief in (
            "제 캐릭터 아바타로 매주 라이브 방송을 하고 싶어요, 3시간 정도",
            "毎晩の生配信でキャラクターのアバターを使いたい",
            "我们想在直播里用一个虚拟形象主播",
            "Queremos un avatar para la transmisión en vivo de cada viernes",
            "Um avatar para a nossa transmissão ao vivo semanal",
            "Ein Avatar für unsere wöchentliche Live-Übertragung",
            "Un avatar pour notre diffusion en direct du jeudi",
        ):
            with self.subTest(brief=brief):
                self.assertTrue(rt.applies(brief, self.AVATAR))

    def test_speed_word_alone_is_still_a_render(self) -> None:
        for brief in (
            "실시간에 가까운 속도로 60초 아바타 영상을 렌더링해 주세요",
            "Renderiza un vídeo de avatar de 60 s casi en tiempo real",
            "Ein 60-Sekunden-Avatarvideo, fast in Echtzeit gerendert",
        ):
            with self.subTest(brief=brief):
                self.assertFalse(rt.applies(brief, self.AVATAR))

    def test_speed_word_with_viewers_answered(self) -> None:
        self.assertTrue(rt.applies("The avatar answers viewers in tiempo real", self.AVATAR))


if __name__ == "__main__":
    unittest.main()
