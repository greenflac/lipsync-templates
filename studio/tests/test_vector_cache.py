"""Кэш векторов: ключ — хеш текста, а не номер строки.

ЗАЧЕМ ОН ЕСТЬ. ИЗМЕРЕНО 2026-09-02 на 4 CPU без GPU: сборка индекса без
плотного канала 1.5 с, `attach_dense` — 160.1 с на 13 426 текстах, из них
загрузка модели 3.1 с. Сервер собирает индекс в `:memory:`, поэтому эти
157 секунд счёта эмбеддингов платились при КАЖДОМ старте, а ждал их первый
вызов пользователя: 162 с на первый `write_lipsync_prompt` против 0.1 с на
второй. С кэшем вторая сборка — 3.0 с, векторы побайтно те же.

Сеть здесь не нужна и не трогается (Т4): модель не грузится, векторы —
подставные байты. Проверяется ровно то, что и должно, — ключ, срок жизни и
поведение при отказе файла.

ЛЕЖИТ В `studio/tests/`, а не в `studio/mcp/tests/`, и это не вкусовщина:
`studio/knowledge.py` затенён для проверки типов одноимённым каталогом рядом,
поэтому его тесты живут там, где эта проверка их не гоняет, — рядом с
`test_knowledge.py`, который проверяет тот же модуль.
"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from studio import knowledge as k  # noqa: F401  (тот же импорт, что в test_knowledge.py)

МОДЕЛЬ = "модель-для-теста"
ДРУГАЯ = "другая-модель"


class КлючЭтоТекст(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.путь = Path(self._dir.name) / "vectors.sqlite3"

    def test_один_и_тот_же_текст_даёт_один_и_тот_же_ключ(self) -> None:
        self.assertEqual(k._text_sha("тёплый янтарный свет"), k._text_sha("тёплый янтарный свет"))

    def test_разный_текст_даёт_разные_ключи(self) -> None:
        """Половина контроля, без которой ключ мог бы быть константой (И5)."""
        self.assertNotEqual(k._text_sha("тёплый свет"), k._text_sha("холодный свет"))

    def test_записанное_читается_обратно(self) -> None:
        sha = k._text_sha("текст")
        self.assertEqual(k._store_vectors(self.путь, МОДЕЛЬ, 4, [(sha, b"0123456789abcdef")]), 1)
        self.assertEqual(k._cached_vectors(self.путь, МОДЕЛЬ, [sha]), {sha: b"0123456789abcdef"})

    def test_векторы_другой_модели_не_подхватываются(self) -> None:
        """Самое дорогое: вектор чужой модели под нашим текстом — это ответ на
        вопрос, которого никто не задавал, и молча."""
        sha = k._text_sha("текст")
        k._store_vectors(self.путь, ДРУГАЯ, 4, [(sha, b"0123456789abcdef")])
        self.assertEqual(k._cached_vectors(self.путь, МОДЕЛЬ, [sha]), {})

    def test_чужого_текста_в_кэше_нет(self) -> None:
        k._store_vectors(self.путь, МОДЕЛЬ, 4, [(k._text_sha("а"), b"0123456789abcdef")])
        self.assertEqual(k._cached_vectors(self.путь, МОДЕЛЬ, [k._text_sha("б")]), {})

    def test_пустой_кэш_это_не_ошибка(self) -> None:
        """Р1: «ничего не нашлось» и «не смогли открыть» — разные вещи, и обе
        не должны ронять сборку."""
        self.assertEqual(k._cached_vectors(self.путь, МОДЕЛЬ, [k._text_sha("а")]), {})

    def test_кэш_можно_выключить(self) -> None:
        """`None` — это то, чем пользуются тесты, чтобы не писать в репозиторий."""
        self.assertEqual(k._store_vectors(None, МОДЕЛЬ, 4, [("sha", b"abcd")]), 0)
        self.assertEqual(k._cached_vectors(None, МОДЕЛЬ, ["sha"]), {})

    def test_битый_файл_кэша_не_роняет_сборку(self) -> None:
        """Кэш — удобство, а не источник истины: его отказ обязан быть тихим и
        не превращаться в отказ индекса."""
        self.путь.write_bytes("это не sqlite".encode("utf-8"))
        self.assertEqual(k._cached_vectors(self.путь, МОДЕЛЬ, ["sha"]), {})
        self.assertEqual(k._store_vectors(self.путь, МОДЕЛЬ, 4, [("sha", b"abcd")]), 0)

    def test_кэш_старой_схемы_не_роняет_сборку(self) -> None:
        """Дыра, найденная мутацией: файл может быть НАСТОЯЩИМ sqlite и всё
        равно негодным — например, оставшимся от прошлой схемы. `CREATE TABLE
        IF NOT EXISTS` такой таблицы не исправит, и запрос упадёт уже ВНУТРИ
        чтения, мимо защиты на открытии."""
        with sqlite3.connect(str(self.путь)) as conn:
            conn.execute("CREATE TABLE vector_cache (что_то_другое INTEGER)")
        self.assertEqual(k._cached_vectors(self.путь, МОДЕЛЬ, ["sha"]), {})
        self.assertEqual(k._store_vectors(self.путь, МОДЕЛЬ, 4, [("sha", b"abcd")]), 0)

    def test_запись_переживает_переоткрытие(self) -> None:
        sha = k._text_sha("текст")
        k._store_vectors(self.путь, МОДЕЛЬ, 4, [(sha, b"0123456789abcdef")])
        with sqlite3.connect(str(self.путь)) as conn:
            (сколько,) = conn.execute("SELECT count(*) FROM vector_cache").fetchone()
        self.assertEqual(сколько, 1)
        self.assertIn(sha, k._cached_vectors(self.путь, МОДЕЛЬ, [sha]))

    def test_много_текстов_читаются_одним_заходом(self) -> None:
        """Живой корпус — 13 426 текстов, а sqlite не берёт столько параметров
        в один IN. Разбиение на куски проверяется числом больше предела."""
        строки = [(k._text_sha(f"текст {i}"), b"0123456789abcdef") for i in range(1200)]
        k._store_vectors(self.путь, МОДЕЛЬ, 4, строки)
        найдено = k._cached_vectors(self.путь, МОДЕЛЬ, [sha for sha, _ in строки])
        self.assertEqual(len(найдено), 1200)


if __name__ == "__main__":
    unittest.main()
