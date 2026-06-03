from inbox_watcher.ledger import DispatchLedger


def test_record_then_open_signatures(tmp_path):
    led = DispatchLedger(tmp_path / "dispatched.jsonl")
    assert led.open_signatures() == set()
    led.record(error_signature="sig1", repo="nexus-uncensored",
               rule_id="r1", priority="P1", mode="dry_run", now="t0")
    assert led.open_signatures() == {"sig1"}


def test_record_existing_bumps_seen_count_and_preserves_first_ts(tmp_path):
    path = tmp_path / "dispatched.jsonl"
    led = DispatchLedger(path)
    led.record(error_signature="sig1", repo="r", rule_id="x", priority="P1",
               mode="dry_run", now="t0")
    led.record(error_signature="sig1", repo="r", rule_id="x", priority="P1",
               mode="dry_run", now="t1")
    folded = led.fold()
    assert folded["sig1"]["seen_count"] == 2
    assert folded["sig1"]["first_dispatched_ts"] == "t0"
    assert folded["sig1"]["last_seen_ts"] == "t1"
    assert folded["sig1"]["open"] is True


def test_fold_tolerates_malformed_lines(tmp_path):
    path = tmp_path / "dispatched.jsonl"
    path.write_text('{"error_signature":"s","open":true,"seen_count":1,'
                    '"first_dispatched_ts":"t","last_seen_ts":"t"}\n'
                    'not json\n')
    led = DispatchLedger(path)
    assert led.open_signatures() == {"s"}


def test_open_signatures_excludes_closed(tmp_path):
    # A later row marking open=false should drop it from open_signatures (fold-latest-wins).
    path = tmp_path / "dispatched.jsonl"
    led = DispatchLedger(path)
    led.record(error_signature="sig1", repo="r", rule_id="x", priority="P1",
               mode="dry_run", now="t0")
    led._append({"error_signature": "sig1", "repo": "r", "rule_id": "x",
                 "priority": "P1", "first_dispatched_ts": "t0", "last_seen_ts": "t2",
                 "seen_count": 1, "mode": "dry_run", "open": False})
    assert led.open_signatures() == set()
