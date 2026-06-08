# Prepared Source Payload Examples

These files define the checked-in JSON handoff examples for the LORETA
Visualizer. They are synthetic format fixtures only. They are not source
estimates and do not describe how to calculate LORETA, eLORETA, MNE inverse, or
other source-localization values.

Future source-localization calculation code can use these examples as the output
shape to target before handing data to the visualizer importer.

The companion schema files are:

- `source_payload_v1.schema.json`
- `source_manifest_v1.schema.json`

The schema files describe the JSON shape for external tools. The Python
validator in `prepared_payload_validator.py` enforces additional cross-field
rules, including one scalar value per point, valid triangle-face indices, unique
manifest condition ids, and safe relative manifest paths.

## Payload Files

Payload JSON files use:

- `format`: `fpvs-loreta-source-payload-v1`
- `label`: human-readable condition or map name
- `kind`: source display type such as `volume_mesh`
- `coordinate_space`: source coordinate-space label
- `source_model`: upstream source model or method label
- `value_label`: scalar value label
- `points`: finite `N x 3` coordinates
- `values`: finite scalar values with one value per point
- `faces`: optional triangle rows that define a mesh over `points`
- `metadata`: optional provenance and example-only notes

`source_payload_v1_fsaverage_native_example.json` is the closest shape for a
future source-localization producer that emits values in fsaverage coordinates.
The importer converts those coordinates into renderer display space through the
tool-local display transform.

`source_payload_v1_occipital_display_example.json` and
`source_payload_v1_frontal_display_example.json` are normalized display-space
examples that can be loaded without an fsaverage cache.

## Manifest Files

Manifest JSON files use:

- `format`: `fpvs-loreta-source-manifest-v1`
- `label`: human-readable manifest name
- `conditions`: entries with `id`, `label`, relative `file`, and optional
  `metadata`

Manifest `file` paths must be relative and stay inside the manifest folder.

## Producer Preflight

Future calculation code can validate output before import:

```python
from Tools.LORETA_Visualizer.prepared_payload_validator import (
    validate_prepared_source_manifest_json,
    validate_prepared_source_payload_json,
)

validate_prepared_source_payload_json("source_payload.json")
validate_prepared_source_manifest_json("source_manifest.json", require_payload_files=True)
```
