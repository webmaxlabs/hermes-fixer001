import pytest

from inbox_watcher.github_pr import open_draft_pr, get_pr_state, _parse, find_open_pr_for_head


class Resp:
    def __init__(self, code, payload, text=""):
        self.status_code = code; self._p = payload; self.text = text
    def json(self): return self._p


def test_find_open_pr_for_head_returns_url_when_present():
    def http(method, url, **kw):
        assert kw["params"] == {"head": "webmaxlabs:hermes-fixer/x", "state": "open"}
        return Resp(200, [{"html_url": "https://github.com/webmaxlabs/r/pull/3"}])
    assert find_open_pr_for_head(owner="webmaxlabs", repo="r", head="hermes-fixer/x",
                                 token="tok", http=http) == "https://github.com/webmaxlabs/r/pull/3"


def test_find_open_pr_for_head_returns_none_when_empty():
    assert find_open_pr_for_head(owner="webmaxlabs", repo="r", head="hermes-fixer/x",
                                 token="tok", http=lambda *a, **k: Resp(200, [])) is None


def test_find_open_pr_for_head_raises_on_error():
    with pytest.raises(RuntimeError):
        find_open_pr_for_head(owner="webmaxlabs", repo="r", head="hermes-fixer/x",
                              token="tok", http=lambda *a, **k: Resp(500, {}, "boom"))


def test_open_draft_pr_posts_and_labels():
    calls = []
    def http(method, url, **kw):
        calls.append((method, url, kw))
        if url.endswith("/pulls"):
            return Resp(201, {"number": 7, "html_url": "https://github.com/o/r/pull/7"})
        return Resp(200, {})
    url = open_draft_pr(owner="o", repo="r", head="hermes-fixer/x", base="main",
                        title="t", body="b", labels=["hermes-fixer", "P1"],
                        token="tok", http=http)
    assert url == "https://github.com/o/r/pull/7"
    pulls = [c for c in calls if c[1].endswith("/pulls")][0]
    assert pulls[2]["json"]["draft"] is True
    assert pulls[2]["headers"]["Authorization"] == "Bearer tok"
    assert any("/issues/7/labels" in c[1] for c in calls)


def test_get_pr_state():
    def http(method, url, **kw):
        return Resp(200, {"state": "closed", "merged": True})
    assert get_pr_state("https://github.com/o/r/pull/7", token="tok", http=http) == "merged"


def test_get_pr_state_open():
    def http(method, url, **kw):
        return Resp(200, {"state": "open", "merged": False})
    assert get_pr_state("https://github.com/o/r/pull/7", token="tok", http=http) == "open"


def test_open_draft_pr_raises_on_error():
    def http(method, url, **kw):
        return Resp(500, {}, text="<html>boom</html>")
    with pytest.raises(RuntimeError):
        open_draft_pr(owner="o", repo="r", head="h", base="main",
                      title="t", body="b", labels=[], token="tok", http=http)


def test_get_pr_state_raises_on_error():
    def http(method, url, **kw):
        return Resp(401, {}, text="Bad credentials")
    with pytest.raises(RuntimeError):
        get_pr_state("https://github.com/o/r/pull/7", token="tok", http=http)


def test_open_draft_pr_no_labels_skips_label_call():
    calls = []
    def http(method, url, **kw):
        calls.append((method, url, kw))
        return Resp(201, {"number": 9, "html_url": "https://github.com/o/r/pull/9"})
    url = open_draft_pr(owner="o", repo="r", head="h", base="main",
                        title="t", body="b", labels=[], token="tok", http=http)
    assert url == "https://github.com/o/r/pull/9"
    assert not any("/labels" in c[1] for c in calls)


def test_parse_malformed_url_raises():
    with pytest.raises(ValueError):
        _parse("https://example.com/not/a/pr")
