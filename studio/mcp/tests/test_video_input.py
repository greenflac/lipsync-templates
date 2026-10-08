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


if __name__ == "__main__":
    unittest.main()
