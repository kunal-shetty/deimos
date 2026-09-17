import pytest
from unittest.mock import MagicMock, patch
from memory.manager import MemoryManager

def test_memory_manager_init_schema_fail():
    # Mock validate_schema to return an error
    with patch("memory.manager.validate_schema") as mock_val:
        mock_val.return_value = ["Table 'users' is missing"]

        with pytest.raises(RuntimeError) as excinfo:
            MemoryManager(user_id="test-user")

        assert "Deimos database schema is invalid" in str(excinfo.value)

def test_memory_manager_init_schema_success():
    # Mock validate_schema to return success
    with patch("memory.manager.validate_schema") as mock_val:
        mock_val.return_value = []

        # Mock all the stores to avoid real Supabase calls
        with patch("memory.manager.ConversationStore"), \
             patch("memory.manager.EpisodicMemory"), \
             patch("memory.manager.SemanticMemory"), \
             patch("memory.manager.ProjectMemory"), \
             patch("memory.manager.get_client") as mock_client:

            mock_client.return_value = MagicMock()
            manager = MemoryManager(user_id="test-user")
            assert manager.user_id == "test-user"

