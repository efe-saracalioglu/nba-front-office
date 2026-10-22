from agents import tracing


def test_tracing_is_a_no_op_without_keys(monkeypatch):
    monkeypatch.setenv("FRONT_OFFICE_TRACING", "0")
    tracing.client.cache_clear()
    try:
        assert not tracing.enabled()
        with (
            tracing.run_trace("t", "s", ["a"], {"m": 1}, "req") as root,
            tracing.observation("x", as_type="tool") as obs,
        ):
            obs.update(output=1)
            root.update(output=2)
        wrapped = tracing.traced_node("n", lambda state: {"answer": state["q"], "usage": []})
        assert wrapped({"q": 42}) == {"answer": 42, "usage": []}
        assert tracing.current_trace_id() is None
    finally:
        tracing.client.cache_clear()
