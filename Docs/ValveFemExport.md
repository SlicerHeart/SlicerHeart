# Valve FEM Export

Export heart valve leaflet surfaces and chordae tendineae as a finite element method (FEM) model, for simulation of valve closure in [FEBio](https://febio.org/).

The module takes the results of valve segmentation and quantification (leaflet surfaces, annulus contour, papillary muscle tips) and produces a simulation-ready model:

- A smooth NURBS leaflet surface fitted to the segmented leaflet, meshed at a user-specified resolution.
- Chordae tendineae generated between the papillary muscle tips and the leaflet, with a realistic branching structure: fan branching for the chords that attach at the leaflet free edge and radial branching for the chords that attach on the leaflet body.
- Surface meshes, chord line sets, and a chord endpoint table written to a folder in file formats that FEBio can import.

## Prerequisites

- A segmented heart valve, prepared with the usual SlicerHeart workflow: `Valve Annulus Analysis` (heart valve node and annulus contour), `Valve Segmentation`, and `Leaflet Analysis` (leaflet surface models).
- For the branching chordae workflow, a NURBS surface fitted to the leaflet, stored in a grid surface markups node. This node type is provided by the [SurfaceMarkup extension](https://github.com/SlicerHeart/SlicerSurfaceMarkup). Note that chord generation cannot run without it: if `Create chords` is enabled and no `Leaflet NURBS surface` is selected, `Generate FEM model` fails with "Invalid leaflet NURBS grid surface node". To export leaflet and annulus geometry only, disable `Create chords`.

## How to use

### Set up inputs

- Load a scene that contains a segmented heart valve (see the Valve Annulus Analysis, Valve Segmentation, and Leaflet Analysis modules).
- In the `Import valve model` section, select the `Heart valve` node and click `Import`. This populates the annulus contour model and curve, and the leaflet models and boundaries, from the selected valve.
- In the `Common inputs` section, create a `Papillary muscle tips` point list and place one point on each papillary muscle tip in the slice views. Chords will start from these points.
- Select the `Output folder` where the generated model files will be written.

### Configure the leaflet surface

In the `Advanced output options` section:

- `Create leaflet surface shell model`: enable it to extract a shell from the leaflet model using the leaflet boundary. Keep it disabled (the default) if the input is already a shell surface.
- `Leaflet surface NURBS resolution`: number of NURBS control points across the leaflet. Higher values follow the segmented surface more closely, lower values give a smoother surface.
- `Leaflet surface mesh resolution`: approximate number of triangles across the leaflet in the exported mesh.
- `Create chords`: disable it to export leaflet and annulus geometry only.

### Define chord bundles

Chords can be generated in two ways, which can be combined.

**From leaflet margin and secondary curves** (`Leaflet inputs` section, up to three leaflets): for each leaflet, select the `Leaflet model` and draw a `Margin curve` along the leaflet margin and a `Secondary curve` somewhat farther from the margin. A primary chord bundle is generated to the margin curve and a secondary bundle to the secondary curve. The same margin curve can be shared between leaflets.

**From leaflet regions on the NURBS surface** (`Chord bundle inputs` section): this is the approach used for the branching chordae structure.

- Select the `Leaflet NURBS surface` grid surface node.
- Click `Add new` to create a `Leaflet region boundary` line and place it across the leaflet so that it divides the surface into regions. Each region is bounded by two such lines and corresponds to a parametric rectangle of the NURBS surface. Use `Delete` to remove a region boundary.
- For each region, select the `Papillary muscle tip` that its chords originate from and set the chord density.
- `Edge branches` control the chords that attach along the leaflet free edge: `Chord density` (chords/cm along the edge), branch `Length`, number of branches in the fan (`# fan`), and the fan `Radius`.
- `Body branches` control the chords that attach on the leaflet body: `Chord density` (chords/cm2), branch `Length`, number of radial branches (`# radial`), and the branch `Radius`.
- Chord endpoints are snapped to the leaflet surface. By default, they are snapped to a densely interpolated version of the NURBS surface, so that endpoints are not restricted to the coarse control point grid.

### Generate and export

- Click `Generate FEM model`. The generated leaflet surfaces, annulus, and chords appear in a `FEM-model` folder in the subject hierarchy, so they can be reviewed and, if needed, regenerated with adjusted parameters.
- Click `Write FEM model to output folder`. Leaflet surfaces, annulus, and chords are all written as `.vtk` model files in the LPS coordinate system. Each chord bundle is written as a line mesh, for spring import into FEBio. Markups nodes (curves, region boundaries, papillary muscle tip points) are not written; they are inputs, not results.

## References

Matthew A. Jolley (Corresponding Author), Nicolas R. Mangine, Devin W. Laurence, Patricia M. Sabin, Wensi Wu, Christian Herz, Christopher N. Zelonis, Justin S. Unger, Csaba Pinter, Andras Lasso, Steve A. Maas, Jeffrey A. Weiss, "Effect of Parametric Variation of Chordae Tendineae Structure on Simulated Atrioventricular Valve Closure", Annals of Biomedical Engineering (In Press).
