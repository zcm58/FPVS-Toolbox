# Sequence Figure

Sequence Figure creates a five-image diagram of an FPVS oddball sequence for a
manuscript, poster, presentation, preregistration, or study handout.

## Layout

The first four slots are base images and the fifth slot is the oddball image.
The selected images are center-cropped to squares, the oddball is outlined, and
the figure includes separate square-wave timing traces for the presentation
rate `F` and oddball rate `f`.

The tool accepts `.bmp`, `.jpg`, `.jpeg`, `.png`, `.tif`, and `.tiff` images.
Use images that can be cropped to a square without removing important content.
Low-resolution source images produce a warning; approximately 1024 pixels on
the short side is sufficient for the default figure layout without a warning.

## Inputs

Select exactly five images, enter the base and oddball frequencies shown in the
timing labels, choose an output basename, and select an existing output folder.
If the active project already contains a `Figures` folder, the tool uses it as
the initial output location.

The frequency entries are figure labels. Sequence Figure does not read EEG
data, validate trigger timing, or alter the experiment configuration.

## Outputs

Each export creates three files with the same basename:

- a 600-DPI `.png` raster image;
- a `.pdf` figure; and
- an editable vector `.svg` figure.

Unsupported filename characters are replaced with underscores. Review the
exported diagram against the actual experiment before including it in study
materials.

## Basic Steps

1. Add four representative base images to slots 1–4.
2. Add the representative oddball image to slot 5.
3. Enter the presentation and oddball rates used by the experiment.
4. Choose the basename and output folder.
5. Select **Export Figure** and review all warnings.

An example caption is: “Schematic FPVS sequence. Base stimuli were presented at
`F` Hz, with an oddball stimulus inserted every *n*th image at `f` Hz.” Replace
the placeholders with the actual design and describe any image randomization
not visible in the schematic.

## References

- Rossion, B., Retter, T. L., & Liu-Shuang, J. (2020). [Understanding human individuation of unfamiliar faces with oddball fast periodic visual stimulation and electroencephalography](https://doi.org/10.1111/ejn.14865). *European Journal of Neuroscience, 52*(10), 4283–4344.
- [Sequence Figure implementation](https://github.com/zcm58/FPVS-Toolbox-Repo/tree/main/src/Tools/Sequence_Figure).
