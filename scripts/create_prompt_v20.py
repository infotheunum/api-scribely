from rewrite_app.db import new_session
from rewrite_app.prompt.versions import create_v20_from_active

db = new_session()
try:
    version = create_v20_from_active(db)
    print(f"candidate: {version.id} ({version.notes})")
finally:
    db.close()
