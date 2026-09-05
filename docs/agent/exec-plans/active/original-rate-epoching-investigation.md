# Investigate Original-Rate Epoching

Investigation only. Keep the current processing method unchanged; no urgent
timing fix was established for one whole-cycle sequence per condition.

- [ ] Review MNE guidance and FPVS precedent for continuous filtering, original-
  marker window extraction, then decimation from 2048 to 512/256 Hz.
- [ ] Compare with the current pipeline using synthetic signals and representative
  recordings. Preserve exact whole-cycle sample counts, filtering/notch settings,
  averaging and QC rules; distinguish alignment effects from removing the current
  Hann resampling window. Include repeated whole sequences, not cycle averaging.
- [ ] Report trigger offsets, FFT/BCA/SNR differences, changed QC decisions and
  runtime. Recommend retaining the default or offering an optional method.

Deliverable: a brief evidence-based decision. Any implementation needs a separate
approved method-change plan, versioned provenance and updated processing contracts.
