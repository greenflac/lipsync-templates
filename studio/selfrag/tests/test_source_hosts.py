"""Whose page is it? The table that decides the ladder's identity rungs.

Expected tiers are literals here, never imports of the ladder: an expected
value that travels with the code it checks cannot disagree with it.
"""

from __future__ import annotations

import unittest
from unittest import mock

from studio.selfrag import source_hosts as S
from studio.selfrag.facts import DEFAULT_FACTS_PATH, Fact, load_facts

VENDOR, PORTAL, BLOG = "vendor", "portal", "blog"


def tier(model: str, url: str) -> str:
    return S.classify(model, url, vendor_tier=VENDOR, portal_tier=PORTAL, blog_tier=BLOG)


def first_hand_coverage(facts) -> tuple[int, int, int]:
    """How many MODELS the base can answer about from first hand, not how many rows.

    Returns `(models, with_a_vendor_source, with_a_source_above_blog)`. Counted
    per model and not per row on purpose — see
    `test_the_real_base_rests_on_first_hand_sources` for why the row count
    stopped meaning what it used to mean.

    Kept out of the test bodies (house rule Т5) so the negative control below
    can run the same code on a base built by hand, with no file and no network.
    """
    rungs: dict[str, set[str]] = {}
    for fact in facts:
        rungs.setdefault(fact.model, set()).add(tier(fact.model, fact.source_url))
    with_vendor = sum(1 for got in rungs.values() if VENDOR in got)
    above_blog = sum(1 for got in rungs.values() if VENDOR in got or PORTAL in got)
    return len(rungs), with_vendor, above_blog


#: CHOSEN, comfortably under the 163 MEASURED on 2026-09-01 (a base of 1575
#: claims about 466 models), so that harvesting more community material never
#: touches it and losing the vendor documents always does.
MODELS_WITH_A_VENDOR_SOURCE_FLOOR = 120

#: CHOSEN, well under the 0.895 MEASURED the same day on the same base. A share
#: and not a count, because the number of models grows and the share is what the
#: sentence "we mostly answer from first hand" actually means.
#:
#: Both floors live here and not in the test body so that the negative control
#: measures itself against the very numbers the real base is held to. A floor
#: mutated in either direction has to move both tests, which is what makes the
#: mutation visible.
ABOVE_BLOG_SHARE_FLOOR = 0.70


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

    def test_the_real_base_rests_on_first_hand_sources(self) -> None:
        """WHY THIS STOPPED PINNING AN EXACT COUNT, 2026-08-27.

        It asserted `len(facts) == <today's number>` with the comment "update
        the literals below with it". That worked while the base changed once a
        session. It stopped working the moment a harvest ran: agents append to
        the fact file continuously, so the assertion went red on every
        legitimate write, and the fix was always to retype the number. Six
        times in one afternoon — and a test whose only failure mode is "the
        number moved again" teaches its reader to retype the number WITHOUT
        LOOKING, which is worse than no test at all. Twice the count changed
        between re-pinning it and running it.

        What it was really guarding is still guarded, and now by properties
        that survive an append:

        * every rung is populated — a table edit that sweeps the base onto one
          rung is the failure this exists to catch,
        * the base rests on first-hand sources — see the next docstring section
          for what replaced the rung-size race that used to stand here,
        * the base does not SHRINK below a floor — the count may grow freely,
          but a collapse means claims stopped loading.

        MEASURED 2026-08-27 for the record, not asserted: 894 facts, 416
        vendor, 203 portal, 275 blog. `blog` is mostly arxiv.org, which is
        `paper` on the METHOD ladder and belongs to nobody in particular on
        the WHOSE-PAGE ladder this test asks about. The two ladders answering
        differently is the design.

        WHY `vendor` IS NO LONGER REQUIRED TO BE THE LARGEST RUNG, 2026-09-01.

        That assertion was a PROXY. What it meant was "we answer mostly from
        first hand"; what it counted was which bucket held the most ROWS after
        re-deriving every rung from its URL. Two things broke the link between
        the two.

        The premise moved. The owner asked for the practitioners' own reports
        to be collected — HuggingFace and Civitai threads by name. Material
        that is DELIBERATELY second-hand now enters the base by instruction, so
        the third rung growing is the instruction working, not damage.

        And the count never measured what it claimed anyway. The third bucket
        is not "hearsay": MEASURED on the 1698-claim base, its 600 rows are 308
        HuggingFace discussion threads, 214 arxiv.org, 31 github.com, 23
        raw.githubusercontent.com and 24 assorted hosts — and 236 of those 600
        are `paper` or `benchmark` on the METHOD ladder, i.e. sources nobody
        calls a blog, sitting on hosts this table has no opinion about. A
        vendor document also yields a BOUNDED number of rows (a model card
        answers a handful of attributes) while threads and papers yield
        unbounded ones, so the ratio tracked harvest shape, not provenance.

        The proof it had come loose is in its own history: the rung race went
        red on 2026-08-31 (`portal` 602 vs `vendor` 511) and was answered by
        EDITING THE HOST TABLE, not by fixing any data — a gate you can turn
        green by reclassifying is measuring the classifier, not the base. Its
        margin had been decaying all along under the same table: +131, +153,
        +134, +61, +32 across the HuggingFace waves. A guard whose margin is a
        coin flip on the next harvest is a guard that will be silenced.

        What stands here instead measures the intention directly and PER MODEL,
        which is the unit an answer is given about: how many models we can say
        anything about from first hand, and what share of them have any source
        above the third rung. Appending 123 practitioner observations moves
        neither number by one (MEASURED: 163 of 466 and 417 of 466, identical
        before and after) — which is the point, because those observations took
        nothing away. Deleting the model cards moves both to the floor; the
        negative control below is that base, built by hand.
        """
        # `load_facts` and not the raw lines: the file is a log where a later
        # row supersedes an earlier one about the same claim and a withdrawal
        # removes it, so its lines outnumber its claims. Counting lines would
        # count corrections twice and count retracted claims as standing.
        facts = load_facts(DEFAULT_FACTS_PATH)

        #: CHOSEN, well under the 894 measured, so ordinary growth never
        #: touches it and a base that stopped loading always does.
        FLOOR = 700
        assert len(facts) >= FLOOR, f"the base collapsed to {len(facts)} claims"

        seen = {VENDOR: 0, PORTAL: 0, BLOG: 0}
        for fact in facts:
            seen[tier(fact.model, fact.source_url)] += 1

        for rung in (VENDOR, PORTAL, BLOG):
            assert seen[rung] > 0, f"nothing lands on {rung}: {seen}"
        models, with_vendor, above_blog = first_hand_coverage(facts)

        assert with_vendor >= MODELS_WITH_A_VENDOR_SOURCE_FLOOR, (
            f"only {with_vendor} of {models} models have a first-hand source; "
            "the base stopped resting on vendor documents"
        )

        share = above_blog / models
        assert share >= ABOVE_BLOG_SHARE_FLOOR, (
            f"only {above_blog} of {models} models ({share:.1%}) have any source "
            "above the third rung: the base is becoming hearsay about models "
            "nobody documented"
        )

    def test_no_rung_is_empty_which_is_what_a_useless_table_looks_like(self) -> None:
        with mock.patch.dict(S.VENDOR_SOURCES, {}, clear=True):
            with mock.patch.object(S, "PORTAL_SOURCES", ()):
                assert tier("kling-3.0", "https://kling.ai/docs") == BLOG


class ABaseThatLostItsFirstHandSources(unittest.TestCase):
    """The negative control for the guard above (house rule И5).

    A guard that only ever sees a healthy base measures nothing, and the guard
    it replaced had exactly that defect: it could be turned green by editing the
    host table. These two bases are built by hand — no file, no network — and
    differ ONLY in who wrote the pages. The healthy one must clear both floors
    and the hollowed-out one must fail both, or the floors are decoration.

    The sizes are literals chosen to straddle the floors: 200 models is above
    the 120 vendor floor, and 200 of 200 is above the 0.70 share floor.
    """

    #: MEASURED nowhere — invented input, and deliberately so: this control has
    #: to keep working when the real base is ten times its present size.
    HOW_MANY_MODELS = 200

    def _facts(self, url_for) -> list[Fact]:
        return [
            Fact(
                model=f"kling-{i}",
                attribute="max_duration_seconds",
                value="10",
                source_url=url_for(i),
                tier="vendor",
            )
            for i in range(self.HOW_MANY_MODELS)
        ]

    def test_a_base_of_vendor_documents_clears_both_floors(self) -> None:
        models, with_vendor, above_blog = first_hand_coverage(
            self._facts(lambda i: f"https://kling.ai/docs/{i}")
        )
        assert (models, with_vendor, above_blog) == (200, 200, 200), (
            models,
            with_vendor,
            above_blog,
        )
        assert with_vendor >= MODELS_WITH_A_VENDOR_SOURCE_FLOOR
        assert above_blog / models >= ABOVE_BLOG_SHARE_FLOOR

    def test_THE_CONTROL_the_same_claims_from_nobody_in_particular_fail_both(self) -> None:
        """Same models, same claims, same count of rows — only the authorship
        is gone. This is the failure the old rung race was meant to catch and
        could not: here the base did not shrink and no rung was swept, the
        first-hand material simply stopped being there."""
        models, with_vendor, above_blog = first_hand_coverage(
            self._facts(lambda i: f"https://some-host-nobody-tabled.example/kling-{i}")
        )
        assert (models, with_vendor, above_blog) == (200, 0, 0), (
            models,
            with_vendor,
            above_blog,
        )
        assert not with_vendor >= MODELS_WITH_A_VENDOR_SOURCE_FLOOR
        assert not above_blog / models >= ABOVE_BLOG_SHARE_FLOOR

    def test_THE_OTHER_HALF_practitioner_threads_added_on_top_change_nothing(self) -> None:
        """The premise change, as a test. 400 community observations appended to
        the healthy base — more rows on the third rung than there are models —
        must not move either number by one, because they took nothing away."""
        base = self._facts(lambda i: f"https://kling.ai/docs/{i}")
        crowd = [
            Fact(
                model=f"kling-{i % self.HOW_MANY_MODELS}",
                attribute="observed_behaviour",
                value="15-second clip in about 5 minutes on an RTX 3060",
                source_url=f"https://huggingface.co/Kwai/Kling/discussions/{i}",
                tier="blog",
            )
            for i in range(400)
        ]
        assert first_hand_coverage(base + crowd) == (200, 200, 200)


class TheHostIsNotAlwaysTheAuthor(unittest.TestCase):
    """Found 2026-08-28 by an independent review, and verified on the shipped
    code before the fix existed: a Hugging Face DISCUSSION thread under a
    vendor's own org classified as `vendor`, because the org prefix is declared
    for the tier ladder. A user's complaint would have entered the base on the
    strongest rung and outranked the vendor's own model card.

    The distinction the fix rests on: a `/blog/` page on a vendor's host was
    written BY the vendor — their word in a marketing shape. A `/discussions/`
    page was written by somebody else and merely hosted. The ladder asks whose
    page it is; on these paths the answer is not the host's owner.
    """

    def test_a_user_thread_on_the_vendors_own_host_is_not_the_vendor(self) -> None:
        assert tier("ltx-2.5", "https://huggingface.co/Lightricks/LTX-2.5/discussions/12") == BLOG
        assert tier("wav2lip", "https://github.com/Rudrabha/Wav2Lip/issues/512") == BLOG

    def test_the_vendors_own_document_on_the_same_host_is_still_the_vendor(self) -> None:
        """The negative control. A rule that demoted the whole host would take
        the model card down with the thread, and the card is the single most
        load-bearing source in this base."""
        assert (
            tier("ltx-2.5", "https://huggingface.co/Lightricks/LTX-2.5/raw/main/README.md")
            == VENDOR
        )
        assert (
            tier("wav2lip", "https://raw.githubusercontent.com/Rudrabha/Wav2Lip/master/README.md")
            == VENDOR
        )

    def test_a_segment_that_merely_contains_the_word_is_not_a_match(self) -> None:
        """Whole segments only, like the blog rule beside it: a repository
        actually named `discussions-api` is not a discussion thread."""
        assert (
            tier("ltx-2.5", "https://huggingface.co/Lightricks/LTX-2.5-discussions/raw/main/R.md")
            == VENDOR
        )


if __name__ == "__main__":
    unittest.main()


class ComfyOrgIsAPlatformNotARepository(unittest.TestCase):
    """A path prefix, added 2026-08-30, and why it is not the whole host.

    ComfyUI's official template registry publishes EXECUTABLE graphs, and a
    closed model appears in one as the node type that calls it — MEASURED that
    day: `api_google_nano_banana2_image_edit.json` is three nodes,
    LoadImage -> GeminiNanoBanana2V2 -> SaveImage. A graph that runs is a
    statement about a running system, which is what `portal` is for.

    The negative control is the reason the prefix exists at all: the rest of
    `raw.githubusercontent.com` is anybody's repository, and promoting the whole
    host would launder every README on GitHub onto the middle rung.
    """

    def test_the_comfy_registry_is_a_portal(self) -> None:
        got = S.classify(
            "nano-banana-edit",
            "https://raw.githubusercontent.com/Comfy-Org/workflow_templates/main/templates/x.json",
            vendor_tier="vendor",
            portal_tier="portal",
            blog_tier="blog",
        )
        assert got == "portal", got

    def test_THE_NEGATIVE_CONTROL_the_rest_of_the_host_stays_a_blog(self) -> None:
        got = S.classify(
            "nano-banana-edit",
            "https://raw.githubusercontent.com/somebody/notes/main/README.md",
            vendor_tier="vendor",
            portal_tier="portal",
            blog_tier="blog",
        )
        assert got == "blog", got

    def test_a_lookalike_owner_does_not_inherit_the_rung(self) -> None:
        """`Comfy-Org-Fake` must not match `Comfy-Org/`: the prefix ends with a
        slash for exactly this reason."""
        got = S.classify(
            "nano-banana-edit",
            "https://raw.githubusercontent.com/Comfy-Org-Fake/x/main/a.json",
            vendor_tier="vendor",
            portal_tier="portal",
            blog_tier="blog",
        )
        assert got == "blog", got


class ОткрывшиесяХосты(unittest.TestCase):
    """Хосты, объявленные 2026-09-02 после перепрощупывания карты отказов.

    Они стояли в журнале отказов с 2026-08-27 и не перепроверялись, потому что
    код, увидев `refused`, обходит хост стороной. Без записи в таблице
    вендорская страница ложится на нижнюю ступень — тир решает URL, а не
    намерение записывающего.
    """

    def рунг(self, model: str, url: str) -> str:
        return S.classify(model, url, vendor_tier="vendor", portal_tier="portal", blog_tier="blog")

    def test_документация_вендора_это_вендор(self) -> None:
        for model, url in (
            ("mistral-small-4-119b-2603", "https://docs.mistral.ai/api/"),
            ("voxtral-small-24b-2507", "https://docs.mistral.ai/api/"),
            ("flux-1-dev", "https://docs.bfl.ml/guides/x"),
            ("kimi-k3", "https://platform.kimi.ai/docs"),
            ("ideogram-v3", "https://developer.ideogram.ai/api"),
        ):
            self.assertEqual(self.рунг(model, url), "vendor", f"{model} @ {url}")

    def test_чужая_модель_на_этом_хосте_вендором_не_становится(self) -> None:
        """Половина контроля, без которой запись читалась бы как «всё, что на
        этом хосте, — правда»: страница Mistral ничего не удостоверяет о Kling."""
        self.assertEqual(self.рунг("kling-3.0", "https://docs.mistral.ai/api/"), "blog")

    def test_общий_хост_объявлен_с_путём_а_не_целиком(self) -> None:
        """`help.aliyun.com` держит ВСЮ документацию Alibaba Cloud. Объявить
        его целиком значило бы выдать вендорский тир страницам про биллинг."""
        model = "wan-2.6-flash"
        внутри = "https://help.aliyun.com/zh/model-studio/wan-video-generation-api"
        снаружи = "https://help.aliyun.com/zh/rds/billing"
        self.assertEqual(self.рунг(model, внутри), "vendor")
        self.assertEqual(self.рунг(model, снаружи), "blog")

    def test_длинный_ключ_семьи_не_оставляет_модель_без_хоста(self) -> None:
        """`vendor_sources_for` берёт САМОЕ ДЛИННОЕ совпадение, поэтому
        `qwen-image` не видит записи ключа `qwen` вовсе. Дописать только к
        короткому ключу — починить одну модель из трёх (И7)."""
        for model in ("qwen-image", "qwen3-vl", "qwen2-audio-7b-instruct"):
            self.assertEqual(
                self.рунг(model, "https://help.aliyun.com/zh/model-studio/x"), "vendor", model
            )


class СлитнаяВерсия(unittest.TestCase):
    """Вендоры пишут версию слитно: `wan2.1`, `flux2-klein`, `qwen2.5-omni`.

    Разделительное правило такие имена не ловило, и дефект чинился ПО МЕСТУ
    трижды — ключами `wan2`, `hunyuanvideo`, `qwen3`. ИЗМЕРЕНО 2026-09-02 на
    живой базе (489 моделей): цифра-разделитель даёт вендорские источники 27
    моделям и НИ ОДНОЙ не меняет семью на чужую.
    """

    def test_слитная_версия_читает_запись_своей_семьи(self) -> None:
        for model, семья in (
            ("qwen2.5-omni-7b", "qwen"),
            ("flux2-klein-9b-consistency", "flux"),
            ("seedance2_5", "seedance"),
            ("voxcpm2", "voxcpm"),
            ("cosmos3-super-image2video", "cosmos"),
        ):
            self.assertEqual(
                S.vendor_sources_for(model), S.VENDOR_SOURCES[семья], f"{model} -> {семья}"
            )

    def test_чужое_имя_на_ту_же_букву_записи_не_читает(self) -> None:
        """Вторая половина контроля. Совпадение идёт ТОЛЬКО по цифре после
        ключа, иначе `wandering-model` унаследовал бы страницы Wan."""
        for model in ("wandering-model", "kolors", "fluxion-labs-thing", "qwenty"):
            self.assertEqual(S.vendor_sources_for(model), (), model)

    def test_буква_после_ключа_разделителем_не_стала(self) -> None:
        """Разделителем стала ЦИФРА, и только она. Одно и то же имя семьи с
        цифрой и с буквой обязано разойтись по разные стороны — иначе правило
        расширено не туда, куда написано."""
        self.assertEqual(S.vendor_sources_for("voxcpm2"), S.VENDOR_SOURCES["voxcpm"])
        self.assertEqual(S.vendor_sources_for("voxcpmx"), ())

    def test_самое_длинное_совпадение_по_прежнему_главнее(self) -> None:
        """`qwen-image` обязан читать СВОЮ запись, а не запись `qwen`: правило
        длиннейшего ключа — то, чем семья дробится, когда версия меняет
        хозяина."""
        self.assertEqual(S.vendor_sources_for("qwen-image"), S.VENDOR_SOURCES["qwen-image"])
