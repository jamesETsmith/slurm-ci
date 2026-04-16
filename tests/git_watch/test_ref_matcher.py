"""Unit tests for :mod:`slurm_ci.ref_matcher`.

The matcher is intentionally pure logic; these tests exercise the public
surface (``normalize_ref``, ``ref_kind``, ``short_name``, and
``RefPatternSet``) without touching subprocess/network code, so they should
stay fast and deterministic.
"""

import pytest

from slurm_ci.ref_matcher import (
    RefPatternSet,
    normalize_ref,
    ref_kind,
    short_name,
)


class TestNormalizeRef:
    def test_short_branch_expands_to_heads(self) -> None:
        assert normalize_ref("main") == "refs/heads/main"

    def test_nested_short_branch_expands_to_heads(self) -> None:
        assert normalize_ref("release/1.0") == "refs/heads/release/1.0"

    def test_wildcard_short_branch_expands(self) -> None:
        assert normalize_ref("release/*") == "refs/heads/release/*"

    def test_fully_qualified_head_passes_through(self) -> None:
        assert normalize_ref("refs/heads/main") == "refs/heads/main"

    def test_tag_pattern_passes_through(self) -> None:
        assert normalize_ref("refs/tags/v*") == "refs/tags/v*"

    def test_empty_string_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            normalize_ref("")


class TestRefKind:
    def test_heads(self) -> None:
        assert ref_kind("refs/heads/main") == "heads"

    def test_tags(self) -> None:
        assert ref_kind("refs/tags/v1.0") == "tags"

    def test_other(self) -> None:
        assert ref_kind("refs/pull/1/head") == "other"


class TestShortName:
    def test_strips_heads(self) -> None:
        assert short_name("refs/heads/release/1.0") == "release/1.0"

    def test_strips_tags(self) -> None:
        assert short_name("refs/tags/v1.0") == "v1.0"

    def test_leaves_other_untouched(self) -> None:
        assert short_name("refs/pull/1/head") == "refs/pull/1/head"


class TestRefPatternSetConstruction:
    def test_requires_at_least_one_include(self) -> None:
        with pytest.raises(ValueError):
            RefPatternSet(include=())

    def test_rejects_unknown_match_style(self) -> None:
        with pytest.raises(ValueError):
            RefPatternSet(include=("refs/heads/main",), match_style="regex")  # type: ignore[arg-type]

    def test_from_branch_normalizes_short_name(self) -> None:
        patterns = RefPatternSet.from_branch("main")
        assert patterns.include == ("refs/heads/main",)
        assert patterns.exclude == ()
        assert patterns.match_style == "fnmatch"

    def test_from_branch_preserves_fully_qualified_ref(self) -> None:
        patterns = RefPatternSet.from_branch("refs/tags/v*")
        assert patterns.include == ("refs/tags/v*",)

    def test_from_branches_normalizes_each_entry(self) -> None:
        patterns = RefPatternSet.from_branches(["main", "release/*"])
        assert patterns.include == (
            "refs/heads/main",
            "refs/heads/release/*",
        )

    def test_from_branches_rejects_empty_iterable(self) -> None:
        with pytest.raises(ValueError):
            RefPatternSet.from_branches([])

    def test_from_refs_normalizes_and_dedupes(self) -> None:
        patterns = RefPatternSet.from_refs(
            include=["main", "refs/heads/main", "release/*"],
            exclude=["release/*-rc*", "refs/heads/release/*-rc*"],
        )
        assert patterns.include == (
            "refs/heads/main",
            "refs/heads/release/*",
        )
        assert patterns.exclude == ("refs/heads/release/*-rc*",)

    def test_from_refs_requires_include(self) -> None:
        with pytest.raises(ValueError):
            RefPatternSet.from_refs(include=[])


class TestLsRemoteArgs:
    def test_returns_include_patterns(self) -> None:
        patterns = RefPatternSet.from_branches(["main", "release/*"])
        assert patterns.ls_remote_args() == [
            "refs/heads/main",
            "refs/heads/release/*",
        ]

    def test_excludes_are_not_sent_to_remote(self) -> None:
        patterns = RefPatternSet.from_refs(
            include=["release/*"],
            exclude=["release/*-rc*"],
        )
        assert patterns.ls_remote_args() == ["refs/heads/release/*"]

    def test_dedupes_preserving_order(self) -> None:
        patterns = RefPatternSet(
            include=(
                "refs/heads/main",
                "refs/heads/release/*",
                "refs/heads/main",
            ),
        )
        assert patterns.ls_remote_args() == [
            "refs/heads/main",
            "refs/heads/release/*",
        ]


class TestMatchesFnmatchStyle:
    """Backward-compatible default: ``*`` crosses ``/`` (legacy behavior)."""

    def test_exact_branch_match(self) -> None:
        patterns = RefPatternSet.from_branch("main")
        assert patterns.matches("refs/heads/main")

    def test_exact_branch_rejects_other(self) -> None:
        patterns = RefPatternSet.from_branch("main")
        assert not patterns.matches("refs/heads/develop")

    def test_wildcard_matches_simple(self) -> None:
        patterns = RefPatternSet.from_branch("release/*")
        assert patterns.matches("refs/heads/release/1.0")

    def test_wildcard_rejects_unrelated_branch(self) -> None:
        patterns = RefPatternSet.from_branch("release/*")
        assert not patterns.matches("refs/heads/main")

    def test_wildcard_rejects_tag(self) -> None:
        patterns = RefPatternSet.from_branch("release/*")
        assert not patterns.matches("refs/tags/release/1.0")

    def test_wildcard_crosses_slash_by_default(self) -> None:
        patterns = RefPatternSet.from_branch("release/*")
        assert patterns.matches("refs/heads/release/1.0/hotfix")

    def test_multiple_includes(self) -> None:
        patterns = RefPatternSet.from_branches(["main", "release/*"])
        assert patterns.matches("refs/heads/main")
        assert patterns.matches("refs/heads/release/1.0")
        assert not patterns.matches("refs/heads/feature/x")

    def test_exclude_takes_precedence(self) -> None:
        patterns = RefPatternSet.from_refs(
            include=["release/*"],
            exclude=["release/*-rc*"],
        )
        assert patterns.matches("refs/heads/release/1.0")
        assert not patterns.matches("refs/heads/release/1.0-rc1")

    def test_tag_pattern_matches_tag(self) -> None:
        patterns = RefPatternSet.from_refs(include=["refs/tags/v*"])
        assert patterns.matches("refs/tags/v1.0")
        assert not patterns.matches("refs/heads/v1.0")


class TestMatchesGitStyle:
    """Git-style matching: ``*`` stops at ``/``; ``**`` spans segments."""

    def test_wildcard_does_not_cross_slash(self) -> None:
        patterns = RefPatternSet.from_branch("release/*", match_style="git")
        assert patterns.matches("refs/heads/release/1.0")
        assert not patterns.matches("refs/heads/release/1.0/hotfix")

    def test_double_star_spans_segments(self) -> None:
        patterns = RefPatternSet.from_refs(
            include=["refs/heads/feature/**"], match_style="git"
        )
        assert patterns.matches("refs/heads/feature/x")
        assert patterns.matches("refs/heads/feature/x/y")
        assert patterns.matches("refs/heads/feature/x/y/z")
        assert not patterns.matches("refs/heads/release/x")

    def test_double_star_matches_zero_segments(self) -> None:
        patterns = RefPatternSet.from_refs(
            include=["refs/heads/feature/**/test"], match_style="git"
        )
        assert patterns.matches("refs/heads/feature/test")
        assert patterns.matches("refs/heads/feature/x/test")
        assert patterns.matches("refs/heads/feature/x/y/test")
        assert not patterns.matches("refs/heads/feature/x/other")

    def test_exclude_with_git_style(self) -> None:
        patterns = RefPatternSet.from_refs(
            include=["release/*"],
            exclude=["release/*-rc*"],
            match_style="git",
        )
        assert patterns.matches("refs/heads/release/1.0")
        assert not patterns.matches("refs/heads/release/1.0-rc1")
        assert not patterns.matches("refs/heads/release/1.0/hotfix")

    def test_exact_match_still_works(self) -> None:
        patterns = RefPatternSet.from_branch("main", match_style="git")
        assert patterns.matches("refs/heads/main")
        assert not patterns.matches("refs/heads/mainline")
