# Product Sense

Product priorities:

- Treat the processing pipeline as the core product. FHC, scalp maps, and other
  analysis/visualization tools are optional consumers of its outputs.
- Preserve trusted FPVS processing outputs.
- Keep project setup and processing workflows clear for EEG researchers.
- Make future feature additions easier by retiring confusing package boundaries.
- Prefer analysis-ready outputs that are additive and do not change existing
  workbook formats.
- Support different hardware and montages through one shared workflow with
  explicit capabilities; show only relevant setup choices and explain concrete
  unsupported combinations without cluttering the main GUI.
- Let users select supported processing methods and parameters per project,
  with saved choices, capability validation, and explicit invalidation when
  methods change. The general pipeline editor remains a future feature;
  existing scientific methods and their locked order remain reproducible.
- Make complete FPVS Studio experiment-to-analysis interoperability a product
  goal, with versioned contracts and end-to-end evidence before claiming support.

Use `docs/agent/product-specs/` for durable feature behavior.
The [hardware, pipeline, and Studio roadmap](../architecture/hardware-pipeline-studio-roadmap.md)
separates these goals from the implemented shared MNE/BIDS boundary, bounded
BioSemi64 and Brain Products routes, and partial Studio support.
