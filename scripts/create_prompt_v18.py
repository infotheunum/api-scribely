"""Create a v18 candidate without replacing the currently active prompt."""

from __future__ import annotations

from rewrite_app.db import new_session
from rewrite_app.prompt.versions import create_v18_from_active


def main() -> None:
    db = new_session()
    try:
        version = create_v18_from_active(db)
        print(f"candidate: {version.id} ({version.notes})")
    finally:
        db.close()


if __name__ == "__main__":
    main()
