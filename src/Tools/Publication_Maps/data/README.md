# Generic scalp display mesh

`neutral_head.npz` contains the outer surface used by the rotating scalp viewer
and its figure exporter. Its 13,432 vertices and 26,618 triangles give every
dataset the same anatomical landmarks. The file contains no EEG values,
participant geometry or source model.

The surface is derived from MakeHuman's neutral hm08 base mesh, released
under CC0 1.0 Universal by Data Collection AB, Joel Palmius and Jonas Hauquier
in 2020. The source OBJ's SHA-256 is
`8e761e6624b8f54536409135d1636da63b32486a90d4897f84e121d144f6fb4c`.
[Pinned base.obj](https://github.com/makehumancommunity/makehuman/blob/a8bc2d54ff0ac92e78ff71431b1023eda42bf482/makehuman/data/3dobjs/base.obj) ·
[MakeHuman asset license](https://github.com/makehumancommunity/makehuman/blob/a8bc2d54ff0ac92e78ff71431b1023eda42bf482/LICENSE.ASSETS.md)

## Geometry preparation

The derivative used NumPy 2.3.1, PyVista 0.46.5 and VTK 9.5.1. OBJ indices
below are zero-based. The landmark choices define a display coordinate frame.

1. Set the origin to the midpoint of the mirrored preauricular landmarks at
   vertex 5477 and its sagittal reflection. Define anterior by the unit vector
   from this origin to the nasion at vertex 132. Use source direction
   `(-1, 0, 0)` for participant right and the cross product of right and
   anterior for superior. Express points on those axes at 0.1 metre per
   source unit.
2. Take faces in the OBJ `body` group whose four source vertices have
   `y > 5.3`. Compact the vertex indices in sorted order, triangulate and
   apply one Loop subdivision. Clip the neck on the plane through source
   `(0, 6.16, 0.32)` with inward normal `(0, 1, 0.10)`. Preserve the
   superior surface and close its planar cut with the triangulated, reversed
   slice contour.
3. Place a neutral sphere of radius 0.0138 metre at the mean of the original
   unique vertices in each `joint-l-eye` and `joint-r-eye` group (24 azimuth
   and 18 polar subdivisions). Merge with the head. Clean at an absolute
   tolerance of 1e-8 metre, triangulate, and call `decimate_pro` with a
   target reduction of 0.25, topology preservation enabled and splitting
   disabled. Clean again with the same tolerance.
4. Snap rim vertices within 0.1 mm of the cut back onto its exact plane after
   decimation. Split the rim's shading normals by giving the closure its own copy
   of its vertices. The surface stays geometrically closed. Store vertex
   coordinates in metres as float32, triangle indices as uint16 and the
   inward-facing plane equation as float64. Both renderers leave the flat
   cut outside the field of electrode values.
