from pathlib import Path
import sys

# Quando este arquivo é executado como /app/scripts/check_models.py,
# o Python coloca /app/scripts no sys.path, e não a raiz /app.
# Inserimos explicitamente a raiz do projeto para os imports locais.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from models import Permission, UserAccessProfile, UserPermission, User, Role

required = [Permission, UserAccessProfile, UserPermission, User, Role]
print("[Flash Stock] Models OK:", ", ".join(model.__name__ for model in required))
