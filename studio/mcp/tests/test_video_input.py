"""Видео на входе: разбирается ли ролик, и честно ли молчит, когда не может.

Ролик тест ДЕЛАЕТ САМ, из ffmpeg-генератора: в сеть не ходим (Т4), и от
наличия чужих файлов не зависим — иначе тест зеленел бы здесь и краснел в CI.
"""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from lipsync.fork_identity import PASS, UNMEASURED
from studio.mcp import creative


def _make_clip(into: Path, *, seconds: float = 2.0) -> Path:
    """Двухсекундный ролик из тестового генератора ffmpeg."""
    import imageio_ffmpeg

    out = into / "clip.mp4"
    subprocess.run(
        [
            imageio_ffmpeg.get_ffmpeg_exe(),
            "-y",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"testsrc=size=160x120:rate=10:duration={seconds}",
            "-pix_fmt",
            "yuv420p",
            str(out),
        ],
        capture_output=True,
        check=False,
    )
    return out


class AClipIsDecodedHere(unittest.TestCase):
    def test_six_frames_come_out_of_a_two_second_clip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            clip = _make_clip(Path(tmp))
            got = creative.frames_from_video(clip, Path(tmp) / "frames")
            assert got["outcome"] == PASS, got["note"]
            assert len(got["frames"]) == creative.VIDEO_FRAMES, got["note"]

    def test_analyse_takes_a_video_path_directly(self) -> None:
        """Смысл правки: оператор даёт ролик, а не заранее нарезанные кадры."""
        with tempfile.TemporaryDirectory() as tmp:
            out = creative.analyse(_make_clip(Path(tmp)))
            assert "motion" in out["parts"], sorted(out["parts"])
            assert out["parts"]["look"]["outcome"] == PASS, out["parts"]["look"]["note"]

    def test_the_frames_are_cleaned_up_afterwards(self) -> None:
        """Кадры живут только на время разбора: временный каталог удаляется
        даже если прибор внутри упал."""
        with tempfile.TemporaryDirectory() as tmp:
            before = set(Path(tempfile.gettempdir()).glob("tmp*"))
            creative.analyse(_make_clip(Path(tmp)))
            leaked = set(Path(tempfile.gettempdir()).glob("tmp*")) - before
            assert not [d for d in leaked if (d / "frame_001.jpg").exists()], sorted(leaked)


class TheMiddleFrameIsMeasuredNotTheFirst(unittest.TestCase):
    """У ролика первый кадр часто титульный или ещё не разогнавшийся, и мерить
    по нему текстуру значит мерить не то. Выбор середины — решение, поэтому у
    него должен быть сторож: без этого теста подмена середины на первый кадр не
    красила НИЧЕГО."""

    def _two_part_clip(self, into: Path) -> Path:
        """Первая половина чёрная, вторая белая. Яркость и скажет, что мерили."""
        import imageio_ffmpeg

        out = into / "twopart.mp4"
        subprocess.run(
            [
                imageio_ffmpeg.get_ffmpeg_exe(),
                "-y",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                "color=c=black:s=160x120:r=10:d=1",
                "-f",
                "lavfi",
                "-i",
                "color=c=white:s=160x120:r=10:d=1",
                "-filter_complex",
                "[0:v][1:v]concat=n=2:v=1[v]",
                "-map",
                "[v]",
                "-pix_fmt",
                "yuv420p",
                str(out),
            ],
            capture_output=True,
            check=False,
        )
        return out

    def test_the_look_reads_the_bright_half_not_the_black_one(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            clip = self._two_part_clip(Path(tmp))
            out = creative.analyse(clip)
            look = out["parts"]["look"]
            assert look["outcome"] == PASS, look["note"]
            mean = float(look["measurements"]["luminance_mean"])
            # Первый кадр чёрный: если бы мерили его, было бы около нуля.
            assert mean > 100, f"яркость {mean}: похоже, померили первый кадр"

    # ЧЕСТНО ПРО СИЛУ ЭТОГО СТОРОЖА: он ловит единственную границу, которая
    # что-то решает, — первый кадр против любого другого. Подмена середины на
    # ПОСЛЕДНИЙ кадр не красит ничего, и это не дыра: обоснование было «первый
    # часто титульный», а середина против конца ничем не обоснована и потому
    # тестом не сторожится. Изображать здесь проверку значило бы поставить
    # сторожа у решения, которого никто не принимал.

    def test_the_first_frame_really_is_dark(self) -> None:
        """Негативный контроль на сам стенд: если бы оба кадра были одинаковы,
        предыдущий тест ничего не различал бы."""
        with tempfile.TemporaryDirectory() as tmp:
            clip = self._two_part_clip(Path(tmp))
            got = creative.frames_from_video(clip, Path(tmp) / "frames")
            assert got["outcome"] == PASS, got["note"]
            first = creative.look(got["frames"][0])
            assert float(first["measurements"]["luminance_mean"]) < 60


class AStillIsNotAVideo(unittest.TestCase):
    def test_an_image_path_is_not_decoded(self) -> None:
        """Негативный контроль (И5): если бы декодировалось всё подряд, каждый
        разбор картинки платил бы за запуск ffmpeg впустую."""
        from PIL import Image

        with tempfile.TemporaryDirectory() as tmp:
            still = Path(tmp) / "shot.jpg"
            Image.new("RGB", (64, 64), (30, 40, 50)).save(still)
            out = creative.analyse(still)
            assert "motion" not in out["parts"], sorted(out["parts"])
            assert "video_decode" not in out["parts"]

    def test_the_suffix_list_is_what_the_docs_say(self) -> None:
        """Литералы, а не импорт проверяемого значения (Т2)."""
        for suffix in (".mp4", ".mov", ".webm"):
            assert suffix in creative.VIDEO_SUFFIXES
        assert ".jpg" not in creative.VIDEO_SUFFIXES
        assert ".png" not in creative.VIDEO_SUFFIXES


class AClipItCannotReadSaysSo(unittest.TestCase):
    def test_a_file_that_is_not_a_video_is_could_not_measure(self) -> None:
        """Р1: «не прочиталось» — третий исход, а не тихий пропуск и не провал."""
        with tempfile.TemporaryDirectory() as tmp:
            broken = Path(tmp) / "broken.mp4"
            broken.write_bytes(b"not a video at all")
            got = creative.frames_from_video(broken, Path(tmp) / "frames")
            assert got["outcome"] == UNMEASURED, got["note"]
            assert got["frames"] == []
            assert got["unmeasured"] == 1

    def test_a_failed_decode_is_NAMED_in_the_analysis(self) -> None:
        """Разбор битого ролика не должен выглядеть как разбор картинки:
        прибор обязан сказать, что декодировать не вышло."""
        with tempfile.TemporaryDirectory() as tmp:
            broken = Path(tmp) / "broken.mp4"
            broken.write_bytes(b"not a video at all")
            out = creative.analyse(broken)
            assert "video_decode" in out["parts"], sorted(out["parts"])
            assert out["parts"]["video_decode"]["outcome"] == UNMEASURED


class FramesYouAlreadyHaveWin(unittest.TestCase):
    def test_explicit_frames_skip_the_decode(self) -> None:
        """Кто уже нарезал кадры, не платит за вторую нарезку."""
        from PIL import Image

        with tempfile.TemporaryDirectory() as tmp:
            frames = []
            for i in range(3):
                path = Path(tmp) / f"f{i}.jpg"
                Image.new("RGB", (64, 64), (10 * i, 20, 30)).save(path)
                frames.append(str(path))
            clip = Path(tmp) / "never_read.mp4"
            clip.write_bytes(b"not a video at all")
            out = creative.analyse(clip, frames=frames)
            assert "video_decode" not in out["parts"], "битый файл не читался — и не должен был"
            assert "motion" in out["parts"]


# --- G12 (validator 2026-10-14): what lipsync needs from a clip, and a face
# detector that does not need insightface -------------------------------------

REPO = Path(__file__).resolve().parents[3]
SELFIE = REPO / "assets" / "fork_client_selfie_f.png"


def _clip_with_audio(into: Path, *, tone_s: float = 1.5, pad_s: float = 1.5) -> Path:
    """3 s of testsrc at 10 fps, 160x120, with a 440 Hz tone then silence."""
    import imageio_ffmpeg

    out = into / "av.mp4"
    total = tone_s + pad_s
    subprocess.run(
        [
            imageio_ffmpeg.get_ffmpeg_exe(),
            "-y",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"testsrc=size=160x120:rate=10:duration={total}",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={tone_s},apad=pad_dur={pad_s}",
            "-shortest",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-ar",
            "48000",
            str(out),
        ],
        capture_output=True,
        check=False,
    )
    return out


class ContainerAndSound(unittest.TestCase):
    def test_the_container_fields_lipsync_needs_are_read(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            info = creative.media_info(_clip_with_audio(Path(tmp)))
        assert info["outcome"] == PASS, info["note"]
        c = info["container"]
        assert (c["duration_s"], c["fps"], c["width"], c["height"]) == (3.0, 10.0, 160, 120)
        assert c["video_codec"] == "h264"
        assert c["has_audio"] is True
        assert c["sample_rate"] == 48000

    def test_ffmpeg_reads_the_same_fields_when_pyav_is_absent(self) -> None:
        from unittest import mock

        with tempfile.TemporaryDirectory() as tmp:
            clip = _clip_with_audio(Path(tmp))
            with mock.patch.object(creative, "_probe_av", return_value=None):
                info = creative.media_info(clip)
        c = info["container"]
        assert c["read_by"] == "ffmpeg -i"
        assert (c["fps"], c["width"], c["height"], c["sample_rate"]) == (10.0, 160, 120, 48000)
        assert c["has_audio"] is True

    def test_a_silent_clip_has_no_audio_track_and_that_is_a_measurement(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = creative.analyse(_make_clip(Path(tmp)))
        assert out["parts"]["container"]["container"]["has_audio"] is False
        audio = out["parts"]["audio"]
        assert audio["outcome"] == PASS and audio["has_audio"] is False
        assert "audio" not in [c["instrument"] for c in out["could_not_run"]]

    def test_loudness_and_the_silent_half(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            got = creative.audio_levels(_clip_with_audio(Path(tmp)))
        assert got["outcome"] == PASS, got["note"]
        assert -40.0 < got["loudness_lufs"] < -10.0
        assert 0.4 <= got["silence_ratio"] <= 0.6, got["silence_ratio"]

    def test_negative_control_a_tone_all_the_way_is_not_silent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            got = creative.audio_levels(_clip_with_audio(Path(tmp), tone_s=3.0, pad_s=0.0))
        assert got["silence_ratio"] == 0.0, got["note"]

    def _wav(self, into: Path, graph: str) -> Path:
        import imageio_ffmpeg

        out = into / "a.wav"
        subprocess.run(
            [
                imageio_ffmpeg.get_ffmpeg_exe(),
                "-y",
                "-loglevel",
                "error",
                "-filter_complex",
                graph,
                "-map",
                "[out]",
                str(out),
            ],
            capture_output=True,
            check=False,
        )
        return out

    def test_a_quiet_hum_below_the_threshold_counts_as_silence(self) -> None:
        """T1 for SILENCE_NOISE_DB: a -60 dBFS hum is silence at -50, and a
        threshold moved far down (digital zero only) would miss it."""
        with tempfile.TemporaryDirectory() as tmp:
            wav = self._wav(
                Path(tmp),
                "sine=f=440:d=1.5[a];sine=f=440:d=1.5,volume=-60dB[b];"
                "[a][b]concat=n=2:v=0:a=1[out]",
            )
            got = creative.audio_levels(wav)
        assert 0.4 <= got["silence_ratio"] <= 0.6, got["note"]

    def test_pauses_between_words_are_not_silence(self) -> None:
        """T1 for SILENCE_MIN_SECONDS: 0.2 s gaps (a pause between words) must
        not make speech 'silent'."""
        part = "sine=f=440:d=0.5[t{n}];anullsrc=r=44100:cl=mono,atrim=0:0.2[g{n}];"
        graph = "".join(part.format(n=n) for n in range(4))
        graph += "".join(f"[t{n}][g{n}]" for n in range(4)) + "concat=n=8:v=0:a=1[out]"
        with tempfile.TemporaryDirectory() as tmp:
            got = creative.audio_levels(self._wav(Path(tmp), graph))
        assert got["silence_ratio"] == 0.0, got["note"]

    def test_the_silence_constants_are_literals(self) -> None:
        assert creative.SILENCE_NOISE_DB == -50
        assert creative.SILENCE_MIN_SECONDS == 0.3

    def test_analyse_of_a_clip_carries_container_and_audio(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = creative.analyse(_clip_with_audio(Path(tmp)))
        assert out["parts"]["container"]["outcome"] == PASS
        assert out["parts"]["audio"]["silence_ratio"] is not None

    def test_a_still_image_has_no_container_block(self) -> None:
        out = creative.analyse(SELFIE)
        assert "container" not in out["parts"] and "audio" not in out["parts"]


class VideoLookAndFramesLookAreApart(unittest.TestCase):
    """G12: with frames_dir the look of the HANDED FRAMES replaced the look of
    the file while `input.path` still pointed at the mp4."""

    def test_the_video_is_measured_on_its_own_frame(self) -> None:
        from PIL import Image

        with tempfile.TemporaryDirectory() as tmp:
            import imageio_ffmpeg

            clip = Path(tmp) / "white.mp4"
            subprocess.run(
                [
                    imageio_ffmpeg.get_ffmpeg_exe(),
                    "-y",
                    "-loglevel",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=c=white:s=160x120:r=10:d=2",
                    "-pix_fmt",
                    "yuv420p",
                    str(clip),
                ],
                capture_output=True,
                check=False,
            )
            frames = []
            for i in range(3):
                path = Path(tmp) / f"f{i}.png"
                Image.new("RGB", (64, 64), (5, 5, 5)).save(path)
                frames.append(str(path))
            out = creative.analyse(clip, frames=frames)
        look, frames_look = out["parts"]["look"], out["parts"]["frames_look"]
        assert look["measurements"]["luminance_mean"] > 200, "the white video itself"
        assert frames_look["measurements"]["luminance_mean"] < 20, "the dark handed frames"
        assert (look["measurements"]["width"], look["measurements"]["height"]) == (160, 120)
        assert "middle frame" in look["measured_on"]

    def test_without_frames_there_is_no_frames_look(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = creative.analyse(_make_clip(Path(tmp)))
        assert "frames_look" not in out["parts"]


class FaceWithoutInsightface(unittest.TestCase):
    def test_the_selfie_has_one_large_face(self) -> None:
        got = creative.faces_opencv(SELFIE)
        assert got["why"] == "", got["why"]
        assert len(got["faces"]) == 1
        assert got["faces"][0]["face_px"] > 300, got["faces"]

    def test_two_people_are_two_faces(self) -> None:
        from PIL import Image

        with tempfile.TemporaryDirectory() as tmp:
            one = Image.open(SELFIE).convert("RGB")
            both = Image.new("RGB", (one.width * 2, one.height))
            both.paste(one, (0, 0))
            both.paste(one.transpose(Image.Transpose.FLIP_LEFT_RIGHT), (one.width, 0))
            path = Path(tmp) / "two.png"
            both.save(path)
            got = creative.faces_opencv(path)
        assert len(got["faces"]) == 2, got

    def test_negative_control_a_grey_frame_has_no_face(self) -> None:
        from PIL import Image

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "grey.png"
            Image.new("RGB", (400, 400), (128, 128, 128)).save(path)
            assert creative.faces_opencv(path)["faces"] == []

    def test_intake_runs_on_the_fallback_and_says_which_detector(self) -> None:
        from unittest import mock

        absent = {"faces": None, "why": "ModuleNotFoundError: No module named 'insightface'"}
        with mock.patch("lipsync.fork_intake.read_faces", return_value=absent):
            out = creative.intake_of(SELFIE)
        assert out["outcome"] == PASS, out["note"]
        assert out["detector"] == creative.DETECTOR_YUNET
        assert "opencv-yunet" in out["note"]
        assert "insightface" in out["primary_why"]

    def test_the_overall_answer_is_not_could_not_measure_for_lack_of_insightface(self) -> None:
        from unittest import mock

        absent = {"faces": None, "why": "ModuleNotFoundError: No module named 'insightface'"}
        with mock.patch("lipsync.fork_intake.read_faces", return_value=absent):
            out = creative.analyse(SELFIE)
        assert out["outcome"] == PASS, out["note"]
        assert out["could_not_run"] == []

    def test_a_tampered_model_is_refused_not_loaded(self) -> None:
        from unittest import mock

        with mock.patch.object(creative, "FACE_MODEL_SHA256", "0" * 64):
            got = creative.faces_opencv(SELFIE)
        assert got["faces"] is None and "sha256" in got["why"]

    def test_the_vendor_threshold_is_a_literal(self) -> None:
        assert creative.FACE_SCORE_MIN == 0.9
        assert creative.FACE_INPUT_SIDE == 640


class ThePlannerReadsTheFrameCheaply(unittest.TestCase):
    """Сборка 2026-10-15: `planner.frame_of` берёт стороны ролика из заголовка
    контейнера (тот же `media_info`, что `parts.container` у `analyse`), а не
    гоняет весь разбор — звук, раскадровку и детектор лиц — ради двух чисел."""

    def test_a_clip_is_sized_from_the_container_without_analyse(self) -> None:
        from unittest import mock

        from studio.planner import frame_of

        with tempfile.TemporaryDirectory() as tmp:
            clip = _make_clip(Path(tmp))

            def _boom(*_a: object, **_k: object) -> dict:
                raise AssertionError("full analyse was called for two numbers")

            with mock.patch.object(creative, "analyse", _boom):
                кадр, нота = frame_of(str(clip))
            assert кадр == (160, 120), нота
            assert нота == "160x120"

    def test_the_container_answer_matches_analyse(self) -> None:
        from studio.planner import frame_of

        with tempfile.TemporaryDirectory() as tmp:
            clip = _make_clip(Path(tmp))
            info = creative.analyse(clip)["parts"]["container"]["container"]
            кадр, _ = frame_of(str(clip))
            assert кадр == (int(info["width"]), int(info["height"]))

    def test_an_unreadable_clip_falls_back_to_the_full_analyse(self) -> None:
        from studio.planner import frame_of

        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.mp4"
            bad.write_bytes(b"not a video at all")
            кадр, нота = frame_of(str(bad))
            assert кадр is None
            assert нота.startswith("креатив не измерен"), нота


if __name__ == "__main__":
    unittest.main()
