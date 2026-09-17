"""Create the v16 prompt candidate from the currently active editorial prompt."""

from db.session import SessionLocal
from rewrite_app.prompt.versions import create_v16_from_active


def main() -> None:
    with SessionLocal() as db:
        version = create_v16_from_active(db)
        print(f"Created/reused draft PromptVersion {version.id}: {version.notes}")


if __name__ == "__main__":
    main()
