from __future__ import annotations

from src.cli import build_parser, workflow_config_from_args


def test_cli_defaults_to_final_submit_for_backward_compatibility() -> None:
    args = build_parser().parse_args([])

    config = workflow_config_from_args(args)

    assert config.dry_run is False
    assert config.final_submit is True


def test_cli_no_final_submit_enables_fill_only_mode() -> None:
    args = build_parser().parse_args(["--no-final-submit"])

    config = workflow_config_from_args(args)

    assert config.dry_run is False
    assert config.final_submit is False
