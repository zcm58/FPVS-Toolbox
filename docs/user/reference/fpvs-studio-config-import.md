# FPVS Studio Config Import

FPVS Toolbox can create a project shell from an FPVS Studio `.fpvsconfig` file.
This import is intentionally narrow: it seeds the Toolbox project title and
event map, then asks you to select the folder containing the raw `.bdf` files.
You still review processing settings in the Toolbox before running the pipeline.

## Imported fields

| Studio `.fpvsconfig` field | Toolbox use |
|---|---|
| `project.name` | Toolbox project title |
| `conditions[].name` | Event map condition label |
| `conditions[].trigger_code` | Event map trigger code |

The importer expects `schema_version` to be `"1.0.0"` and at least one
condition. Condition names must be non-empty and unique. Trigger codes must be
positive integers and unique.

## Minimal shape

```json
{
  "schema_version": "1.0.0",
  "project": {
    "name": "Semantic Categories Test"
  },
  "conditions": [
    {
      "name": "Fruit vs Vegetable",
      "trigger_code": 1
    },
    {
      "name": "Veg vs Fruit",
      "trigger_code": 2
    }
  ]
}
```

## Not imported

The importer does not copy images, completed-session order, participant data,
EEG files, or preprocessing settings. It stores the selected raw-data folder in
the Toolbox project manifest. The oddball trigger remains the Toolbox
analysis convention documented for the processing pipeline.
