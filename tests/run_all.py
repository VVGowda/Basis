"""Run every test suite and report one result.

    venv\\Scripts\\python.exe tests\\run_all.py

Three suites, deliberately separate:

  test_engine       loan maths and the rule engine. Pure, offline, fast.
  test_matching     institution name reconciliation. Pure, offline, fast.
  test_degradation  what a user sees when upstreams die. Points real providers
                    at dead sockets, so it takes a few seconds.

None of them depend on a live public API succeeding. A suite that goes red
because somebody else's free endpoint is having a bad morning is a suite people
learn to ignore. Use scripts/check_apis.py for live upstream health.
"""

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SUITES = ["test_engine.py", "test_matching.py", "test_degradation.py"]


def main() -> int:
    total_failed = 0
    results = []

    for suite in SUITES:
        print(f"\n{'=' * 70}\n  {suite}\n{'=' * 70}")
        proc = subprocess.run(
            [sys.executable, str(HERE / suite)],
            capture_output=True,
            text=True,
        )
        # Each suite prints its own summary line last.
        tail = [line for line in proc.stdout.strip().splitlines() if line.strip()]
        for line in tail:
            if line.startswith(("FAIL", "ERROR")) or "passed" in line:
                print("  " + line)

        if proc.returncode != 0:
            total_failed += 1
            if proc.stderr.strip():
                print("  stderr:", proc.stderr.strip()[:400])

        results.append((suite, proc.returncode == 0, tail[-1] if tail else "no output"))

    print(f"\n{'=' * 70}")
    for suite, ok, summary in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {suite:<24} {summary}")
    print("=" * 70)

    if total_failed:
        print(f"\n{total_failed} suite(s) failed\n")
        return 1

    print("\nAll suites passed\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
