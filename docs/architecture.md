# Architecture Deep Dive

Deimos is designed as an autonomous agent that bridges the gap between short-term context and long-term knowledge.

## 1. The Agent Loop
Deimos operates on a `Think $\rightarrow$ Act $\rightarrow$ Observe` loop.

1. **Analysis**: The agent receives input and determines if it needs to:
   - Ask clarifying questions (Interactive Loop).
   - Create a structured plan (Workflow Planning).
   - Execute a task immediately.
2. **Planning**: If a plan is required, the agent generates a **Workflow DAG** (Directed Acyclic Graph) where tasks have dependencies.
3. **Execution**: The agent identifies "ready" steps, executes them using tools, and updates the plan state.
4. **Observation**: Tool outputs are fed back into the context to refine the next action.

## 2. Memory Layers
Deimos uses a multi-tiered memory system to avoid context window overflow while maintaining deep user knowledge.

### a. Working Memory (Short-term)
- **Scope**: Current conversation.
- **Storage**: Local LLM context.
- **Lifecycle**: Cleared on `/reset`.

### b. Episodic Memory (Medium-term)
- **Scope**: Past sessions.
- **Storage**: `episodic_memories` table.
- **Process**: At the end of every session, the agent summarizes the chat. If enough summaries accumulate, they are compressed into higher-level "archives" (Level 1, Level 2), creating a hierarchical summary of the user's history.

### c. Semantic Memory (Long-term)
- **Scope**: Durable facts.
- **Storage**: `semantic_memories` table.
- **Process**: The agent extracts key-value facts (e.g., `preferred_language: TypeScript`) and merges them using a confidence-based system.

### d. Project Memory (Contextual)
- **Scope**: Specific coding projects.
- **Storage**: `project_memories` table.
- **Process**: When a project is detected in the input, Deimos loads the relevant facts for that project into the system prompt.

## 3. Tool Registry
Deimos uses a registry-based system for extensibility. Every tool inherits from `BaseTool`, defining its own `input_schema` and `run` logic. This allows the agent to dynamically discover and call capabilities like Git, Web Search, and File System operations.

## 4. Dashboard & Monitoring
The dashboard provides a read-only window into the agent's brain. It connects to the Supabase backend to visualize memory and uses WebSockets to stream the agent's internal thought process in real-time.
