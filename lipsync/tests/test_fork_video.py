"""Раскодировщик видео: сторожа."""

from __future__ import annotations

import ast
import base64
import unittest
from pathlib import Path

from lipsync import fork_video as fv
from lipsync.fork_identity import FAIL, PASS, UNMEASURED

ONE_PIXEL_PNG = base64.b64decode(
    b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAAAAAA6fptVAAAACklEQVR4nGNgAAAAAgABc3UBGAAAAABJRU5ErkJggg=="
)


def _probe_json(
    *,
    fps="30/1",
    nb='"nb_frames": "60",',
    dur="2.000000",
    width=64,
    height=64,
    audio=False,
    codec="h264",
) -> str:
    """Ответ ffprobe той же формы, что снят прогоном. Обрезан до нужных полей."""
    audio_stream = (
        """        {"index": 1, "codec_name": "aac", "codec_type": "audio",
         "r_frame_rate": "0/0", "avg_frame_rate": "0/0",
         "duration": "2.000000", "nb_frames": "88"},\n"""
        if audio
        else ""
    )
    return (
        """{
    "streams": [
"""
        + audio_stream
        + """        {"index": 0, "codec_name": \""""
        + codec
        + """",
         "codec_type": "video", "width": """
        + str(width)
        + """,
         "height": """
        + str(height)
        + """, "pix_fmt": "yuv420p",
         "r_frame_rate": \""""
        + fps
        + """", "avg_frame_rate": \""""
        + fps
        + """",
         "start_time": "0.000000", "duration": \""""
        + dur
        + """",
         """
        + nb
        + """ "bits_per_raw_sample": "8"}
    ],
    "format": {"filename": "x.mp4", "nb_streams": 1, "format_name": "mov,mp4,m4a,3gp,3g2,mj2",
               "duration": \""""
        + dur
        + """", "size": "4679", "bit_rate": "18716"}
}"""
    )


PROBE_STDOUT_BROKEN = "{\n\n}\n"
PROBE_STDERR_BROKEN = (
    "[mov,mp4,m4a,3gp,3g2,mj2 @ 0x55e104b3c700] moov atom "
    "not found\nv_broken.mp4: Invalid data found when "
    "processing input\n"
)
PROBE_STDERR_NOT_VIDEO = "not_a_video.txt: Invalid data found when processing input\n"

DECODE_RC_BROKEN = 183
DECODE_STDERR_BROKEN = (
    "[in#0 @ 0x55a6d95f0e00] Error opening input: Invalid "
    "data found when processing input\nError opening input "
    "file v_broken.mp4.\n"
)


class _Prober:
    """Подменённый ffprobe. Считает вызовы: «не звали» — тоже утверждение."""

    def __init__(self, *, ran=True, code=0, out="", err="", why=""):
        self.answer = {"ran": ran, "code": code, "out": out, "err": err, "why": why}
        self.calls = 0

    def __call__(self, path):
        self.calls += 1
        return dict(self.answer)


class _Decoder:
    """Подменённый ffmpeg: кладёт `n` настоящих PNG с теми же именами."""

    def __init__(self, n=0, *, ran=True, code=0, err="", why="", payload=None):
        self.n, self.answer = n, {"ran": ran, "code": code, "out": "", "err": err, "why": why}
        self.payload = ONE_PIXEL_PNG if payload is None else payload
        self.argv = None
        self.calls = 0

    def __call__(self, argv):
        self.calls += 1
        self.argv = list(argv)
        out = Path(argv[-1]).parent
        out.mkdir(parents=True, exist_ok=True)
        for i in range(self.n):
            (out / fv.frame_name(i)).write_bytes(self.payload)
        return dict(self.answer)


def _video(tmp: Path, name="driving.mp4", size=4679) -> Path:
    """Файл-заглушка: `probe` до вызова ffprobe смотрит только на размер."""
    p = tmp / name
    p.write_bytes(b"\x00" * size)
    return p


class ParseProbe(unittest.TestCase):
    """Разбор ответа ffprobe. На литералах, снятых с настоящего ffprobe."""

    def test_the_fields_we_use_are_read_from_a_real_answer(self):
        got = fv.parse_probe(_probe_json())
        self.assertTrue(got["ok"], got.get("why"))
        self.assertEqual(got["fps"], 30.0)
        self.assertEqual(got["frames"], 60)
        self.assertEqual(got["frames_from"], "nb_frames")
        self.assertEqual(got["seconds"], 2.0)
        self.assertEqual((got["width"], got["height"]), (64, 64))
        self.assertIs(got["audio"], False)
        self.assertEqual(got["codec"], "h264")

    def test_an_audio_track_is_seen_and_a_missing_one_is_not_invented(self):
        self.assertIs(fv.parse_probe(_probe_json(audio=True))["audio"], True)
        self.assertIs(fv.parse_probe(_probe_json(audio=False))["audio"], False)

    def test_ntsc_2997_is_not_thirty(self):
        got = fv.parse_probe(_probe_json(fps="30000/1001", dur="3.003000", nb='"nb_frames": "90",'))
        self.assertAlmostEqual(got["fps"], 29.97002997002997, places=9)
        self.assertNotEqual(got["fps"], 30.0)
        self.assertEqual(got["frames"], 90)

    def test_without_nb_frames_the_count_is_named_an_estimate(self):
        got = fv.parse_probe(_probe_json(nb=""))
        self.assertEqual(got["frames"], 60)
        self.assertEqual(got["frames_from"], "длительность x частота")

    def test_a_broken_file_answer_has_no_video_stream(self):
        got = fv.parse_probe(PROBE_STDOUT_BROKEN)
        self.assertFalse(got["ok"])
        self.assertIn("видеопотока", got["why"])

    def test_garbage_instead_of_json_does_not_raise(self):
        got = fv.parse_probe("не json вовсе")
        self.assertFalse(got["ok"])
        self.assertIn("JSON", got["why"])

    def test_an_audio_only_file_is_not_a_video(self):
        only_audio = (
            '{"streams": [{"index": 0, "codec_name": "aac", '
            '"codec_type": "audio", "duration": "2.000000"}], '
            '"format": {"duration": "2.000000"}}'
        )
        got = fv.parse_probe(only_audio)
        self.assertFalse(got["ok"])
        self.assertIs(got["audio"], True)


class FpsRule(unittest.TestCase):
    """Продуктовое решение про частоту. Развилка вынесена из `frames`."""

    def test_no_request_means_every_frame_and_says_so(self):
        got = fv.fps_plan(30.0)
        self.assertEqual(got["outcome"], PASS)
        self.assertEqual(got["mode"], fv.AS_IS)
        self.assertEqual(got["fps"], 30.0)

    def test_downsampling_is_allowed_and_announced(self):
        got = fv.fps_plan(30.0, want=24)
        self.assertEqual(got["outcome"], PASS)
        self.assertEqual(got["mode"], fv.DROP)
        self.assertEqual(got["fps"], 24.0)

    def test_upsampling_is_refused(self):
        got = fv.fps_plan(24.0, want=30)
        self.assertEqual(got["outcome"], FAIL)
        self.assertEqual(got["mode"], fv.REFUSE)
        self.assertIsNone(got["fps"])

    def test_2997_to_30_is_refused_and_30005_to_30_is_not(self):
        """Допуск частоты зажат литералами С ДВУХ СТОРОН."""
        self.assertEqual(fv.fps_plan(29.97002997002997, want=30)["outcome"], FAIL)
        near = fv.fps_plan(30.005, want=30)
        self.assertEqual(near["outcome"], PASS)
        self.assertEqual(near["mode"], fv.AS_IS)

    def test_an_unknown_source_rate_is_unmeasured_not_as_is(self):
        got = fv.fps_plan(None, want=None)
        self.assertEqual(got["outcome"], UNMEASURED)
        self.assertEqual(got["mode"], fv.REFUSE)

    def test_a_nonsense_request_is_refused(self):
        for bad in (0, -5, "30", True, 0.0, float("nan")):
            with self.subTest(want=bad):
                self.assertEqual(fv.fps_plan(30.0, want=bad)["outcome"], FAIL)


class CountVerdict(unittest.TestCase):
    """Вердикт по числам кадров: ноль — не успех, расхождение — не «годно»."""

    def test_zero_frames_is_a_failure_not_an_empty_success(self):
        got = fv.count_outcome(60, 0)
        self.assertEqual(got["outcome"], FAIL)
        self.assertNotEqual(got["outcome"], PASS)

    def test_the_exact_count_passes(self):
        self.assertEqual(fv.count_outcome(60, 60)["outcome"], PASS)

    def test_the_count_tolerance_is_clamped_from_both_sides(self):
        """Допуск в кадрах зажат литералами с двух сторон."""
        self.assertEqual(fv.count_outcome(60, 61)["outcome"], PASS)
        self.assertEqual(fv.count_outcome(60, 59)["outcome"], PASS)
        self.assertEqual(fv.count_outcome(60, 62)["outcome"], UNMEASURED)
        self.assertEqual(fv.count_outcome(60, 58)["outcome"], UNMEASURED)

    def test_a_big_shortfall_is_unmeasured_never_pass(self):
        got = fv.count_outcome(320, 5)
        self.assertEqual(got["outcome"], UNMEASURED)
        self.assertIn("320", got["note"])
        self.assertIn("5", got["note"])

    def test_without_an_expectation_completeness_is_unmeasured(self):
        self.assertEqual(fv.count_outcome(None, 7)["outcome"], UNMEASURED)

    def test_negative_written_is_a_programming_error_not_a_verdict(self):
        with self.assertRaises(ValueError):
            fv.count_outcome(10, -1)


class ExpectedFrames(unittest.TestCase):
    def test_as_is_expects_every_frame(self):
        self.assertEqual(fv.expected_frames(60, source_fps=30.0), 60)

    def test_dropping_to_24_of_30_expects_forty_eight(self):
        self.assertEqual(fv.expected_frames(60, source_fps=30.0, out_fps=24.0), 48)

    def test_a_limit_cuts_the_expectation_and_never_raises_it(self):
        self.assertEqual(fv.expected_frames(320, source_fps=30.0, limit=77), 77)
        self.assertEqual(fv.expected_frames(60, source_fps=30.0, limit=1000), 60)

    def test_without_a_source_count_there_is_no_expectation(self):
        self.assertIsNone(fv.expected_frames(None, source_fps=30.0))


class FrameNames(unittest.TestCase):
    def test_the_first_frame_is_zero_padded_to_five(self):
        self.assertEqual(fv.frame_name(0), "00000.png")
        self.assertEqual(fv.frame_name(12), "00012.png")
        self.assertEqual(fv.frame_name(99999), "99999.png")

    def test_string_order_equals_number_order_over_our_whole_range(self):
        """Ширина поля зажата сверху нашим потолком, снизу — сортировкой."""
        names = [fv.frame_name(i) for i in range(0, 306)]
        self.assertEqual(names, sorted(names))
        self.assertEqual(len(set(len(n) for n in names)), 1)

    def test_a_negative_index_is_refused(self):
        with self.assertRaises(ValueError):
            fv.frame_name(-1)

    def test_frame_name_has_no_start_of_its_own(self):
        """Начало нумерации выбирает ВЫЗЫВАЮЩИЙ, а не эта функция."""
        self.assertEqual(fv.frame_name(0), "00000.png")
        self.assertEqual(fv.frame_name(1), "00001.png")
        self.assertEqual(fv.frame_name(361), "00361.png")
        self.assertEqual(fv.frame_name(362), "00362.png")

    def test_both_starts_sort_into_the_same_order(self):
        """ЗАМЕР, вынесенный в сторож: раскладка с нуля и с единицы дают"""
        for n in (9, 10, 99, 100, 362, 999, 1000):
            with self.subTest(n=n):
                zero = sorted(fv.frame_name(k) for k in range(n))
                one = sorted(fv.frame_name(k + 1) for k in range(n))
                self.assertEqual([int(x[:-4]) for x in zero], list(range(n)))
                self.assertEqual([int(x[:-4]) - 1 for x in one], list(range(n)))
                self.assertEqual(len(set(len(x) for x in zero + one)), 1)

    def test_the_order_would_break_without_the_padding(self):
        """НЕГАТИВНЫЙ КОНТРОЛЬ к предыдущему: без дополнения нулями"""
        for n in (100, 1000):
            for start in (0, 1):
                with self.subTest(n=n, start=start):
                    bad = sorted(f"{k + start}.png" for k in range(n))
                    self.assertNotEqual([int(x[:-4]) - start for x in bad], list(range(n)))


class DecodeCommand(unittest.TestCase):
    """Состав команды — тоже решение, и он краснеет в тесте, а не в прогоне."""

    def test_the_numbering_starts_at_zero_and_names_are_padded(self):
        argv = fv.decode_argv("in.mp4", "/out")
        self.assertIn("-start_number", argv)
        self.assertEqual(argv[argv.index("-start_number") + 1], "0")
        self.assertTrue(argv[-1].endswith("%05d.png"), argv[-1])

    def test_frame_rate_is_passed_through_not_conformed(self):
        argv = fv.decode_argv("in.mp4", "/out")
        self.assertIn("-fps_mode", argv)
        self.assertEqual(argv[argv.index("-fps_mode") + 1], "passthrough")

    def test_no_filter_is_added_when_nothing_was_requested(self):
        self.assertNotIn("-vf", fv.decode_argv("in.mp4", "/out"))

    def test_a_requested_rate_becomes_an_fps_filter(self):
        argv = fv.decode_argv("in.mp4", "/out", out_fps=24.0)
        self.assertEqual(argv[argv.index("-vf") + 1], "fps=24")

    def test_a_limit_becomes_frames_v(self):
        argv = fv.decode_argv("in.mp4", "/out", limit=77)
        self.assertEqual(argv[argv.index("-frames:v") + 1], "77")

    def test_stdin_is_not_eaten(self):
        self.assertIn("-nostdin", fv.decode_argv("in.mp4", "/out"))


class Probe(unittest.TestCase):
    """Три исхода метаданных, и «нет инструмента» не равно «плохой файл»."""

    def setUp(self):
        import tempfile

        self.tmp = Path(tempfile.mkdtemp(prefix="fork_video_probe_"))

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_a_missing_file_is_a_failure(self):
        got = fv.probe(self.tmp / "нет.mp4", prober=_Prober())
        self.assertEqual(got["outcome"], FAIL)

    def test_a_directory_is_a_failure_and_says_what_to_do(self):
        d = self.tmp / "кадры"
        d.mkdir()
        got = fv.probe(d, prober=_Prober())
        self.assertEqual(got["outcome"], FAIL)
        self.assertIn("КАТАЛОГ", got["note"])

    def test_an_empty_file_is_a_failure_without_paying_for_a_process(self):
        p = self.tmp / "пусто.mp4"
        p.write_bytes(b"")
        prober = _Prober()
        got = fv.probe(p, prober=prober)
        self.assertEqual(got["outcome"], FAIL)
        self.assertEqual(prober.calls, 0)

    def test_a_missing_ffprobe_is_unmeasured_never_a_verdict(self):
        got = fv.probe(_video(self.tmp), prober=_Prober(ran=False, why="ffprobe не найден"))
        self.assertEqual(got["outcome"], UNMEASURED)
        self.assertNotEqual(got["outcome"], FAIL)
        self.assertNotEqual(got["outcome"], PASS)

    def test_a_broken_file_is_a_failure_and_carries_the_reason(self):
        got = fv.probe(
            _video(self.tmp),
            prober=_Prober(code=1, out=PROBE_STDOUT_BROKEN, err=PROBE_STDERR_BROKEN),
        )
        self.assertEqual(got["outcome"], FAIL)
        self.assertIn("moov atom not found", got["note"])

    def test_a_text_file_is_a_failure(self):
        got = fv.probe(
            _video(self.tmp, name="не_видео.txt"),
            prober=_Prober(code=1, out=PROBE_STDOUT_BROKEN, err=PROBE_STDERR_NOT_VIDEO),
        )
        self.assertEqual(got["outcome"], FAIL)

    def test_a_good_file_passes_with_numbers_beside_the_verdict(self):
        got = fv.probe(_video(self.tmp), prober=_Prober(out=_probe_json()))
        self.assertEqual(got["outcome"], PASS)
        self.assertEqual(got["fps"], 30.0)
        self.assertEqual(got["frames"], 60)
        self.assertEqual(got["seconds"], 2.0)
        self.assertEqual((got["width"], got["height"]), (64, 64))
        self.assertIs(got["audio"], False)
        self.assertEqual(got["bytes"], 4679)
        self.assertGreaterEqual(got["elapsed"], 0.0)

    def test_a_half_read_answer_is_unmeasured_not_pass(self):
        got = fv.probe(_video(self.tmp), prober=_Prober(out=_probe_json(fps="0/0", nb="")))
        self.assertEqual(got["outcome"], UNMEASURED)


class FpsProberDropIn(unittest.TestCase):
    """Совместимая замена `fork_template._ffprobe_fps`: `path -> float|None`."""

    def setUp(self):
        import tempfile

        self.tmp = Path(tempfile.mkdtemp(prefix="fork_video_drop_"))

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_it_returns_a_number_on_a_good_file(self):
        real = fv.read_probe
        fv.read_probe = _Prober(out=_probe_json(fps="24/1"))
        try:
            self.assertEqual(fv.fps_prober(_video(self.tmp)), 24.0)
        finally:
            fv.read_probe = real

    def test_it_returns_none_when_there_is_nothing_to_ask(self):
        real = fv.read_probe
        fv.read_probe = _Prober(ran=False, why="нет ffprobe")
        try:
            self.assertIsNone(fv.fps_prober(_video(self.tmp)))
        finally:
            fv.read_probe = real


class Frames(unittest.TestCase):
    """Раскодирование целиком: числа, три исхода, порядок, идемпотентность."""

    def setUp(self):
        import tempfile

        self.tmp = Path(tempfile.mkdtemp(prefix="fork_video_frames_"))
        self.src = _video(self.tmp)
        self.out = self.tmp / "кадры"

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, *, n=60, probe_kw=None, **kw):
        prober = _Prober(out=_probe_json(**(probe_kw or {})))
        decoder = kw.pop("decoder", None) or _Decoder(n)
        rep = fv.frames(self.src, self.out, prober=prober, decoder=decoder, **kw)
        return rep, prober, decoder

    def test_a_sixty_frame_clip_decodes_with_all_four_numbers(self):
        rep, _, _ = self._run(n=60)
        self.assertEqual(rep["outcome"], PASS)
        self.assertEqual(rep["expected"], 60)
        self.assertEqual(rep["written"], 60)
        self.assertEqual(rep["bytes"], 60 * len(ONE_PIXEL_PNG))
        self.assertGreaterEqual(rep["elapsed"], 0.0)
        self.assertEqual(len(rep["paths"]), 60)

    def test_a_single_frame_clip_is_not_an_edge_case_that_fails(self):
        rep, _, _ = self._run(n=1, probe_kw={"nb": '"nb_frames": "1",', "dur": "0.033333"})
        self.assertEqual(rep["outcome"], PASS)
        self.assertEqual(rep["written"], 1)
        self.assertEqual(rep["paths"][0].name, "00000.png")

    def test_a_clip_longer_than_our_ceiling_still_decodes_in_order(self):
        rep, _, _ = self._run(n=320, probe_kw={"nb": '"nb_frames": "320",', "dur": "10.666667"})
        self.assertEqual(rep["outcome"], PASS)
        self.assertEqual(rep["written"], 320)
        names = [p.name for p in rep["paths"]]
        self.assertEqual(names, sorted(names))
        self.assertEqual(names[0], "00000.png")
        self.assertEqual(names[-1], "00319.png")
        self.assertEqual(names, [fv.frame_name(i) for i in range(320)])

    def test_zero_written_frames_is_a_failure_not_an_empty_success(self):
        rep, _, _ = self._run(n=0)
        self.assertEqual(rep["outcome"], FAIL)
        self.assertEqual(rep["written"], 0)

    def test_a_missing_ffmpeg_is_unmeasured_never_a_verdict(self):
        rep, _, _ = self._run(decoder=_Decoder(0, ran=False, why="ffmpeg не найден"))
        self.assertEqual(rep["outcome"], UNMEASURED)
        self.assertNotEqual(rep["outcome"], FAIL)
        self.assertNotEqual(rep["outcome"], PASS)

    def test_a_nonzero_return_code_is_a_failure_and_carries_the_reason(self):
        rep, _, _ = self._run(decoder=_Decoder(0, code=DECODE_RC_BROKEN, err=DECODE_STDERR_BROKEN))
        self.assertEqual(rep["outcome"], FAIL)
        self.assertIn("183", rep["note"])

    def test_a_broken_source_never_reaches_the_decoder(self):
        prober = _Prober(code=1, out=PROBE_STDOUT_BROKEN, err=PROBE_STDERR_BROKEN)
        decoder = _Decoder(60)
        rep = fv.frames(self.src, self.out, prober=prober, decoder=decoder)
        self.assertEqual(rep["outcome"], FAIL)
        self.assertEqual(decoder.calls, 0)
        self.assertFalse(self.out.exists())

    def test_upsampling_is_refused_before_a_single_frame_is_written(self):
        rep, _, decoder = self._run(
            fps=30, probe_kw={"fps": "24/1", "nb": '"nb_frames": "72",', "dur": "3.000000"}
        )
        self.assertEqual(rep["outcome"], FAIL)
        self.assertEqual(decoder.calls, 0)
        self.assertEqual(rep["written"], 0)

    def test_downsampling_changes_the_expected_count_and_says_so(self):
        rep, _, decoder = self._run(n=48, fps=24)
        self.assertEqual(rep["outcome"], PASS)
        self.assertEqual(rep["expected"], 48)
        self.assertEqual(rep["written"], 48)
        self.assertEqual(rep["mode"], fv.DROP)
        self.assertEqual(decoder.argv[decoder.argv.index("-vf") + 1], "fps=24")

    def test_asking_for_the_same_rate_touches_nothing(self):
        rep, _, decoder = self._run(n=60, fps=30)
        self.assertEqual(rep["outcome"], PASS)
        self.assertEqual(rep["mode"], fv.AS_IS)
        self.assertNotIn("-vf", decoder.argv)

    def test_a_limit_caps_both_the_expectation_and_the_command(self):
        rep, _, decoder = self._run(
            n=77, limit=77, probe_kw={"nb": '"nb_frames": "320",', "dur": "10.666667"}
        )
        self.assertEqual(rep["outcome"], PASS)
        self.assertEqual(rep["expected"], 77)
        self.assertEqual(decoder.argv[decoder.argv.index("-frames:v") + 1], "77")

    def test_a_nonsense_limit_is_refused(self):
        for bad in (0, -1, "77", 1.5):
            with self.subTest(limit=bad):
                rep, _, decoder = self._run(limit=bad)
                self.assertEqual(rep["outcome"], FAIL)
                self.assertEqual(decoder.calls, 0)

    def test_a_shortfall_against_the_metadata_is_unmeasured_not_pass(self):
        rep, _, _ = self._run(n=5)
        self.assertEqual(rep["outcome"], UNMEASURED)
        self.assertEqual(rep["expected"], 60)
        self.assertEqual(rep["written"], 5)

    def test_a_second_run_refuses_to_overwrite_someone_elses_frames(self):
        first, _, _ = self._run(n=60)
        self.assertEqual(first["outcome"], PASS)
        before = {p.name: p.read_bytes() for p in sorted(self.out.iterdir())}
        rep, _, decoder = self._run(n=3)
        self.assertEqual(rep["outcome"], UNMEASURED)
        self.assertEqual(decoder.calls, 0)
        after = {p.name: p.read_bytes() for p in sorted(self.out.iterdir())}
        self.assertEqual(after, before)

    def test_overwrite_is_possible_but_only_when_asked_out_loud(self):
        self._run(n=60)
        rep, _, decoder = self._run(
            n=3, overwrite=True, probe_kw={"nb": '"nb_frames": "3",', "dur": "0.100000"}
        )
        self.assertEqual(rep["outcome"], PASS)
        self.assertEqual(decoder.calls, 1)
        self.assertEqual(
            sorted(p.name for p in self.out.iterdir()), ["00000.png", "00001.png", "00002.png"]
        )

    def test_a_second_run_reports_the_frames_that_lie_there_not_a_zero(self):
        """ДЕФЕКТ, ради которого писан этот сторож: итоговая строка печатала"""
        first, _, _ = self._run(n=60)
        self.assertEqual(first["outcome"], PASS)
        rep, _, decoder = self._run(n=3)
        self.assertEqual(rep["outcome"], UNMEASURED)
        self.assertEqual(decoder.calls, 0)
        self.assertEqual(rep["written"], 0)
        self.assertEqual(rep["bytes"], 0)
        self.assertEqual(rep["present"], 60)
        self.assertEqual(rep["present_bytes"], 60 * len(ONE_PIXEL_PNG))
        self.assertIn("до нас в каталоге лежало кадров 60", rep["note"])
        self.assertIn("записано нами 0", rep["note"])
        self.assertNotIn("каталог назначения был пуст", rep["note"])

    def test_a_second_run_still_names_the_expectation_it_already_knew(self):
        """Метаданные разобрались до отказа — значит «ожидалось» ИЗВЕСТНО."""
        self._run(n=60)
        rep, _, _ = self._run(n=3)
        self.assertEqual(rep["expected"], 60)
        self.assertIn("Ожидалось кадров 60", rep["note"])

    def test_a_clean_directory_is_reported_as_looked_at_and_empty(self):
        """Негативный контроль с другой стороны: пусто — это ОТВЕТ."""
        rep, _, _ = self._run(n=60)
        self.assertEqual(rep["outcome"], PASS)
        self.assertEqual(rep["present"], 0)
        self.assertEqual(rep["present_bytes"], 0)
        self.assertIn("каталог назначения был пуст", rep["note"])

    def test_an_overwrite_says_what_it_wiped(self):
        self._run(n=60)
        rep, _, _ = self._run(
            n=3, overwrite=True, probe_kw={"nb": '"nb_frames": "3",', "dur": "0.100000"}
        )
        self.assertEqual(rep["outcome"], PASS)
        self.assertEqual(rep["written"], 3)
        self.assertEqual(rep["present"], 60)
        self.assertIn("до нас в каталоге лежало кадров 60", rep["note"])

    def test_a_refusal_before_the_look_never_claims_an_empty_directory(self):
        """Третий исход не сворачивается в первые два: отказ случился"""
        prober = _Prober(code=1, out=PROBE_STDOUT_BROKEN, err=PROBE_STDERR_BROKEN)
        rep = fv.frames(self.src, self.out, prober=prober, decoder=_Decoder(60))
        self.assertEqual(rep["outcome"], FAIL)
        self.assertIsNone(rep["present"])
        self.assertIsNone(rep["present_bytes"])
        self.assertIn("каталог назначения не осматривали", rep["note"])
        self.assertNotIn("каталог назначения был пуст", rep["note"])

    def test_every_step_reports_its_own_outcome_and_duration(self):
        rep, _, _ = self._run(n=60)
        steps = [s["step"] for s in rep["steps"]]
        self.assertEqual(steps, ["метаданные", "частота", "раскодирование", "кадры"])
        for s in rep["steps"]:
            with self.subTest(step=s["step"]):
                self.assertIn(s["outcome"], (PASS, FAIL, UNMEASURED))
                self.assertGreaterEqual(s["seconds"], 0.0)


class DirectoryFact(unittest.TestCase):
    """Три состояния каталога назначения — три РАЗНЫЕ фразы, литералами."""

    def test_the_three_phrases_are_the_ones_the_operator_will_read(self):
        self.assertEqual(fv.DIR_UNSEEN, "каталог назначения не осматривали")
        self.assertEqual(fv.DIR_EMPTY, "каталог назначения был пуст")
        self.assertEqual(fv._dir_fact(3, 99), "до нас в каталоге лежало кадров 3, байт 99")

    def test_not_looked_at_and_empty_are_not_the_same_phrase(self):
        self.assertNotEqual(fv._dir_fact(None, None), fv._dir_fact(0, 0))
        self.assertEqual(fv._dir_fact(None, None), "каталог назначения не осматривали")
        self.assertEqual(fv._dir_fact(0, 0), "каталог назначения был пуст")

    def test_frames_lying_there_are_never_swallowed_into_a_zero(self):
        self.assertNotEqual(fv._dir_fact(60, 189567), fv._dir_fact(0, 0))
        self.assertIn("60", fv._dir_fact(60, 189567))
        self.assertIn("189567", fv._dir_fact(60, 189567))


class PlanForSeconds(unittest.TestCase):
    """Длина считается обёрткой, а не здесь."""

    def test_it_forwards_to_fork_comfy_and_does_not_recompute(self):
        got = fv.plan_for_seconds(5)
        self.assertEqual(got["frames_requested"], 150)
        self.assertEqual(got["frames"], 149)
        self.assertEqual(got["snapped_away"], 1)

    def test_a_length_outside_the_owners_band_is_refused(self):
        with self.assertRaises(ValueError):
            fv.plan_for_seconds(2)


class Wiring(unittest.TestCase):
    """Сторожа устройства модуля, а не поведения."""

    def test_the_outside_world_is_touched_in_exactly_two_places(self):
        """`subprocess.run` живёт только в двух точках внедрения."""
        src = Path(fv.__file__).read_text(encoding="utf-8")
        tree = ast.parse(src)
        allowed, found = {"read_probe", "run_decode"}, []
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            for inner in ast.walk(node):
                if (
                    isinstance(inner, ast.Call)
                    and isinstance(inner.func, ast.Attribute)
                    and inner.func.attr == "run"
                    and isinstance(inner.func.value, ast.Name)
                    and inner.func.value.id == "subprocess"
                ):
                    found.append(node.name)
        self.assertEqual(
            sorted(set(found)),
            sorted(allowed),
            f"внешний инструмент зовётся из {sorted(set(found))}, "
            f"а точек внедрения должно быть ровно две",
        )

    def test_both_outside_calls_carry_their_own_timeout(self):
        """Оба выхода наружу висят на таймауте, и на СВОЁМ, а не на общем."""
        tree = ast.parse(Path(fv.__file__).read_text(encoding="utf-8"))
        want = {"read_probe": "PROBE_TIMEOUT_S", "run_decode": "DECODE_TIMEOUT_S"}
        seen = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name in want:
                for inner in ast.walk(node):
                    if isinstance(inner, ast.Call):
                        for kw in inner.keywords:
                            if kw.arg == "timeout" and isinstance(kw.value, ast.Name):
                                seen[node.name] = kw.value.id
        self.assertEqual(seen, want)

    def test_the_verdict_words_are_not_reinvented(self):
        self.assertEqual(
            (fv.PASS, fv.FAIL, fv.UNMEASURED), ("годно", "не годно", "не смогли проверить")
        )

    def test_the_output_rate_is_not_copied_from_fork_comfy(self):
        src = Path(fv.__file__).read_text(encoding="utf-8")
        for line in src.splitlines():
            if line.strip().startswith("#") or '"""' in line:
                continue
            with self.subTest(line=line[:60]):
                self.assertNotIn("FPS_OUT = 30", line)
                self.assertNotIn("WRAP_FPS = 30", line)

    def test_the_mode_words_are_the_ones_the_operator_will_read(self):
        self.assertEqual((fv.AS_IS, fv.DROP, fv.REFUSE), ("как есть", "прорежаем", "отказ"))
        self.assertEqual(len({fv.AS_IS, fv.DROP, fv.REFUSE}), 3)

    def test_the_three_outcomes_map_to_three_different_exit_codes(self):
        self.assertEqual(fv.EXIT_BY_OUTCOME, {"годно": 0, "не годно": 1, "не смогли проверить": 2})
        self.assertEqual(len(set(fv.EXIT_BY_OUTCOME.values())), 3)


class EntryPoint(unittest.TestCase):
    def test_probing_a_missing_file_exits_one_not_zero(self):
        self.assertEqual(fv.main(["probe", "/нет/такого/файла.mp4"]), 1)

    def test_decoding_a_missing_file_exits_one_not_zero(self):
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(fv.main(["frames", "/нет/такого/файла.mp4", f"{d}/кадры"]), 1)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
