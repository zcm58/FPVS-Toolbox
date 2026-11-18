# Design

The canonical OpenFPVS desktop experience spec is maintained in the private
OpenFPVS repository. From the Toolbox repository root, maintainers can find it
at `../OpenFPVS/DESKTOP_EXPERIENCE.md` in a sibling checkout.

Design for lab members doing routine work. Give new members guidance at the
point of need and keep detailed controls and evidence available to experts.
FPVS Studio is the visual and interaction reference. When a Toolbox surface
changes, use the corresponding Studio pattern where it fits the processing
task. Preserve current workflows and behavior unless the task explicitly
changes them. The [product scope](../product-specs/fpvs-toolbox.md) and
[GUI architecture](../architecture/gui.md) document the local contracts.

[Frontend](FRONTEND.md) maps these decisions to Toolbox theme and component
owners. The private umbrella's `INTEGRATION_PLAN.md` owns cross-app direction
and acceptance. Its `PROJECT_REPORTING.md` owns sharing and approved access.
Toolbox owns its import, offline processing and scientific output contracts.
