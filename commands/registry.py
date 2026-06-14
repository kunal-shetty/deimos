"""
Registry of all slash commands.
"""

from commands.base import Command


class CommandRegistry:
    """Holds all registered commands and dispatches by name."""

    def __init__(self):
        self._commands: dict[str, Command] = {}

    def register(self, command: Command):
        self._commands[command.name] = command

    def get(self, name: str) -> Command | None:
        return self._commands.get(name)

    def all(self) -> list[Command]:
        return sorted(self._commands.values(), key=lambda c: c.name)

    def names(self) -> list[str]:
        return sorted(self._commands.keys())

    def dispatch(self, raw_input: str, state) -> bool:
        """
        If raw_input starts with '/', parse and run the matching command.
        Returns True if a command was dispatched (handled), False otherwise
        (caller should treat raw_input as a normal agent prompt).
        """
        if not raw_input.startswith("/"):
            return False

        parts = raw_input[1:].split(maxsplit=1)
        if not parts:
            return False

        name = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        command = self.get(name)
        if not command:
            state.ui.error(
                f"Unknown command: /{name}. Type / and press Tab to see available commands."
            )
            return True

        command.run(args, state)
        return True