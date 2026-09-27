"""MCP server: tools are registered and go through the same answer/search code."""
import asyncio
from unittest.mock import patch

import app.mcp_server as ms
from tests.test_slack import RESULT


def test_tools_registered():
    names = {t.name for t in asyncio.run(ms.mcp.list_tools())}
    assert names == {"ask_policy", "search_policies", "list_policies", "policy_changes"}


def test_ask_policy_uses_answer_pipeline_and_logs():
    class Q:
        id = 7
    with patch.object(ms, "SessionLocal"), patch.object(ms, "_mcp_user_id", return_value=1), \
         patch.object(ms, "answer_question", return_value=RESULT) as aq, \
         patch.object(ms, "log_query", return_value=Q()) as lq:
        out = ms.ask_policy("how much leave?", organisation="Acme")
    assert aq.call_args.kwargs["organisation"] == "Acme"
    assert lq.call_args.kwargs["source"] == "mcp"
    assert out["query_id"] == 7 and [s["n"] for s in out["sources"]] == [1]


def test_search_caps_top_k():
    with patch.object(ms, "SessionLocal"), patch.object(ms, "search_chunks", return_value=[]) as sc:
        ms.search_policies("leave", top_k=500)
    assert sc.call_args.args[2] == 10
