# Sequence Figure

Sequence Figure illustrates FPVS oddball sequences for one to four conditions
in a single figure for a manuscript, poster, presentation, preregistration, or
study handout. Three conditions are selected by default.

Sequence Figure is currently available under **Beta Tools**. Enable Beta Tools
in **Settings > Advanced**, then close and reopen FPVS Toolbox.

## Layout

Each condition has four base-image slots and a fifth oddball-image slot. The
selected images are center-cropped to squares and repeated twice horizontally
to show two oddball cycles. The figure stacks the selected conditions, labels
each row, highlights the oddball columns, and includes separate square-wave
timing traces for the presentation rate `F` and oddball rate `f`.

The export retains the fixed 13.333 x 7.5 inch figure size. Four conditions are
the hard limit; that layout uses slightly smaller images to keep rows separate.

The tool accepts `.bmp`, `.jpg`, `.jpeg`, `.png`, `.tif`, and `.tiff` images.
Use images that can be cropped to a square without removing important content.
Low-resolution source images produce a warning; approximately 1024 pixels on
the short side is sufficient for the default figure layout without a warning.

## Inputs

Choose the condition count, then use each condition tab to select five images
and enter a label of up to 24 characters. Long labels wrap in the exported
figure. Reducing the count hides extra conditions without discarding their
current-session images or labels; hidden conditions are not exported.

Enter the base and oddball frequencies shown in the timing labels, choose an
output basename, and select an existing output folder. If the active project
already contains a `Figures` folder, the tool uses it as the initial output
location. The tool does not write project settings or participant metadata.

The frequency entries are figure labels. The schematic always shows four base
images followed by one oddball; changing the labels does not change that
pattern. Sequence Figure does not read EEG data, validate trigger timing, or
alter the experiment configuration.

Optional styling controls:

- **Grayscale-safe lines and frames** distinguishes base and oddball markers
  using tone, solid/dashed lines, and hatching. It does not recolor the stimulus
  images themselves.
- **Transparent PDF background** removes the PDF page background. PNG and SVG
  exports retain a white background.

## Outputs

Each export creates three files with the same basename:

- a 600-DPI `.png` raster image;
- a `.pdf` figure; and
- an editable vector `.svg` figure.

Unsupported filename characters are replaced with underscores. Review the
exported diagram against the actual experiment before including it in study
materials.

## Basic Steps

1. Select one to four conditions.
2. In each condition tab, enter its label and add four base images to slots
   1–4 plus the representative oddball image in slot 5.
3. Enter the presentation and oddball rates used by the experiment.
4. Choose any optional styling, the basename, and the output folder.
5. Select **Export Figure** and review all warnings and exported condition rows.

An example caption is: “Schematic FPVS sequence. Base stimuli were presented at
`F` Hz, with an oddball stimulus inserted every *n*th image at `f` Hz.” Replace
the placeholders with the actual design and describe any image randomization
not visible in the schematic.

## References

- Rossion, B., Retter, T. L., & Liu-Shuang, J. (2020). [Understanding human individuation of unfamiliar faces with oddball fast periodic visual stimulation and electroencephalography](https://doi.org/10.1111/ejn.14865). *European Journal of Neuroscience, 52*(10), 4283–4344.
- [Sequence Figure implementation](https://github.com/zcm58/FPVS-Toolbox-Repo/tree/main/src/Tools/Sequence_Figure).
