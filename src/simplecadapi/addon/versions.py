"""Compatibility ranges for ``[compat] sca`` in ``sca-addon.toml``.

Supported syntax — deliberately a small, documented subset:

* versions are dot-separated numeric components with optional
  pre-release suffixes (``2.1.2``, ``2.0.4b2``); a suffix sorts before
  the same numeric component without one (``2.0.4b2 < 2.0.4``);
* a trailing ``.postN`` component is a post-release (PEP 440): it sorts
  after the release it follows and before the next one
  (``2.2.6 < 2.2.6.post1 < 2.2.6.post2 < 2.2.7``);
* ranges are comma-separated clauses with the operators
  ``== != >= <= > <``; a bare version means exact equality;
* clauses must be jointly satisfiable (``>=2.1,<2.0`` is rejected).

Wildcards (``*``), extras, and PEP 440 epochs are out of scope.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from . import AddonError

_CLAUSE_RE = re.compile(r"^(==|!=|>=|<=|>|<)?\s*([0-9][0-9A-Za-z.]*)$")
_COMPONENT_RE = re.compile(r"^([0-9]+)([a-zA-Z][0-9A-Za-z]*)?$")
_POST_RE = re.compile(r"^post([0-9]+)$")


class VersionSpecError(AddonError):
    """Raised when a version literal or compat range cannot be parsed."""


def version_key(text: str) -> tuple[tuple[int, int, str], ...]:
    """Parse a dotted version into a sortable key, padding-compatible."""
    stripped = text.strip()
    if not stripped:
        raise VersionSpecError("empty version literal")
    components: list[tuple[int, int, str]] = []
    for part in stripped.split("."):
        post = _POST_RE.match(part)
        if post is not None and components:
            # after the release it follows (a missing component pads as (0, 1, "")),
            # and in order among post-releases
            components.append((int(post.group(1)), 2, ""))
            continue
        match = _COMPONENT_RE.match(part)
        if match is None:
            raise VersionSpecError(
                f"invalid version component {part!r} in {stripped!r}: expected "
                "dot-separated numerics with optional suffix (e.g. 2.1.2, 2.0.4b2)"
            )
        numeric = int(match.group(1))
        suffix = match.group(2) or ""
        # A bare numeric component sorts after the same numeric with a
        # pre-release suffix: 2.0.4b2 < 2.0.4.
        components.append((numeric, 1 if not suffix else 0, suffix))
    return tuple(components)


def _padded(
    left: tuple[tuple[int, int, str], ...], right: tuple[tuple[int, int, str], ...]
) -> tuple[tuple[tuple[int, int, str], ...], tuple[tuple[int, int, str], ...]]:
    pad = (0, 1, "")
    delta = len(left) - len(right)
    if delta > 0:
        return left, right + (pad,) * delta
    return left + (pad,) * (-delta), right


def compare_versions(left: str, right: str) -> int:
    """Compare two version literals: negative/zero/positive."""
    left_key, right_key = _padded(version_key(left), version_key(right))
    if left_key < right_key:
        return -1
    if left_key > right_key:
        return 1
    return 0


def _clause_holds(operator: str, candidate: str, bound: str) -> bool:
    order = compare_versions(candidate, bound)
    if operator == "==":
        return order == 0
    if operator == "!=":
        return order != 0
    if operator == ">=":
        return order >= 0
    if operator == "<=":
        return order <= 0
    if operator == ">":
        return order > 0
    if operator == "<":
        return order < 0
    raise VersionSpecError(f"unsupported operator {operator!r}")


def _strongest_lower(
    clauses: tuple[tuple[str, str], ...]
) -> tuple[str, str] | None:
    best: tuple[str, str] | None = None
    for clause in clauses:
        if best is None or compare_versions(clause[1], best[1]) > 0:
            best = clause
    return best


def _strongest_upper(
    clauses: tuple[tuple[str, str], ...]
) -> tuple[str, str] | None:
    best: tuple[str, str] | None = None
    for clause in clauses:
        if best is None or compare_versions(clause[1], best[1]) < 0:
            best = clause
    return best


@dataclass(frozen=True)
class VersionRange:
    """A parsed compat range: a conjunction of operator/version clauses."""

    clauses: tuple[tuple[str, str], ...]

    @classmethod
    def parse(cls, spec: str) -> VersionRange:
        if not isinstance(spec, str) or not spec.strip():
            raise VersionSpecError("compat range must be a non-empty string")
        clauses: list[tuple[str, str]] = []
        for chunk in spec.split(","):
            text = chunk.strip()
            if not text:
                raise VersionSpecError(f"empty clause in compat range {spec!r}")
            match = _CLAUSE_RE.match(text)
            if match is None:
                raise VersionSpecError(
                    f"invalid clause {text!r} in compat range {spec!r}: expected "
                    "comma-separated clauses like '>=2.1,<3' (operators "
                    "== != >= <= > <; a bare version means exact match)"
                )
            operator = match.group(1) or "=="
            bound = match.group(2)
            try:
                version_key(bound)
            except VersionSpecError as exc:
                raise VersionSpecError(f"invalid clause {text!r}: {exc}") from exc
            clauses.append((operator, bound))
        parsed = cls(clauses=tuple(clauses))
        parsed._check_conflicts()
        return parsed

    def _check_conflicts(self) -> None:
        equals = [bound for op, bound in self.clauses if op == "=="]
        for left, right in zip(equals, equals[1:]):
            if compare_versions(left, right) != 0:
                raise VersionSpecError(f"conflicting equality clauses =={left} and =={right}")
        lowers = [(op, bound) for op, bound in self.clauses if op in {">", ">="}]
        uppers = [(op, bound) for op, bound in self.clauses if op in {"<", "<="}]
        if equals:
            point = equals[0]
            if not self.matches(point):
                offending = next(
                    f"{op}{bound}"
                    for op, bound in self.clauses
                    if not _clause_holds(op, point, bound)
                )
                raise VersionSpecError(
                    f"conflicting clauses: =={point} contradicts {offending}"
                )
            return
        lower = _strongest_lower(tuple(lowers))
        upper = _strongest_upper(tuple(uppers))
        if lower is None or upper is None:
            return
        order = compare_versions(lower[1], upper[1])
        if order > 0 or (
            order == 0 and (">" in {lower[0], upper[0]})
        ):
            raise VersionSpecError(
                f"conflicting clauses: range is empty between {lower[0]}{lower[1]} "
                f"and {upper[0]}{upper[1]}"
            )

    def matches(self, candidate: str) -> bool:
        return all(_clause_holds(op, candidate, bound) for op, bound in self.clauses)

    def __str__(self) -> str:  # pragma: no cover - display only
        return ",".join(f"{op}{bound}" for op, bound in self.clauses)
