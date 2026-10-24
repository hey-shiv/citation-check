import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import citation_check as cc  # noqa: E402

BIB = r"""
@article{vaswani2017,
  title = {Attention Is {All} You Need},
  author = {Vaswani, Ashish and Shazeer, Noam},
  year = {2017},
  eprint = {1706.03762},
}
@inproceedings{fake2023,
  title = "Neural Harmonic Reasoning for Symbolic Music Understanding at Scale",
  author = "Doe, Jane",
  year = 2023
}
@article{wrongyear,
  title = {Deep Residual Learning for Image Recognition},
  author = {He, Kaiming},
  year = {2009},
  doi = {10.1109/CVPR.2016.90}
}
"""

ARXIV_XML = """<feed xmlns="http://www.w3.org/2005/Atom"><entry>
<title>Attention Is All
 You Need</title><published>2017-06-12T17:57:34Z</published>
<author><name>Ashish Vaswani</name></author></entry></feed>"""

CROSSREF_RESNET = json.dumps({"message": {
    "title": ["Deep Residual Learning for Image Recognition"],
    "issued": {"date-parts": [[2016, 6]]},
    "author": [{"family": "He"}], "DOI": "10.1109/CVPR.2016.90"}})

CROSSREF_SEARCH_MISS = json.dumps({"message": {"items": [{
    "title": ["Symbolic Music Generation with Diffusion Models"],
    "issued": {"date-parts": [[2021]]}, "author": [{"family": "Mittal"}]}]}})

OPENALEX_SEARCH = json.dumps({"results": [{
    "title": "Music Transformer: Generating Music with Long-Term Structure",
    "publication_year": 2019, "doi": None,
    "authorships": [{"author": {"display_name": "Cheng-Zhi Anna Huang"}}]}]})


def fake_fetch(url):
    if "export.arxiv.org" in url:
        return ARXIV_XML
    if "/works/10.1109" in url:
        return CROSSREF_RESNET
    if "api.crossref.org/works?" in url:
        return CROSSREF_SEARCH_MISS
    if "api.openalex.org" in url:
        return OPENALEX_SEARCH
    raise AssertionError("unexpected url " + url)


def test_parse_bib_reads_braced_quoted_and_bare_values():
    entries = cc.parse_bib(BIB)
    assert [e["key"] for e in entries] == ["vaswani2017", "fake2023", "wrongyear"]
    assert entries[0]["title"] == "Attention Is All You Need"
    assert entries[1]["year"] == "2023"
    assert cc.first_author_surname(entries[0]["author"]) == "vaswani"


def test_real_fake_and_wrong_year_references_are_told_apart():
    results = {r["key"]: r for r in (cc.check_entry(e, fake_fetch) for e in cc.parse_bib(BIB))}
    assert results["vaswani2017"]["status"] == cc.VERIFIED
    assert results["fake2023"]["status"] == cc.NOT_FOUND
    assert results["wrongyear"]["status"] == cc.MISMATCH
    assert "year 2009 vs 2016" in results["wrongyear"]["problems"]


def test_exit_code_flags_bad_references(tmp_path, capsys):
    bib = tmp_path / "refs.bib"
    bib.write_text(BIB)
    assert cc.main([str(bib), "--delay", "0"], fetch=fake_fetch) == 1
    out = capsys.readouterr().out
    assert "1 verified, 1 mismatch, 1 not_found, 0 error" in out


def test_conference_paper_missing_from_crossref_is_found_via_openalex():
    entry = {"key": "huang2019", "title": "Music Transformer: Generating Music with Long-Term Structure",
             "author": "Huang, Cheng-Zhi Anna", "year": "2019"}
    assert cc.check_entry(entry, fake_fetch)["status"] == cc.VERIFIED


def test_unreachable_index_never_reports_a_paper_as_missing():
    def openalex_down(url):
        if "api.openalex.org" in url:
            raise cc.urllib.error.URLError("rate limited")
        return fake_fetch(url)
    entry = {"key": "fake", "title": "Neural Harmonic Reasoning for Symbolic Music Understanding at Scale"}
    result = cc.check_entry(entry, openalex_down)
    assert result["status"] == cc.ERROR
    assert "openalex" in result["problems"][0]


def test_arxiv_outage_falls_back_to_title_search():
    def arxiv_down(url):
        if "export.arxiv.org" in url:
            raise cc.urllib.error.HTTPError(url, 429, "Too Many Requests", {}, None)
        return fake_fetch(url)
    entry = {"key": "huang", "title": "Music Transformer: Generating Music with Long-Term Structure",
             "author": "Huang, Cheng-Zhi Anna", "year": "2019", "eprint": "1809.04281"}
    assert cc.check_entry(entry, arxiv_down)["status"] == cc.VERIFIED
