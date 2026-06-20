import os
from .base import BaseTool
from .list_skills import SKILLS_DIR


class ReadSkillTool(BaseTool):
    name = "read_skill"
    description = (
        "Read the full instructions for a named skill (from list_skills). "
        "Always read the relevant skill BEFORE creating files of that type "
        "(e.g. read the 'docx' skill before calling create_docx) — it contains "
        "formatting conventions and best practices you must follow."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "skill_name": {
                "type": "string",
                "description": "Name of the skill to read, as returned by list_skills.",
            },
        },
        "required": ["skill_name"],
    }

    def run(self, skill_name: str) -> str:
        skill_path = os.path.join(SKILLS_DIR, skill_name, "SKILL.md")
        if not os.path.isfile(skill_path):
            return f"Error: No skill found named '{skill_name}'. Use list_skills to see available skills."

        try:
            with open(skill_path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            return f"Error reading skill: {e}"