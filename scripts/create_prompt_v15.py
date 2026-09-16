"""Create the v15 prompt candidate from the currently active prompt.

Run in the rewrite production service, review the candidate in Admin, then
activate it explicitly.  The command never retires or replaces the active row.
"""

from __future__ import annotations

from rewrite_app.db import new_session
from rewrite_app.prompt.versions import create_v15_from_active


def main() -> None:
    db = new_session()
    try:
        version = create_v15_from_active(db)
        print(f"candidate: {version.id} ({version.notes})")
    finally:
        db.close()


if __name__ == "__main__":
    main()
