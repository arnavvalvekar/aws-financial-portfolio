"""The live demo must keep working: every attack has to be blocked."""

from demo_leak_attack import run_attacks


def test_every_leak_attack_is_blocked():
    results = run_attacks()
    assert len(results) == 4
    assert all(ok for _, ok, _ in results), [(t, m) for t, ok, m in results if not ok]
