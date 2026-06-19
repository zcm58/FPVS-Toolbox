# Sequence Figure

Use this tool when you need a publication-oriented illustration of an FPVS
stimulus sequence for a thesis, presentation, poster, or manuscript.

The Sequence Figure tool builds a fixed five-slot sequence illustration from
manually selected stimulus images. It draws the timing scaffold and labels for
the presentation frequency (`F`) and oddball frequency (`f`), then exports the
figure as high-resolution PNG plus editable/vector PDF and SVG files.

## Inputs

- Five stimulus images, selected in display order.
- Presentation rate label, default `F = 6 Hz`.
- Oddball rate label, default `f = 1.2 Hz`.
- Output folder and output basename.

The fifth slot is outlined to mark the oddball item in the sequence. Select the
specific images you want shown; this tool does not sample images from condition
folders.

## Outputs

The output folder receives:

- `*.png` at 600 DPI for direct use in documents or slides;
- `*.pdf` for vector publication workflows;
- `*.svg` for additional editing in tools such as PowerPoint, Illustrator,
  Inkscape, or Affinity Designer.

If a selected source image is too small for the requested export size, the tool
still exports the figure but reports a warning in the completion dialog. Use
larger source images when possible for final manuscripts.

## Notes

This tool is separate from the SNR Plot Generator. Use Sequence Figure for
stimulus-sequence illustrations, and use SNR Plot Generator for frequency-domain
response plots from FPVS Toolbox Excel outputs.
