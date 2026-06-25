from __future__ import annotations

from remora.toolcall.benchmark import ARTIFACT_PATH, write_benchmark


def main() -> None:
    data = write_benchmark()
    print(f"Wrote {data['metadata']['total_tasks']} tasks to {ARTIFACT_PATH}")


if __name__ == "__main__":
    main()
