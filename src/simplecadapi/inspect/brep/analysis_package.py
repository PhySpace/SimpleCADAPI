"""Validate a saved computational-geometry analysis package before reconstruction.

The checks mirror R0 of ``step-reconstruction.md``: they read saved files and
the target STEP only, and never rerun recognition or rendering.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
from pathlib import Path
from typing import Any, Mapping

from .feature_catalog import CATALOG_SCHEMA_VERSION
from .manufacturing import _model
from .model import BRepEntityError
from .reconstruction_contract import RECONSTRUCTION_SCHEMA_VERSION


ACCEPTED_CATALOG_SCHEMA_VERSIONS = (CATALOG_SCHEMA_VERSION,)
ACCEPTED_RECONSTRUCTION_SCHEMA_VERSIONS = (RECONSTRUCTION_SCHEMA_VERSION,)
RECOGNITION_CONFIG_KEYS = (
    "feature_kinds",
    "linear_tolerance",
    "angular_tolerance_degrees",
    "max_features",
    "section_rule",
)
PACKAGE_JSON_FILES = (
    "analysis-config.json",
    "run-status.json",
    "target-summary.json",
    "raw-feature-hints.json",
    "feature-index.json",
    "feature-summary.json",
    "reconstruction-hypotheses.json",
    "loft-sweep-specialist.json",
    "section-index.json",
    "visual-index.json",
    "artifact-manifest.json",
)
PACKAGE_TEXT_FILES = (
    "requirement-brief.md",
    "parse-report.md",
    "unresolved-features.md",
)
_ENTITY_FIELDS = ("entity_ids", "highlight_entity_ids", "support_entity_ids")
_FINISHED_STATUSES = ("complete", "complete_with_gaps")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _issue(code: str, detail: str, **extra: Any) -> dict[str, Any]:
    return {"code": code, "detail": detail, **extra}


def _installed_sdk_version() -> str | None:
    try:
        return importlib.metadata.version("simplecadapi")
    except importlib.metadata.PackageNotFoundError:
        return None


def _load_documents(
    root: Path, failures: list[dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    documents: dict[str, dict[str, Any]] = {}
    for name in PACKAGE_JSON_FILES:
        path = root / name
        if not path.is_file():
            failures.append(_issue("missing_file", f"{name} is missing", path=name))
            continue
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            failures.append(_issue("invalid_json", f"{name}: {error}", path=name))
            continue
        if not isinstance(value, dict):
            failures.append(
                _issue("invalid_json", f"{name} root must be an object", path=name)
            )
            continue
        documents[name] = value
    for name in PACKAGE_TEXT_FILES:
        if not (root / name).is_file():
            failures.append(_issue("missing_file", f"{name} is missing", path=name))
    return documents


def _check_target_hash(
    current: str,
    documents: Mapping[str, Mapping[str, Any]],
    failures: list[dict[str, Any]],
) -> None:
    for name in ("feature-index.json", "artifact-manifest.json"):
        if name in documents and "target_sha256" not in documents[name]:
            failures.append(
                _issue("target_hash_missing", f"{name} has no target_sha256", path=name)
            )
    for name, document in documents.items():
        recorded = document.get("target_sha256")
        if recorded is not None and recorded != current:
            failures.append(
                _issue(
                    "target_hash_mismatch",
                    f"{name} records {recorded}, target is {current}",
                    path=name,
                )
            )
    catalog = documents.get("feature-index.json", {})
    for feature in catalog.get("features", ()):
        if feature.get("target_sha256") != current:
            failures.append(
                _issue(
                    "target_hash_mismatch",
                    "feature records a different target hash",
                    feature_id=feature.get("feature_id"),
                )
            )


def _config_value(key: str, value: Any) -> Any:
    if key == "feature_kinds" and isinstance(value, (list, tuple)):
        return sorted(str(item) for item in value)
    return value


def _check_config(
    config: Mapping[str, Any] | None,
    expected: Mapping[str, Any],
    failures: list[dict[str, Any]],
) -> None:
    if config is None:
        return
    for key, value in expected.items():
        if key not in config:
            failures.append(
                _issue("config_key_missing", f"analysis-config.json has no {key}", key=key)
            )
        elif _config_value(key, config[key]) != _config_value(key, value):
            failures.append(
                _issue(
                    "config_mismatch",
                    f"{key}: package {config[key]!r}, request {value!r}",
                    key=key,
                )
            )


def _check_run_status(
    status: Mapping[str, Any] | None,
    sdk_version: str | None,
    failures: list[dict[str, Any]],
) -> None:
    if status is None:
        return
    state = status.get("status")
    if state not in _FINISHED_STATUSES:
        failures.append(
            _issue(
                "run_not_complete",
                f"run-status.json status is {state!r}",
                failed_phase=status.get("failed_phase"),
            )
        )
    if state == "complete_with_gaps" and status.get("route") != "reconstruction_prelude":
        failures.append(
            _issue(
                "gap_status_wrong_route",
                "complete_with_gaps is only valid for route reconstruction_prelude",
            )
        )
    recorded = status.get("sdk_version")
    if recorded is None:
        failures.append(
            _issue("sdk_version_missing", "run-status.json has no sdk_version")
        )
    elif sdk_version is None:
        failures.append(
            _issue("sdk_version_unknown", "installed simplecadapi version is unknown")
        )
    elif recorded != sdk_version:
        failures.append(
            _issue(
                "sdk_version_mismatch",
                f"package built with {recorded}, installed {sdk_version}",
            )
        )


def _check_catalog(
    catalog: Mapping[str, Any] | None,
    hypotheses: Mapping[str, Any] | None,
    failures: list[dict[str, Any]],
) -> None:
    if catalog is None:
        return
    version = catalog.get("schema_version")
    if version not in ACCEPTED_CATALOG_SCHEMA_VERSIONS:
        failures.append(
            _issue(
                "catalog_schema_unsupported",
                f"feature-index.json schema_version {version!r} is not accepted",
            )
        )
    if catalog.get("truncated") is not False or catalog.get("complete") is not True:
        failures.append(
            _issue(
                "catalog_incomplete",
                "feature-index.json must have truncated=false and complete=true",
            )
        )
    contracts: dict[str, Any] = {}
    for feature in catalog.get("features", ()):
        contract = feature.get("reconstruction")
        if contract is None:
            continue
        contracts[str(feature.get("feature_id"))] = contract
        if contract.get("schema_version") not in ACCEPTED_RECONSTRUCTION_SCHEMA_VERSIONS:
            failures.append(
                _issue(
                    "reconstruction_schema_unsupported",
                    f"schema_version {contract.get('schema_version')!r} is not accepted",
                    feature_id=feature.get("feature_id"),
                )
            )
    if hypotheses is None:
        return
    saved = hypotheses.get("hypotheses")
    if not isinstance(saved, dict) or set(saved) != set(contracts):
        failures.append(
            _issue(
                "hypotheses_mismatch",
                "reconstruction-hypotheses.json must hold exactly the non-null "
                "reconstruction handoffs keyed by feature_id",
            )
        )
        return
    for feature_id, contract in contracts.items():
        if saved[feature_id] != contract:
            failures.append(
                _issue(
                    "hypothesis_changed",
                    "saved handoff differs from feature-index.json",
                    feature_id=feature_id,
                )
            )


def _check_manifest(
    root: Path,
    manifest: Mapping[str, Any] | None,
    failures: list[dict[str, Any]],
) -> int:
    if manifest is None:
        return 0
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        failures.append(_issue("manifest_invalid", "artifacts must be a list"))
        return 0
    resolved_root = root.resolve()
    listed: set[str] = set()
    for item in artifacts:
        relative = str(item.get("path", ""))
        path = (root / relative).resolve()
        if not relative or not path.is_relative_to(resolved_root):
            failures.append(
                _issue("manifest_path_invalid", f"{relative!r} leaves the package")
            )
            continue
        listed.add(Path(relative).as_posix())
        if not path.is_file():
            failures.append(
                _issue("manifest_file_missing", f"{relative} is missing", path=relative)
            )
        elif path.stat().st_size != item.get("bytes") or _sha256(path) != item.get(
            "sha256"
        ):
            failures.append(
                _issue(
                    "manifest_hash_mismatch",
                    f"{relative} bytes or SHA-256 differ from the manifest",
                    path=relative,
                )
            )
    for name in (*PACKAGE_JSON_FILES, *PACKAGE_TEXT_FILES):
        if name != "artifact-manifest.json" and name not in listed:
            failures.append(
                _issue("manifest_incomplete", f"{name} is not listed", path=name)
            )
    return len(artifacts)


def _collect_gaps(
    status: Mapping[str, Any] | None,
    visual_index: Mapping[str, Any] | None,
    specialist: Mapping[str, Any] | None,
    failures: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    gaps: list[dict[str, Any]] = []
    for entry in (visual_index or {}).get("visuals", ()):
        if entry.get("status") == "skipped":
            gaps.append(
                _issue(
                    "visual_skipped",
                    str(entry.get("reason", "")),
                    feature_id=entry.get("feature_id"),
                )
            )
    for entry in (specialist or {}).get("entries", ()):
        if entry.get("status") == "incomplete":
            gaps.append(
                _issue(
                    "specialist_incomplete",
                    str(entry.get("reason", "")),
                    feature_id=entry.get("feature_id"),
                )
            )
    if status is None or not gaps:
        return gaps
    if status.get("status") == "complete":
        failures.append(
            _issue(
                "undeclared_gaps",
                f"{len(gaps)} gap(s) exist but run-status.json is complete",
            )
        )
        return gaps
    declared = {
        (gap.get("code"), gap.get("feature_id")) for gap in status.get("gaps", ())
    }
    for gap in gaps:
        if (gap["code"], gap["feature_id"]) not in declared:
            failures.append(
                _issue(
                    "unlisted_gap",
                    f"{gap['code']} is not listed in run-status.json gaps",
                    feature_id=gap["feature_id"],
                )
            )
    return gaps


def _check_entities(
    target: Path, catalog: Mapping[str, Any], failures: list[dict[str, Any]]
) -> None:
    model = _model(target)
    for feature in catalog.get("features", ()):
        for field in _ENTITY_FIELDS:
            for entity_id in feature.get(field, ()):
                try:
                    model.resolve_entity(str(entity_id))
                except BRepEntityError:
                    failures.append(
                        _issue(
                            "entity_unresolved",
                            f"{field} entry {entity_id} does not exist on the target",
                            feature_id=feature.get("feature_id"),
                        )
                    )


def inspect_analysis_package_rdescriptor(
    package_dir: str | Path,
    target_path: str | Path,
    *,
    expected_config: Mapping[str, Any],
    sdk_version: str | None = None,
) -> dict[str, Any]:
    """Check whether a saved analysis package may start STEP reconstruction.

    This is the R0 gate of ``step-reconstruction.md``. It reads the package
    written by ``step-computational-geometry-analysis.md`` and the target STEP,
    and never reruns recognition. Hard failures mean the package must be
    regenerated; soft gaps are budget-skipped per-feature visuals and
    ``incomplete`` loft/sweep specialist entries declared under
    ``complete_with_gaps``.

    Parameters
    ----------
    package_dir:
        Directory holding the analysis package.
    target_path:
        Target STEP file whose current SHA-256 the package must match.
    expected_config:
        Recognition parameters of the current request, compared key by key
        with ``analysis-config.json``. Use the keys in
        ``RECOGNITION_CONFIG_KEYS``; ``feature_kinds`` ignores order.
    sdk_version:
        SDK version the package must have been built with. Defaults to the
        installed ``simplecadapi`` version.

    Returns
    -------
    dict
        ``status`` is ``pass``, ``pass_with_gaps``, or ``fail``;
        ``may_start_reconstruction`` is true only without hard failures.
        ``hard_failures`` and ``soft_gaps`` list ``code``/``detail`` records;
        the result also reports the current ``target_sha256``, the number of
        manifest artifacts checked, and the accepted schema versions.
    """

    root = Path(package_dir)
    target = Path(target_path)
    failures: list[dict[str, Any]] = []
    current = _sha256(target) if target.is_file() else None
    if current is None:
        failures.append(_issue("target_missing", f"{target} is not a file"))
    documents: dict[str, dict[str, Any]] = {}
    gaps: list[dict[str, Any]] = []
    checked = 0
    if not root.is_dir():
        failures.append(_issue("package_missing", f"{root} is not a directory"))
    else:
        documents = _load_documents(root, failures)
        if current is not None:
            _check_target_hash(current, documents, failures)
        _check_config(
            documents.get("analysis-config.json"), expected_config, failures
        )
        _check_run_status(
            documents.get("run-status.json"),
            sdk_version or _installed_sdk_version(),
            failures,
        )
        _check_catalog(
            documents.get("feature-index.json"),
            documents.get("reconstruction-hypotheses.json"),
            failures,
        )
        checked = _check_manifest(
            root, documents.get("artifact-manifest.json"), failures
        )
        gaps = _collect_gaps(
            documents.get("run-status.json"),
            documents.get("visual-index.json"),
            documents.get("loft-sweep-specialist.json"),
            failures,
        )
        catalog = documents.get("feature-index.json")
        if current is not None and catalog is not None and not any(
            failure["code"] == "target_hash_mismatch" for failure in failures
        ):
            _check_entities(target, catalog, failures)
    if failures:
        status = "fail"
    else:
        status = "pass_with_gaps" if gaps else "pass"
    return {
        "status": status,
        "may_start_reconstruction": not failures,
        "package_dir": str(root),
        "target_path": str(target),
        "target_sha256": current,
        "hard_failures": failures,
        "soft_gaps": gaps,
        "checked_artifact_count": checked,
        "accepted_schema_versions": {
            "catalog": list(ACCEPTED_CATALOG_SCHEMA_VERSIONS),
            "reconstruction": list(ACCEPTED_RECONSTRUCTION_SCHEMA_VERSIONS),
        },
    }


__all__ = [
    "ACCEPTED_CATALOG_SCHEMA_VERSIONS",
    "ACCEPTED_RECONSTRUCTION_SCHEMA_VERSIONS",
    "PACKAGE_JSON_FILES",
    "PACKAGE_TEXT_FILES",
    "RECOGNITION_CONFIG_KEYS",
    "inspect_analysis_package_rdescriptor",
]
