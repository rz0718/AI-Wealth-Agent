import json
from pathlib import Path

SKILLS_DIR = Path(__file__).parent.parent.parent / "skills"


def handle_load_skill(name: str) -> str:
    skill_path = SKILLS_DIR / name / "SKILL.md"
    if not skill_path.exists():
        available = [p.name for p in SKILLS_DIR.iterdir() if p.is_dir()]
        return json.dumps({
            "status": "error",
            "message": f"Unknown skill '{name}'. Available: {available}",
        })
    return json.dumps({"status": "success", "name": name, "content": skill_path.read_text()})
