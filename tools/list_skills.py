import os
from .base import BaseTool

SKILLS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "skills")


class ListSkillsTool(BaseTool):
    name = "list_skills"
    description = (
        "List all available skills. Skills contain best-practice instructions "
        "for producing specific output types (Word documents, etc.). ALWAYS "
        "check this before attempting a task that involves creating a document "
        "or structured file — call this first, then read_skill on anything "
        "relevant, before calling the matching creation tool."
    )
    input_schema = {"type": "object", "properties": {}, "required": []}

    def run(self) -> str:
        if not os.path.isdir(SKILLS_DIR):
            return "No skills directory found."

        skills = []
        for name in sorted(os.listdir(SKILLS_DIR)):
            skill_path = os.path.join(SKILLS_DIR, name, "SKILL.md")
            if os.path.isfile(skill_path):
                summary = _first_line_summary(skill_path)
                skills.append(f"- {name}: {summary}")

        if not skills:
            return "No skills found."

        return "Available skills:\n" + "\n".join(skills)


def _first_line_summary(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    return line[:150]
    except Exception:
        pass
    return "(no summary)"