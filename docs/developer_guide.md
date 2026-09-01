# Developer Guide

This guide explains how to extend and modify Deimos.

## 1. Creating New Tools

Tools are the primary way Deimos interacts with the world. All tools must inherit from `BaseTool` in `tools/base.py`.

### Step-by-Step
1. **Define the Tool**: Create a new class in `tools/`.
2. **Implement Properties**:
   - `name`: A unique snake_case string.
   - `description`: A clear explanation of what the tool does (this is what the LLM sees).
   - `input_schema`: A JSON schema defining the arguments.
3. **Implement `run()`**: Write the execution logic. Return a string result.
4. **Register the Tool**: Add an instance of your tool to the `_register_defaults` list in `tools/registry.py`.

### Example
```python
class MyCustomTool(BaseTool):
    @property
    def name(self) -> str: return "my_tool"
    
    @property
    def description(self) -> str: return "Does something cool."
    
    @property
    def input_schema(self) -> dict:
        return {"type": "object", "properties": {"val": {"type": "string"}}, "required": ["val"]}
    
    def run(self, val: str) -> str:
        return f"Processed {val}!"
```

## 2. Modifying the Agent Loop

The core logic resides in `agent/core.py` and `agent/planner.py`.

- **Agent Core**: Manages the `handle_input` $\rightarrow$ `run` cycle.
- **Planner**: Handles the transition from a user request to a structured `Plan`.

To change how the agent thinks or plans, modify the `PLANNING_PROMPT` or the logic in `Planner.maybe_plan`.

## 3. Extending Memory

Deimos uses Supabase for long-term memory. To add new memory types:
1. **Add a Table**: Create a new table in Supabase.
2. **Create a Store**: Implement a new memory class (similar to `SemanticMemory`) in `memory/`.
3. **Integrate into Manager**: Add the store to `MemoryManager` and update `build_memory_context` to include the new data in the system prompt.

## 4. Dashboard Extensions

The dashboard is a FastAPI app. To add new views:
1. **Create an Endpoint**: Add a new `@app.get` route in `web/dashboard.py`.
2. **Update the HTML**: Add a new tab and a corresponding `load...()` function in the `DASHBOARD_HTML` constant.
