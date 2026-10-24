# inspect_analysis_package_rdescriptor

## API Definition

```python
def inspect_analysis_package_rdescriptor(package_dir: str | Path, target_path: str | Path, *, expected_config: Mapping[str, Any], sdk_version: str | None = None) -> dict[str, Any]
```

*Source: inspect/brep/analysis_package.py*

## Import Surface

- inspection namespace: `from simplecadapi.inspect import brep` then `brep.inspect_analysis_package_rdescriptor(...)`; unavailable inside GraphSession

## Description

Check whether a saved analysis package may start STEP reconstruction.

This is the R0 gate of ``step-reconstruction.md``. It reads the package
written by ``step-computational-geometry-analysis.md`` and the target STEP,
and never reruns recognition. Hard failures mean the package must be
regenerated; soft gaps are budget-skipped per-feature visuals and
``incomplete`` loft/sweep specialist entries declared under
``complete_with_gaps``.

## Parameters

### package_dir

- **Description**: Directory holding the analysis package.

### target_path

- **Description**: Target STEP file whose current SHA-256 the package must match.

### expected_config

- **Description**: Recognition parameters of the current request, compared key by key with ``analysis-config.json``. Use the keys in ``RECOGNITION_CONFIG_KEYS``; ``feature_kinds`` ignores order.

### sdk_version

- **Description**: SDK version the package must have been built with. Defaults to the installed ``simplecadapi`` version.

## Returns

-------
dict
``status`` is ``pass``, ``pass_with_gaps``, or ``fail``;
``may_start_reconstruction`` is true only without hard failures.
``hard_failures`` and ``soft_gaps`` list ``code``/``detail`` records;
the result also reports the current ``target_sha256``, the number of
manifest artifacts checked, and the accepted schema versions.
