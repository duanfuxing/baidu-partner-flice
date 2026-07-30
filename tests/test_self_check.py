from src.self_check import run_self_check


def test_offline_self_check_dependencies() -> None:
    assert run_self_check(check_spawn=False)


def test_offline_self_check_spawn_process() -> None:
    assert run_self_check()
