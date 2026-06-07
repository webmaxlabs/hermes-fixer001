from inbox_watcher.github_pr import open_draft_pr, get_pr_state


class Resp:
    def __init__(self, code, payload): self.status_code = code; self._p = payload
    def json(self): return self._p


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
