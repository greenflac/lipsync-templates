"""Whose page is it? The table that decides the ladder's identity rungs.

Expected tiers are literals here, never imports of the ladder: an expected
value that travels with the code it checks cannot disagree with it.
"""

from __future__ import annotations

import unittest
from unittest import mock

from studio.selfrag import source_hosts as S
from studio.selfrag.facts import DEFAULT_FACTS_PATH, load_facts

VENDOR, PORTAL, BLOG = "vendor", "portal", "blog"


def tier(model: str, url: str) -> str:
    return S.classify(model, url, vendor_tier=VENDOR, portal_tier=PORTAL, blog_tier=BLOG)


class WhoOwnsThePage(unittest.TestCase):
    def test_the_vendors_own_page_is_the_first_rung(self) -> None:
        assert tier("kling-3.0", "https://kling.ai/docs/limits") == VENDOR
        assert tier("flux-2", "https://docs.bfl.ai/guides/edit") == VENDOR

    def test_a_vendor_page_belongs_to_ITS_model_and_not_to_a_rival(self) -> None:
        """`kling.ai` is the vendor for Kling and a competitor writing about Veo.

        Nothing in the base cites a rival vendor today; this is what keeps that
        true as it grows.
        """
        assert tier("kling-3.0", "https://kling.ai/x") == VENDOR
        assert tier("veo-3.1", "https://kling.ai/x") == BLOG

    def test_a_platform_that_runs_the_model_is_the_middle_rung(self) -> None:
        assert tier("wan-2.6-flash", "https://wavespeed.ai/models/alibaba/wan-2.6") == PORTAL
        assert tier("veo-3.1", "https://fal.ai/models/veo") == PORTAL

    def test_a_platforms_own_blog_post_is_a_blog_post(self) -> None:
        """MEASURED: 5 of the 11 platform URLs in the base are articles.

        The rung is earned by documenting an endpoint that answers, not by the
        domain it sits on.
        """
        assert tier("kling-3.0", "https://www.atlascloud.ai/blog/tips/video-length") == BLOG
        assert tier("veo-3.1", "https://piapi.ai/blogs/veo-3-1-api-pricing") == BLOG
        assert tier("runway-gen-4.5", "https://gaga.art/blog/runway-gen-4-5-review/") == BLOG

    def test_one_community_is_the_middle_rung_and_the_forum_around_it_is_not(self) -> None:
        """The owner named these on 2026-08-27: Civitai and the ComfyUI subreddit.

        A community where people post workflows WITH the results they got is
        the middle rung by the owner's own description of it. Reddit as a whole
        is a forum, so the rung is claimed by path and not by host — which is
        what the path prefix exists for.
        """
        comfy = "https://www.reddit.com/r/comfyui/comments/a/wan_workflow/"
        assert tier("wan-2.6-flash", comfy) == PORTAL
        assert tier("wan-2.6-flash", "https://old.reddit.com/r/comfyui/comments/a/x/") == PORTAL
        assert tier("wan-2.6-flash", "https://www.reddit.com/r/aww/comments/a/x/") == BLOG
        assert tier("flux-2", "https://civitai.com/api/v1/images?modelId=1") == PORTAL

    def test_a_blog_shaped_word_inside_a_longer_segment_is_not_a_blog_path(self) -> None:
        assert tier("veo-3.1", "https://fal.ai/blogging-api/veo") == PORTAL

    def test_a_shared_host_is_split_by_path_because_owners_share_it(self) -> None:
        """`github.com/Wan-Video/` is Alibaba's repo; `Vchitect/RAPO` is a paper's."""
        assert tier("wan-2.6-flash", "https://github.com/Wan-Video/Wan2.2") == VENDOR
        assert tier("wan-2.6-flash", "https://github.com/Vchitect/RAPO") == BLOG

    def test_www_is_not_a_different_host(self) -> None:
        assert tier("kling-3.0", "https://www.kling.ai/docs") == VENDOR

    def test_everything_unnamed_is_the_third_rung(self) -> None:
        for url in (
            "https://the-decoder.com/sora-2",
            "https://some-host-nobody-tabled.example/x",
            "not a url at all",
            "",
        ):
            assert tier("veo-3.1", url) == BLOG, url

    def test_an_unknown_model_earns_no_vendor_rung_from_a_vendor_host(self) -> None:
        assert tier("model-nobody-has-tabled", "https://kling.ai/docs") == BLOG

    def test_a_version_nobody_tabled_still_knows_its_vendor(self) -> None:
        """Found by the blind control set on 2026-08-27.

        It recorded a `deepmind.google` claim about `veo-3` while the table
        listed `veo-3.1`, and was refused. A vendor does not change when the
        version does, so the table is keyed by family and an unreleased version
        is not locked out of the first rung.
        """
        assert tier("veo-3", "https://deepmind.google/veo") == VENDOR
        assert tier("kling-4.0", "https://kling.ai/docs") == VENDOR

    def test_a_family_does_not_swallow_a_name_that_merely_starts_the_same(self) -> None:
        assert tier("wandering-model", "https://wan.video/x") == BLOG
        assert tier("sorabase", "https://openai.com/x") == BLOG

    def test_the_longest_family_wins_so_a_split_is_possible_later(self) -> None:
        table = {"acme": ("acme.test",), "acme-pro": ("pro.acme.test",)}
        with mock.patch.dict(S.VENDOR_SOURCES, table, clear=True):
            assert S.vendor_sources_for("acme-pro-2") == ("pro.acme.test",)
            assert S.vendor_sources_for("acme-2") == ("acme.test",)


class TheTableAgainstTheRealBase(unittest.TestCase):
    """The classification is only worth anything if it discriminates.

    House rule И5: an instrument with no negative control measures nothing. So
    this asserts the real fact base lands on all three rungs, with the counts
    measured on 2026-08-27 as literals — if a table edit sweeps everything onto
    one rung, that is a failure and not a tidier file.
    """

    def test_the_real_base_lands_on_all_three_rungs(self) -> None:
        # `load_facts` and not the raw lines: since 2026-08-27 the file is a
        # log where a later row supersedes an earlier one about the same claim
        # and a withdrawal removes it, so the file's lines outnumber its claims.
        # Counting
        # lines would count corrections twice and count retracted claims as
        # standing — measuring the file's history rather than what it asserts.
        facts = load_facts(DEFAULT_FACTS_PATH)
        assert len(facts) == 59, "the measured base; update the literals below with it"

        seen = {VENDOR: 0, PORTAL: 0, BLOG: 0}
        for fact in facts:
            seen[tier(fact.model, fact.source_url)] += 1

        # MEASURED 2026-08-27 by running this classification over the base.
        # `vendor` counts the one `probe` row too, because it cites
        # api.klingai.com: the URL is the vendor's, while the rung the row
        # keeps is `probe`, which describes how the fact was obtained.
        assert seen[VENDOR] == 18, seen
        assert seen[PORTAL] == 12, seen
        assert seen[BLOG] == 29, seen

    def test_no_rung_is_empty_which_is_what_a_useless_table_looks_like(self) -> None:
        with mock.patch.dict(S.VENDOR_SOURCES, {}, clear=True):
            with mock.patch.object(S, "PORTAL_SOURCES", ()):
                assert tier("kling-3.0", "https://kling.ai/docs") == BLOG


if __name__ == "__main__":
    unittest.main()
