"""
Base classes for the Deimos slash-command system.

AppState holds everything a command might need to act on. Since `/resume`
swaps out the active Agent entirely, AppState wraps it in a mutable
container so commands always see the current instance.
"""

from abc import ABC, abstractmethod


class AppState:
    """Mutable container for shared application objects."""

    def __init__(self, ui, llm, tools, system_prompt, agent):
        self.ui = ui
        self.llm = llm
        self.tools = tools
        self.system_prompt = system_prompt
        self.agent = agent
        self.running = True
        self.shutdown_done = False

    def shutdown_current_agent(self):
        """Save & end the current agent's session. Idempotent."""
        if self.shutdown_done:
            return
        title = self.agent.shutdown()
        self.ui.memory_saved(title)
        self.shutdown_done = True


class Command(ABC):
    """Base class for all slash commands."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Command name without the leading slash, e.g. 'help'."""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """Short description shown in the command menu."""
        ...

    @property
    def usage(self) -> str:
        """Usage string shown in /help. Defaults to '/<name>'."""
        return f"/{self.name}"

    @abstractmethod
    def run(self, args: str, state: AppState):
        """Execute the command. `args` is everything after the command name."""
        ...