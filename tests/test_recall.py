from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from memory.recall import MemoryRecall, format_recall

NOW = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)


def _client(rows=None, probe_error=None):
    client = MagicMock()
    calls = []

    def rpc(name, params):
        calls.append(params)
        call = MagicMock()
        if probe_error and len(calls) == 1:
            call.execute.side_effect = probe_error
        else:
            call.execute.return_value = MagicMock(data=rows or [])
        return call

    client.rpc.side_effect = rpc
    client.calls = calls
    return client


def test_unavailable_when_the_migration_has_not_run():
    recall = MemoryRecall(_client(probe_error=Exception("Could not find the function public.search_memories")), "u1")
    assert not recall.available
    assert recall.search("anything") == []


def test_search_passes_user_and_excluded_conversation_and_drops_weak_matches():
    rows = [
        {"kind": "fact", "body": "preferred_language: Python", "score": 1.0},
        {"kind": "message", "body": "use pytest for everything", "score": 0.5},
        {"kind": "session", "body": "barely related", "score": 0.05},
    ]
    client = _client(rows)
    recall = MemoryRecall(client, "u1")

    found = recall.search("which test runner do I like?", exclude_conversation="c9")

    assert [r["body"] for r in found] == ["preferred_language: Python", "use pytest for everything"]
    params = client.calls[-1]
    assert params["p_user_id"] == "u1" and params["p_exclude_conversation"] == "c9"


def test_blank_queries_skip_the_database():
    client = _client([])
    recall = MemoryRecall(client, "u1")
    probes = len(client.calls)
    assert recall.search("   ") == [] and len(client.calls) == probes


def test_format_labels_kinds_and_ages_and_skips_core_facts():
    rows = [
        {"kind": "fact", "body": "name: Kunal"},
        {"kind": "project", "project_name": "Deimos", "body": "test_command: pytest -q"},
        {"kind": "session", "body": "Added  checkpoints\nand /undo", "created_at": (NOW - timedelta(days=3)).isoformat()},
        {"kind": "message", "body": "I prefer ruff", "created_at": (NOW - timedelta(hours=2)).isoformat()},
    ]
    block = format_recall(rows, skip_bodies={"name: Kunal"}, now=NOW)
    lines = block.splitlines()
    assert lines[0] == "## Relevant memory"
    assert lines[2:] == [
        "- (project Deimos) test_command: pytest -q",
        "- (earlier session, 3 days ago) Added checkpoints and /undo",
        "- (you said, today) I prefer ruff",
    ]


def test_format_returns_none_when_everything_is_skipped():
    assert format_recall([{"kind": "fact", "body": "a: b"}], skip_bodies={"a: b"}) is None
    assert format_recall([]) is None


def _manager(search_available, facts):
    from memory.manager import MemoryManager
    with patch("memory.manager.validate_schema", return_value=[]), \
         patch("memory.manager.get_client"), \
         patch("memory.manager.ConversationStore"), \
         patch("memory.manager.EpisodicMemory") as episodic, \
         patch("memory.manager.SemanticMemory") as semantic, \
         patch("memory.manager.ProjectMemory") as project, \
         patch("memory.manager.MemoryRecall") as recall:
        recall.return_value.available = search_available
        semantic.return_value.get_all_facts.return_value = facts
        project.return_value.get_known_projects.return_value = []
        episodic.return_value.get_recent_summaries.return_value = []
        episodic.return_value.get_latest_archive.return_value = None
        manager = MemoryManager(user_id="u1")
        return manager, manager.build_memory_context()


FACTS = [{"key": f"k{i}", "value": f"v{i}", "confidence": 1 - i / 100} for i in range(20)]


def test_only_core_facts_load_up_front_when_recall_is_available():
    manager, block = _manager(True, FACTS)
    assert "k7: v7" in block and "k8: v8" not in block
    assert manager._core_fact_lines == {f"k{i}: v{i}" for i in range(8)}


def test_all_facts_load_up_front_without_recall():
    _, block = _manager(False, FACTS)
    assert "k19: v19" in block


def test_importance_is_patched_by_message_id():
    from memory.manager import MemoryManager
    manager = MemoryManager.__new__(MemoryManager)
    manager.conversations = MagicMock()
    manager.conversations.save_message.return_value = "msg-42"
    with patch("memory.manager.score_message_async") as score:
        manager.save_message("user", "I'm building Deimos")
        apply = score.call_args.args[1]
        apply(8, None)
    manager.conversations.update_message_importance.assert_called_once_with("msg-42", 8, None)
