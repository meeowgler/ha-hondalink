import sys
from pathlib import Path

# util.py lives at the repo root (HACS content_in_root) and has no Home Assistant imports,
# so the tests import it directly instead of going through the package __init__.py.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
