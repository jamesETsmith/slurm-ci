"""Pure-logic helpers for matching git refs against user-supplied patterns.

This module is intentionally side-effect free: it does not touch the network,
the filesystem, or ``subprocess``. The goal is to have the ref-matching
semantics fully unit-tested in isolation so they can later be wired into
``git_watcher.py`` without changing observable behavior.

Two match styles are supported:

* ``"fnmatch"`` (default, preserves current ``git_watcher`` behavior) uses
  :func:`fnmatch.fnmatchcase` on the full ref name. ``*`` matches across ``/``.
* ``"git"`` uses a segment-aware matcher where ``*`` never crosses ``/``, and
  a segment of ``**`` matches zero or more path segments. This is closer to
  git's own wildmatch semantics and is what most users mean when they write
  ``release/*``.
"""

from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatchcase
from typing import Iterable, Literal


MatchStyle = Literal["fnmatch", "git"]

_DEFAULT_MATCH_STYLE: MatchStyle = "fnmatch"
_VALID_MATCH_STYLES: tuple[MatchStyle, ...] = ("fnmatch", "git")


def normalize_ref(value: str) -> str:
    """Normalize a user-supplied branch/ref string to a fully-qualified ref.

    Strings that already start with ``refs/`` are returned unchanged. Anything
    else is treated as a short branch name and expanded to
    ``refs/heads/<value>``.
    """
    if not value:
        raise ValueError("Ref pattern must be a non-empty string")
    if value.startswith("refs/"):
        return value
    return f"refs/heads/{value}"


def ref_kind(ref_name: str) -> str:
    """Return the category of a fully-qualified ref name.

    Returns one of ``"heads"``, ``"tags"``, or ``"other"``.
    """
    if ref_name.startswith("refs/heads/"):
        return "heads"
    if ref_name.startswith("refs/tags/"):
        return "tags"
    return "other"


def short_name(ref_name: str) -> str:
    """Strip the ``refs/heads/`` or ``refs/tags/`` prefix from ``ref_name``.

    Refs outside these two well-known namespaces are returned unchanged so
    callers can still display them meaningfully.
    """
    for prefix in ("refs/heads/", "refs/tags/"):
        if ref_name.startswith(prefix):
            return ref_name[len(prefix) :]
    return ref_name


def _match_segments(pattern_parts: list[str], value_parts: list[str]) -> bool:
    if not pattern_parts:
        return not value_parts

    head, rest = pattern_parts[0], pattern_parts[1:]

    if head == "**":
        if not rest:
            return True
        for i in range(len(value_parts) + 1):
            if _match_segments(rest, value_parts[i:]):
                return True
        return False

    if not value_parts:
        return False

    if not fnmatchcase(value_parts[0], head):
        return False

    return _match_segments(rest, value_parts[1:])


def _git_style_match(pattern: str, value: str) -> bool:
    """Match ``value`` against ``pattern`` using git-style glob semantics.

    ``*`` matches within a single path segment (it does not cross ``/``).
    A segment consisting entirely of ``**`` matches zero or more segments.
    All other wildcard syntax follows :func:`fnmatch.fnmatchcase` within a
    single segment.
    """
    return _match_segments(pattern.split("/"), value.split("/"))


def _matches_any(patterns: Iterable[str], ref_name: str, style: MatchStyle) -> bool:
    for pattern in patterns:
        if style == "git":
            if _git_style_match(pattern, ref_name):
                return True
        else:
            if fnmatchcase(ref_name, pattern):
                return True
    return False


def _dedupe(values: Iterable[str]) -> tuple[str, ...]:
    seen: dict[str, None] = {}
    for value in values:
        seen.setdefault(value, None)
    return tuple(seen)


@dataclass(frozen=True)
class RefPatternSet:
    """Normalized set of include/exclude ref patterns.

    All patterns are stored as fully-qualified refs (``refs/heads/...`` or
    ``refs/tags/...``), so the same matcher can be used uniformly for
    branches and tags. Use the ``from_*`` classmethods to build instances
    from user-facing config rather than constructing directly.
    """

    include: tuple[str, ...]
    exclude: tuple[str, ...] = ()
    match_style: MatchStyle = _DEFAULT_MATCH_STYLE

    def __post_init__(self) -> None:
        if not self.include:
            raise ValueError("RefPatternSet requires at least one include pattern")
        if self.match_style not in _VALID_MATCH_STYLES:
            raise ValueError(
                f"Unknown match_style {self.match_style!r}; "
                f"expected one of {_VALID_MATCH_STYLES}"
            )

    @classmethod
    def from_branch(
        cls, branch: str, *, match_style: MatchStyle = _DEFAULT_MATCH_STYLE
    ) -> "RefPatternSet":
        """Create a pattern set from a single legacy branch string.

        Mirrors the historical ``GitWatchConfig.branch`` scalar: short names
        are expanded to ``refs/heads/<branch>``; fully-qualified refs pass
        through unchanged.
        """
        return cls(include=(normalize_ref(branch),), match_style=match_style)

    @classmethod
    def from_branches(
        cls,
        branches: Iterable[str],
        *,
        match_style: MatchStyle = _DEFAULT_MATCH_STYLE,
    ) -> "RefPatternSet":
        """Create a pattern set from a list of branch/ref strings."""
        include = tuple(normalize_ref(b) for b in branches)
        if not include:
            raise ValueError("'branches' must contain at least one entry")
        return cls(include=include, match_style=match_style)

    @classmethod
    def from_refs(
        cls,
        include: Iterable[str],
        exclude: Iterable[str] = (),
        *,
        match_style: MatchStyle = _DEFAULT_MATCH_STYLE,
    ) -> "RefPatternSet":
        """Create a pattern set from explicit include/exclude ref patterns.

        Entries are normalized via :func:`normalize_ref` so callers may pass
        either short branch names or fully-qualified refs.
        """
        include_tuple = _dedupe(normalize_ref(p) for p in include)
        exclude_tuple = _dedupe(normalize_ref(p) for p in exclude)
        if not include_tuple:
            raise ValueError("'include' must contain at least one entry")
        return cls(
            include=include_tuple,
            exclude=exclude_tuple,
            match_style=match_style,
        )

    def ls_remote_args(self) -> list[str]:
        """Return the ref patterns to pass to ``git ls-remote``.

        Only includes are sent to the remote; excludes are applied
        client-side by :meth:`matches`. Duplicates are collapsed while
        preserving original order.
        """
        return list(_dedupe(self.include))

    def matches(self, ref_name: str) -> bool:
        """Return whether a fully-qualified ``ref_name`` should be processed.

        A ref matches when at least one include pattern matches and no
        exclude pattern matches. Matching uses the configured
        :attr:`match_style`.
        """
        if not _matches_any(self.include, ref_name, self.match_style):
            return False
        if _matches_any(self.exclude, ref_name, self.match_style):
            return False
        return True
