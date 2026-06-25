from __future__ import annotations

from remora.toolcall.benchmark_v2 import ARTIFACT_PATH_V2, write_benchmark_v2


def main() -> None:
    data = write_benchmark_v2()
    print(f"Wrote {data['metadata']['total_tasks']} tasks to {ARTIFACT_PATH_V2}")


if __name__ == "__main__":
    main()
