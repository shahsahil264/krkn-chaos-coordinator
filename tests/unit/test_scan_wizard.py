"""Tests for the harness-neutral interactive scan wizard."""

from argparse import Namespace

from src.main import _apply_interactive_options


def test_interactive_options_support_custom_agent_and_keyword_scan(monkeypatch) -> None:
    answers = iter([
        "4.20,4.21",  # release
        "2",           # enter agent IDs
        "control_plane, networking",
        "10",          # lookback
        "3",           # keyword only
        "3",           # chaos only
    ])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    args = Namespace(
        release="4.21",
        agent=None,
        days=14,
        max_bugs=2000,
        use_llm=False,
        domain_filter_only=False,
        filter_review_json=None,
        no_filter_review=False,
    )

    _apply_interactive_options(
        args,
        {
            "control_plane": Namespace(description="Control plane"),
            "networking": Namespace(description="Networking"),
        },
    )

    assert args.release == "4.20,4.21"
    assert args.agent == "control_plane,networking"
    assert args.days == 10
    assert args.max_bugs == 2000
    assert args.use_llm is False
    assert args.domain_filter_only is False


def test_interactive_domain_only_disables_llm_and_exports_review(monkeypatch) -> None:
    answers = iter(["", "1", "", "1", "2"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    args = Namespace(
        release="4.21",
        agent=None,
        days=14,
        max_bugs=2000,
        use_llm=False,
        domain_filter_only=False,
        filter_review_json=None,
        no_filter_review=False,
    )

    _apply_interactive_options(args, {"control_plane": Namespace(description="Control plane")})

    assert args.agent is None
    assert args.domain_filter_only is True
    assert args.use_llm is False
    assert args.filter_review_json == "filter_review.json"
    assert args.no_filter_review is True
