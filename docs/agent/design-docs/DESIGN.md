# Design

The canonical OpenFPVS desktop experience spec is maintained in the private
OpenFPVS repository. From the Toolbox repository root, maintainers can find it
at `../OpenFPVS/DESKTOP_EXPERIENCE.md` in a sibling checkout.
For release decisions, read [How to plan independent releases](https://github.com/zcm58/OpenFPVS-Website/blob/main/DESKTOP_EXPERIENCE.md#how-to-plan-independent-releases).

Design for lab members doing routine work. Give new members guidance at the
point of need and keep detailed controls and evidence available to experts.
Use FPVS Studio as the reference for layout and interaction. Apply the
OpenFPVS **Slate & Signal Teal** desktop palette through the existing Toolbox
theme. Preserve the scientific palettes used for data and publication figures.
When a Toolbox surface changes, match the Studio pattern where it fits the
processing task and preserve existing behavior unless explicitly revised.
The [product scope](../product-specs/fpvs-toolbox.md) and
[GUI architecture](../architecture/gui.md) document the local contracts.

Keep informational notices dismissible so the analyst can continue other
work. Block the affected action when its inputs are invalid, execution would
be unsafe, or continuing would likely lose work. Explain what needs attention.

[Frontend](FRONTEND.md) maps these decisions to Toolbox theme and component
owners. The private umbrella's `INTEGRATION_PLAN.md` owns cross-app direction
and acceptance. Its `PROJECT_REPORTING.md` owns sharing and approved access.
Toolbox owns its import, offline processing and scientific output contracts.
