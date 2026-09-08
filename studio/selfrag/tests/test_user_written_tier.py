"""Пользовательский текст на портале: одна ступень, независимо от формы ссылки.

ИЗМЕРЕНО 2026-08-31, при подготовке к чтению обсуждений HuggingFace: одно и то
же обсуждение получало РАЗНЫЙ тир в зависимости от того, какую ссылку выбрал
записывающий — человеческую или API. Понижение применялось только внутри
вендорской ветки, и мимо неё пользовательский текст поднимался на портальную
ступень.

Ожидаемые значения — литералы (правило Т2).
"""

from __future__ import annotations

import unittest

from studio.selfrag import source_hosts as sh


def тир(url: str, model: str = "minimax-h3") -> str:
    return sh.classify(model, url, vendor_tier="vendor", portal_tier="portal", blog_tier="blog")


class OneRungPerText(unittest.TestCase):
    def test_the_same_discussion_gets_one_rung_in_both_url_forms(self):
        человеческая = тир("https://huggingface.co/MiniMaxAI/MiniMax-H3/discussions/42")
        апишная = тир("https://huggingface.co/api/models/MiniMaxAI/MiniMax-H3/discussions")
        self.assertEqual(человеческая, апишная)
        self.assertEqual(человеческая, "blog")

    def test_the_vendors_own_card_keeps_the_top_rung(self):
        """Понижение бьёт по обсуждениям, а не по странице модели."""
        self.assertEqual(тир("https://huggingface.co/MiniMaxAI/MiniMax-H3"), "vendor")

    def test_the_portal_api_itself_is_still_the_portal(self):
        self.assertEqual(тир("https://huggingface.co/api/models/MiniMaxAI/MiniMax-H3"), "portal")


class WhereUsersAreThePoint(unittest.TestCase):
    def test_a_comfyui_thread_keeps_the_portal_rung(self):
        """Решение владельца 2026-08-27: там пользовательское и есть суть."""
        self.assertEqual(тир("https://reddit.com/r/comfyui/comments/abc/workflow"), "portal")

    def test_civitai_keeps_it_too(self):
        self.assertEqual(тир("https://civitai.com/models/123"), "portal")

    def test_an_issue_on_an_ordinary_portal_does_not(self):
        self.assertEqual(тир("https://replicate.com/some/model/issues/7"), "blog")

    def test_the_exception_list_is_a_subset_of_the_portals(self):
        """Опечатка в списке-исключении молча вернула бы прежнее поведение."""
        self.assertTrue(sh.PORTALS_WHERE_USERS_ARE_THE_POINT <= set(sh.PORTAL_SOURCES))


if __name__ == "__main__":
    unittest.main()
