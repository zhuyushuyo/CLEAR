"""Start CLEAR:  python launch.py"""

import sys
from pathlib import Path

if sys.version_info < (3, 10):
    sys.exit("CLEAR needs Python 3.10 or newer.")

# Keep the app folder clean: no __pycache__ folders for Google Drive to sync.
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

from clear.app import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
