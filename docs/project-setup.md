# Project Setup

Use this page when you are creating a new FPVS Toolbox project or checking whether your folders, groups, and trigger codes are ready for processing.

A project stores the information FPVS Toolbox needs to process your data consistently: where the files are, what groups exist, which condition labels belong to which trigger codes, and where outputs should be saved.

## Before you create the project

Prepare:

- A local project root folder.
- Raw BioSemi `.bdf` files.
- Group names, if your study has more than one participant group.
- Condition names.
- Numeric trigger codes for each condition.
- Preprocessing settings you plan to use.

!!! warning "Avoid cloud-synced folders"
    Do not use OneDrive, Dropbox, Google Drive, or network folders as the active project root. Sync tools can lock Excel files and logs while FPVS Toolbox is writing them.

## Recommended project layout

```text
FPVS_Projects
  -> My_Study
       -> Raw files or input folders
       -> Project settings
       -> Processing outputs
       -> Statistical analysis results
```

Alt text: A simple FPVS project folder with raw input files, project settings, processing outputs, and statistical analysis results.

## Create a project

1. Open FPVS Toolbox.
2. Choose a local project root.
3. Click **Create New Project**.
4. Enter a short project name.
5. Add group names if needed.
6. Choose the input folder for each group.
7. Add condition labels and trigger codes.
8. Save the project.

## Event map checklist

| Check | Why it matters |
|---|---|
| Each condition has the correct numeric code. | Wrong codes cause missing condition outputs. |
| Codes match the values in the `.bdf` trigger channel. | The app cannot infer task codes automatically. |
| Condition labels are readable. | Labels become folder and file names. |
| Labels avoid Windows filename symbols. | Symbols such as `/`, `\`, `:`, `*`, and `?` can break output paths. |

## Good first-run strategy

1. Process one participant first.
2. Confirm events are found.
3. Confirm Excel files are created.
4. Review logs before running the full batch.

If the pilot file fails, use [Troubleshooting](troubleshooting.md) before processing the full dataset.
