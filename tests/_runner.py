"""Run a test module's test_* functions under plain python, with no pytest installed.

Every test file here is a normal pytest module, so CI can just run pytest. But the
machine this integration is developed on has neither pytest nor homeassistant installed,
and a QA harness you cannot run without setting up an environment first is a harness that
does not get run. So each module also ends with:

    if __name__ == "__main__":
        run_module(globals())

which gives the same assertions from `python3 tests/test_x.py`.
"""

from __future__ import annotations

import traceback


def run_module(namespace: dict) -> int:
    """Run every test_* callable in `namespace`. Returns a process exit code."""
    tests = sorted(
        (name, obj)
        for name, obj in namespace.items()
        if name.startswith("test_") and callable(obj)
    )
    failed: list[tuple[str, BaseException]] = []
    for name, fn in tests:
        try:
            fn()
        # Broad on purpose: a runner reports every failure, it does not filter them.
        except BaseException as exc:
            failed.append((name, exc))
            print(f"  FAIL {name}")
            traceback.print_exc()
        else:
            print(f"  ok   {name}")
    print(f"{len(tests) - len(failed)}/{len(tests)} passed")
    for name, exc in failed:
        print(f"  failed: {name}: {type(exc).__name__}: {exc}")
    return 1 if failed else 0
