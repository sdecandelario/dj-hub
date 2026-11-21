"""DJ Hub backend. Importing the package loads <project>/.env (secrets, see .env.dist) into the environment."""
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


def _load_env_file(path):
    """KEY=VALUE lines; blank lines and # comments are skipped. Variables already in the environment win."""
    import os

    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip("\"'")
        if value:
            os.environ.setdefault(key.strip(), value)


_load_env_file(ENV_FILE)
