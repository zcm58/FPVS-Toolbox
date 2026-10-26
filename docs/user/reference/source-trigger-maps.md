# Combining studies with different trigger codes

Use **source trigger maps** when the same analyzed condition was recorded with
different marker codes across studies or recordings. Toolbox keeps the raw files
unchanged and saves how each recording's markers correspond to the shared
conditions.

For example, Neutral Angry might start at code 11 in an adolescent study and
code 12 in an adult study. Both can produce a **Neutral Angry** output in one
two-group project. The project still uses one presentation rate, oddball rate
and analyzed duration.

## Keep participants distinct

Register one raw folder for each group. When separate studies reused participant
labels, retain a source-study namespace and the original ID, then review a unique
project ID before saving registration. **ACRP1** and **MCCTRP1** can both retain
original ID **P1** without becoming the same participant. Their filenames may
remain `p1.bdf` in separate group folders.

Existing project IDs stay fixed. Group membership, a matching filename, or a
matching original ID does not establish that two recordings belong to the same
person. Repeated visits to one participant use the repeated-session workflow;
source study is not a session.

When new files appear in a combined project's raw folders, processing opens a
registration review before discovery. Review each new participant's source study,
original ID, unique project ID and trigger map. Existing registered identities
stay read-only. New participants can be added after processing has locked the
groups; their identity and map assignments are saved together.

## Configure the source maps

1. Confirm the shared rate and duration in **Settings > Protocol**. Save any
   pending Settings edits before opening the editor from Home.
2. Choose **Use source maps…** in the Home Conditions area or Protocol settings.
   An existing shared map becomes a draft source map. Previously saved differences
   in recording oddball codes become separate maps so their interpretation is
   preserved.
3. In **Condition maps**, add the shared analyzed conditions and a source map for
   each marker convention. Select each map and enter its **Onset marker** and
   **Oddball marker** for every condition. The condition ID stays stable when its
   display label changes.
4. Under **Recognized source conditions not analyzed**, enter other known condition
   onset codes from that source. These preserve block boundaries even when those
   conditions are outside the comparison. Optional source labels help identify
   them. Unknown observed codes are not automatically added as boundaries.
5. In **Assignments**, assign each registered recording to its source map.
   Multiple selected rows can receive the same map. Every recording needs an
   assignment, including recordings currently excluded from processing.
6. Check **Review**, then choose **Save trigger maps**. When opened from Settings,
   choose **Apply to Settings**, then use the outer **Save** to commit the draft.

An empty marker cell blocks saving. Every selected condition must exist in every
source map; a blank cell does not mean zero response or an excluded observation.
Codes must be distinct for selected conditions within a source, and onset codes
cannot also be oddball codes. Different sources may reuse the same numbers.

Group defaults only propose maps for future recordings. Changing a default or a
group does not change a recording's saved map. Review explicit assignments when
adding recordings. The source study and the trigger map are separate: recordings
from one study may use more than one trigger convention.

## Reprocessing and analysis

Saving a scientific map, condition-label or assignment change requires processing
again before using earlier results. Saving does not start processing or delete
outputs. Renaming a source map or changing a future-registration default does not
invalidate current results.

Renaming a condition keeps its participant- and recording-level exclusions with
the same condition ID. Old output folders remain on disk but are omitted from
mapped-project discovery. A condition with saved exclusions cannot be deleted or
replaced by a different ID until those exclusions are explicitly cleared in a
separate save. Resolve or retire accepted condition-electrode repair requests
before renaming their condition; their review evidence is not transferred.

Use the current Toolbox version when reopening a mapped project. Older versions
reject its protocol version. Ordinary editing does not switch a source-mapped
project back to a shared trigger map; assign one source map to every recording
when all recordings should use the same convention.

After processing and required validity checks finish, standard group tools use the
canonical project participants and shared condition outputs. FHC and Summed BCA
retain their existing methods. The beta LORETA source-PSD input adapter currently
requires a shared condition-onset map and cannot use source-mapped projects.

Matching labels and trigger interpretation does not establish identical
experiments. Document differences in acquisition, repetitions, stimuli and
recruitment when comparing source studies, especially when source study and
experimental group coincide.
