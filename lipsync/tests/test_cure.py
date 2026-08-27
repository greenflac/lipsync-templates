"""Test the remedy commands, on BOTH shells — the Windows half had never run.

WHY: every branch in this module is chosen by `WINDOWS`, and `WINDOWS` is
decided once at import time from `os.name`. Every run of this suite has been on
Linux, so half of every function in the file had never been executed by
anything. A remedy printed in a shell that cannot run it is worse than no
remedy: the reader pastes it and gets an error about their own machine.

`WINDOWS` is patched on the module object rather than by faking `os.name`,
because the functions read the module global at call time.

Expected strings are literals. Importing them from `cure` would let the command
change and these tests follow it in silence.
"""

from __future__ import annotations

import unittest
from unittest import mock

from lipsync import cure

KEY = "POLLINATIONS_API_KEY"


class _OnWindows:
    """Run the body as if the module had been imported on Windows."""

    def __enter__(self):
        self._patch = mock.patch.object(cure, "WINDOWS", True)
        self._patch.start()
        return self

    def __exit__(self, *exc):
        self._patch.stop()
        return False


class _OnPosix:
    def __enter__(self):
        self._patch = mock.patch.object(cure, "WINDOWS", False)
        self._patch.start()
        return self

    def __exit__(self, *exc):
        self._patch.stop()
        return False


class TheShellIsReadAtCallTimeNotGuessed(unittest.TestCase):
    def test_the_flag_is_decided_from_the_operating_system_name(self) -> None:
        """Reloaded under a patched `os.name`, because the flag is set at import."""
        import importlib

        with mock.patch("os.name", "nt"):
            self.assertTrue(importlib.reload(cure).WINDOWS)
        with mock.patch("os.name", "posix"):
            self.assertFalse(importlib.reload(cure).WINDOWS)
        self.addCleanup(importlib.reload, cure)

    def test_the_switch_actually_switches(self) -> None:
        """Negative control: the two shells must not produce the same string."""
        with _OnPosix():
            posix = cure.mkdir("/tmp/x")
        with _OnWindows():
            windows = cure.mkdir("/tmp/x")
        self.assertNotEqual(posix, windows)


class MkdirRunsInTheShellItIsPrintedIn(unittest.TestCase):
    def test_posix_creates_parents(self) -> None:
        with _OnPosix():
            self.assertEqual(cure.mkdir("/tmp/a/b"), "mkdir -p /tmp/a/b")

    def test_windows_quotes_the_path_because_it_may_hold_spaces(self) -> None:
        with _OnWindows():
            self.assertEqual(cure.mkdir(r"C:\Users\Ann Lee\.x"), 'mkdir "C:\\Users\\Ann Lee\\.x"')

    def test_the_posix_form_has_no_quotes_to_confuse_the_p_flag(self) -> None:
        with _OnPosix():
            self.assertNotIn('"', cure.mkdir("/tmp/a"))


class DownloadUsesTheOneToolBothMachinesHave(unittest.TestCase):
    def test_posix(self) -> None:
        with _OnPosix():
            self.assertEqual(
                cure.download("https://h/m.bin", "/tmp/m.bin"),
                "curl -sSL -o /tmp/m.bin https://h/m.bin",
            )

    def test_windows_quotes_only_the_destination(self) -> None:
        with _OnWindows():
            got = cure.download("https://h/m.bin", r"C:\m.bin")
            self.assertEqual(got, 'curl -sSL -o "C:\\m.bin" https://h/m.bin')

    def test_both_shells_reach_for_curl(self) -> None:
        for shell in (_OnPosix(), _OnWindows()):
            with shell:
                self.assertTrue(cure.download("https://h/x", "x").startswith("curl "))


class HomeIsWrittenForTheShellNotForPython(unittest.TestCase):
    def test_posix_bare(self) -> None:
        with _OnPosix():
            self.assertEqual(cure.home(), "~")

    def test_posix_with_a_subdirectory(self) -> None:
        with _OnPosix():
            self.assertEqual(cure.home(".mediapipe"), "~/.mediapipe")

    def test_windows_bare_uses_the_variable_the_shell_expands(self) -> None:
        with _OnWindows():
            self.assertEqual(cure.home(), "%USERPROFILE%")

    def test_windows_joins_with_a_backslash(self) -> None:
        with _OnWindows():
            self.assertEqual(cure.home(".mediapipe"), "%USERPROFILE%\\.mediapipe")

    def test_neither_shell_is_handed_a_python_style_path(self) -> None:
        """A `pathlib` join would put a forward slash into the Windows form."""
        with _OnWindows():
            self.assertNotIn("/", cure.home(".x"))


class SetEnvNamesTheCommandTheReaderCanActuallyRun(unittest.TestCase):
    """This is what `pollinations._key` prints when the key is missing."""

    def test_posix_is_a_single_export(self) -> None:
        with _OnPosix():
            self.assertEqual(cure.set_env(KEY, "sk_..."), f"export {KEY}=sk_...")

    def test_posix_has_one_line_because_one_command_is_enough(self) -> None:
        with _OnPosix():
            self.assertEqual(len(cure.set_env(KEY, "sk_...").splitlines()), 1)

    def test_windows_offers_the_session_and_the_permanent_form(self) -> None:
        with _OnWindows():
            got = cure.set_env(KEY, "sk_...")
        self.assertIn(f'$env:{KEY} = "sk_..."', got)
        self.assertIn(f'setx {KEY} "sk_..."', got)
        self.assertEqual(len(got.splitlines()), 2)

    def test_the_default_placeholder_is_visibly_a_placeholder(self) -> None:
        with _OnPosix():
            self.assertEqual(cure.set_env(KEY), f"export {KEY}=...")

    def test_no_export_reaches_a_windows_reader(self) -> None:
        """The defect this branch exists to prevent."""
        with _OnWindows():
            self.assertNotIn("export ", cure.set_env(KEY, "sk_..."))


class TheGpuDoctorsHelperIsGone(unittest.TestCase):
    """`py_snippet` built one-liners for `preflight_gpu.py`, which is not here."""

    def test_the_snippet_builder_is_gone(self) -> None:
        self.assertFalse(hasattr(cure, "py_snippet"))

    def test_the_interpreter_name_it_needed_is_gone_with_it(self) -> None:
        self.assertFalse(hasattr(cure, "PY"))

    def test_the_sweep_can_see_a_name_that_is_present(self) -> None:
        """Negative control on the two checks above."""
        self.assertTrue(hasattr(cure, "set_env"))


if __name__ == "__main__":
    unittest.main()
