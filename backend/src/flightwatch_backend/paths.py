from pathlib import Path


PACKAGE_DIR = Path(__file__).resolve().parent
BACKEND_ROOT = PACKAGE_DIR.parent.parent
REPO_ROOT = BACKEND_ROOT.parent
FRONTEND_DIR = REPO_ROOT / "frontend"
FLIGHT_FETCH_DIR = REPO_ROOT / "scripts" / "flight_fetch"
ENV_FILE = BACKEND_ROOT / ".env"

