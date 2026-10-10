"""Export the API contract without connecting to the user's database or gateway."""
import json
import sys
import tempfile
from pathlib import Path

from agentlab.api.app import create_app
from agentlab.bootstrap import build_services
from agentlab.settings import Settings

with tempfile.TemporaryDirectory(prefix="agentlab-openapi-") as temporary:
    root = Path(temporary)
    svc = build_services(Settings(store_backend="memory", data_dir=root, env_file=root / ".env",
                                  config_dir=Path(__file__).resolve().parents[1] / "config"))
    Path(sys.argv[1]).write_text(json.dumps(create_app(svc).openapi(), ensure_ascii=False, indent=2) + "\n")
