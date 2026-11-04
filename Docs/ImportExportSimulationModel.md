# Import/export simulation model

Imports simulation meshes (surface or volumetric) into 3D Slicer and exports models from the
scene, converting between coordinate systems and unit systems.

Simulation software (svFSI/SimVascular, FEBio, ...) usually writes meshes in LPS coordinates and
in the CGS unit system, while Slicer works in RAS and in mm. This module makes the conversion
explicit: it lists every coordinate set and data array of the input files, shows the unit and the
scale factor that will be applied to each of them, and stores the units in the imported model so
that it can be exported to any unit system later.

Importing and exporting are separate tasks, so only one of the two sections is open at a time:
opening one closes the other. Closing a section does not open the other one. The section that
was left open is restored the next time the module is used.

## Import model

- **Input files**: drag and drop mesh files on the list, or add them with the *Add* button.
  Several files can be imported at once with the same settings. *Remove* removes the selected
  files, or all files if nothing is selected.
- **Coordinate system in file**: coordinate system of the input files (RAS or LPS). LPS is the
  default, because that is what most simulation software uses. Meshes are always imported into
  the scene in RAS.
- **Unit system in file**: unit system of the input files (CGS or mm-g-s). Meshes are always
  imported into the scene in mm-g-s, because Slicer works in mm.
- **Coordinates and data arrays**: the point coordinates and every point and cell array of the
  input files, with the number of components, the value range, the unit, and the factor that the
  values are multiplied by on import (*Scale to Slicer*). The unit is guessed from the array name
  and can be corrected before importing. If several files are imported at once then arrays with
  the same name are listed once, with the value range covering all the files.
- **Advanced / Merge duplicate points** (enabled by default): simulation results often store a
  separate copy of a point for each cell that uses it. Copies with the same position and exactly
  the same values in all point data arrays are merged, which can reduce the memory use several-fold
  without changing any value. Copies that differ in any value are kept separate, and the number of
  cells does not change. The status log shows the number of points before and after merging. Images
  are not affected.
- **Advanced / Decimate large meshes** (enabled by default): reduces the number of cells
  of tetrahedral meshes, unlike merging duplicate points this reduces the resolution of the data.
  Other types of meshes are not decimated, they only get their duplicate points merged.
  - **Decimate above**: only meshes with more cells than this are decimated (default: 1000000).
  - **Target reduction**: percentage of the cells to remove (default: 75%). The status log reports
    if the target cannot be reached, because most of the remaining cells are at the boundary.
  - **Boundary weight**: how strongly the shape of the outer boundary is preserved (default: 100).
    A lower value allows removing more cells, but the shape of the mesh may change.
- **Advanced / Resample uniformly** (disabled by default): replaces the cells of volumetric meshes
  with cubes aligned with the axes, see [Uniform resampling](#uniform-resampling). Decimation is not
  used for meshes that are resampled. Surface meshes and images are not resampled.
  - **Resolution**: size of the cubes, in mm (default: 1 mm).
- **Advanced / First time point index** (default: 0, which is the first time point in the file):
  time points of a VTKHDF file before this one are skipped, for example to load only the last
  cardiac cycle. An error is reported if the file does not have this many time points.
- **Advanced / Keep 1 of every N time points** (default: 1, which loads all time points): loads only
  the first of every N time points of a VTKHDF file, starting from the first time point index. For
  example, with an index of 0, the value 3 loads the time points 0, 3, 6, ... This counts time
  points, not time, so the loaded time points are not evenly spaced in time if the ones in the file
  are not. Time values are kept as they are in the file.

  If only one time point remains after applying these two options then it is loaded as a regular
  model, without a sequence, and its time is stored in the `SimulationModel.TimeValue` attribute.
- **Advanced / Approximate scalar ranges** (enabled by default): lists large VTKHDF files in the
  table without reading all of their data. Reading the data arrays takes most of the time, and the
  file does not store their ranges. For a file with more than 1 million cells and more than 8
  partitions, only the geometry and 8 evenly spaced partitions of the last time point are read. The
  range of the point coordinates remains exact. The ranges of data arrays are marked with `~` and can
  be much narrower than the true ranges, so disable this option to see the exact ranges. The ranges
  are only displayed, they do not affect the import. Other file formats are always read completely.

### Uniform resampling

The result is an unstructured grid of hexahedra on a regular grid, stored in a model node like any
other imported mesh. A cube is kept if its center is inside the mesh, so the boundary becomes a
staircase but the volume of the mesh is preserved. A structure thinner than the resolution may become
disconnected or disappear, and an error is reported if no cube is left. Grid points are at integer
multiples of the resolution in the coordinate system of the file, so all the time points of a
sequence use the same grid, even if the mesh moves.

Values are transferred the same way as for [decimation](#decimation): floating-point point arrays
are interpolated, the corners outside of the mesh get the value at the closest position of the mesh,
integer point arrays are taken from the nearest point, and cell arrays from the cell that contains the
center of the cube. Values at the staircase boundary, such as wall shear stress, are therefore not at
the true position of the wall.

### Decimation

Decimation collapses edges of the mesh using `vtkUnstructuredGridQuadricDecimation`. It only looks
at the geometry, not at the values of the data arrays, so it does not keep more cells where the
flow is complex. The values are then transferred to the result:

- Floating-point point arrays are interpolated from the original mesh at each new point. The rare
  point that falls slightly outside the original mesh is interpolated at the closest position of
  the closest original cell.
- Integer point arrays (identifiers, labels) get the value of the nearest original point, because
  interpolating them would give meaningless values.
- Cell arrays get the value of the original cell at the center of the new cell.

Quantities that change quickly over short distances lose the most accuracy, especially near walls.
Turn off decimation if the original resolution is needed, for example for measuring wall shear
stress. All the time points of a file that have the same geometry use the same decimated mesh, so
the decimation only runs once for them; a time point with a different geometry is decimated again.
Decimating millions of cells can take a few minutes.

### How the unit is guessed from the array name

The name is split into words, and a quantity is recognized if its name occurs as a **whole
word anywhere** in the array name. Any prefix and any suffix is therefore ignored, whatever the
simulation software puts around the quantity:

| Array name | Recognized as |
| --- | --- |
| `Stress`, `Stress_xx`, `Stress_yz`, `solid_Stress_1`, `mean_stress_xy` | stress (pressure) |
| `Strain_xz`, `PrincipalStrain_1`, `VonMisesStrain` | strain (dimensionless) |
| `Velocity`, `fluid_Velocity`, `average_speed` | velocity |
| `average_pressure`, `vinplane_traction` | pressure |

Camel case names are split into words too, so `VonMisesStress`, `WallShearStress`, and
`KinematicViscosity` are recognized, as are the same names written with underscores. Because
only whole words match, a word that merely happens to be a part of a longer one does not match:
`Acceleration` is an acceleration, not a `ratio`.

A name that matches no rule (`attribute`, `Q-Criterion`) is listed as dimensionless and left
unscaled, which is always safe; set its unit by hand in the table if it should be scaled.

## Export model

- **Models**: a subject hierarchy tree of the models in the scene. Select several with Ctrl or
  Shift; selecting a folder exports every model in it. The models that were just imported are
  selected automatically.
- **Coordinate system in file**, **Unit system in file**: what the written files should use.
  The factor applied to each array is shown in the *Scale from Slicer* column.
- **File format**: *VTK (XML)*, *VTK (classic)*, *PLY*, *OBJ*, or *STL*. The file extension is
  not chosen directly, because it depends on the mesh of each model (see below).
- **Output folder**: each selected model is written to a separate file in this folder, named
  after the model (characters that are not allowed in file names are replaced with `_`, and a
  number is appended if two models have the same name, so nothing is overwritten silently).

The units stored in each model at import time (see below) are used to compute the scale factor
for each array, shown in the table. If several models are selected, an array that occurs in more
than one of them is listed once, with the value range covering all of them. Arrays of a model
that has no stored unit information (for example, a model that was not imported with this
module) get their unit guessed from the array name.

## Conversion

**Coordinate system.** RAS and LPS differ by a 180-degree rotation about the third axis, which
negates the first two axes. Every array is rotated according to what it holds:

| Array | Conversion |
| --- | --- |
| Point coordinates, 3-component vectors (velocity, displacement, WSS, ...) | `x` and `y` components negated |
| 2-component vectors of 2D simulations, if the quantity is recognized from the name (`Velocity`, `Displacement`, ...) | `x` and `y` components negated |
| 6-component symmetric tensor (VTK order `xx, yy, zz, xy, yz, xz`) | `yz` and `xz` components negated |
| 9-component tensor (row-major) | `xz`, `yz`, `zx`, `zy` components negated |
| Single tensor component in its own 1-component array (`Stress_xz`, `Strain_yz`, `sigma_xz`, `StressXZ`) | negated if that component is negated |
| Invariants and other scalars (pressure, `VonMisesStress`, `VonMisesStrain`, `PrincipalStress_1`, `PrincipalStrain_1`, `Jacobian`, ...) | unchanged |
| `Q-Criterion`, whatever the number of its components (some solvers write this scalar in a 3-component array) | unchanged |
| Other 2-component arrays (texture coordinates, names that are not recognized, ...) | unchanged |
| Integer arrays (identifiers, labels, counts) | unchanged |

A tensor `T` transforms as `R*T*R'`, where `R` negates the first two axes; this negates exactly
the components that mix the third axis with one of the first two. Invariants such as von Mises
and principal values do not depend on the coordinate system, so they are left alone. The tooltip
of each array name in the table shows how that array is transformed, and the status log lists
every array that is scaled or negated.

Note that a vector stored as separate single-axis arrays (`Velocity_x`, `Velocity_y`, ...) is
**not** recognized; only tensor component names (two axis letters) are.

**Unit system.** The mass (g) and the time (s) unit are the same in the CGS and in the mm-g-s
system, only the length unit differs (1 cm = 10 mm). Therefore the conversion factor of a
quantity is determined by its *length exponent* alone: the power of the length unit in the
quantity.

| Quantity | Length exponent | CGS unit | mm-g-s unit | CGS -> mm-g-s |
| --- | --- | --- | --- | --- |
| Dimensionless, identifier | 0 | - | - | 1 |
| Length | 1 | cm | mm | 10 |
| Velocity | 1 | cm/s | mm/s | 10 |
| Acceleration | 1 | cm/s2 | mm/s2 | 10 |
| Area | 2 | cm2 | mm2 | 100 |
| Volume | 3 | cm3 | mm3 | 1000 |
| Flow rate | 3 | cm3/s | mm3/s | 1000 |
| Pressure, traction, WSS, stress | -1 | dyn/cm2 | g/(mm*s2) | 0.1 |
| Density | -3 | g/cm3 | g/mm3 | 0.001 |
| Dynamic viscosity | -1 | g/(cm*s) | g/(mm*s) | 0.1 |
| Kinematic viscosity | 2 | cm2/s | mm2/s | 100 |
| Force | 1 | dyn | g*mm/s2 | 10 |
| Resistance | -4 | dyn*s/cm5 | g/(mm4*s) | 0.0001 |
| Compliance | 4 | cm5/dyn | mm4*s2/g | 10000 |
| Mass | 0 | g | g | 1 |
| Time | 0 | s | s | 1 |
| Rate (frequency, vorticity, strain rate) | 0 | 1/s | 1/s | 1 |

## Stored unit information

The unit and the length exponent of the point coordinates and of every array are stored in the
imported model as node attributes, which are visible and editable in the Data module:

| Attribute | Example value |
| --- | --- |
| `SimulationModel.CoordinateSystem` | `RAS` |
| `SimulationModel.UnitSystem` | `mmgs` |
| `SimulationModel.SourceFile` | `C:/data/fluid.vtu` |
| `SimulationModel.TimeValue` (a single time point of a time series) | `4.685` |
| `SimulationModel.Position.Unit` | `mm` |
| `SimulationModel.Position.LengthExponent` | `1` |
| `SimulationModel.Position.Quantity` | `length` |
| `SimulationModel.PointArray.Velocity.Unit` | `mm/s` |
| `SimulationModel.PointArray.Velocity.LengthExponent` | `1` |
| `SimulationModel.PointArray.Pressure.Unit` | `g/(mm*s2)` |
| `SimulationModel.PointArray.Pressure.LengthExponent` | `-1` |
| `SimulationModel.CellArray.Density.Unit` | `g/mm3` |
| `SimulationModel.CellArray.Density.LengthExponent` | `-3` |

If an array has a unit that this module does not know (for example, because the attribute was set
by hand), the length exponent attribute is still used to convert the values.

## Supported file formats

Reading: `.vtu`, `.vtp`, `.vtk`, `.vtkhdf`, `.vtkhdf5`, `.vti`, `.stl`, `.ply`, `.obj`. A model is
loaded as a surface mesh (`vtkPolyData`) or as a volumetric mesh (`vtkUnstructuredGrid`), whichever
the file contains.

**VTKHDF files** (`.vtkhdf`, `.vtkhdf5`) may store several partitions and time points. Partitions
are appended into a single mesh without merging points, so point values stay as they are in the
file (duplicate points are then merged if that option is enabled, see above). A file with several
time points is split up: each time point is converted to RAS and mm-g-s
and stored in a sequence node, with the time in seconds as index, and a sequence browser node is
added to show it. The time points are all kept in memory, so make sure that there is enough for
the whole sequence. The value ranges in the arrays table are the ones of the last time point. The
quantities selected in the table apply to all time points. Exporting the proxy model of the
sequence writes the time point that is currently selected in the browser.

**Images** (`.vti`) are loaded as a volume node, one for each point data array (a scalar volume for
a 1-component array and a vector volume otherwise). The origin and spacing are scaled and the
coordinate system is converted the same way as the point coordinates of a mesh, so the image stays
aligned with meshes imported with the same settings. Voxel values are scaled according to the unit
selected in the table, which is dimensionless (not scaled) by default for names such as
`ImageScalars`. Cell data arrays of an image are not loaded, and images cannot be exported.

Writing: the format is selected by name, and the extension follows from the mesh of the model
being written, because the same format stores a surface mesh and a volumetric mesh in different
file types:

| Format | Surface mesh | Volumetric mesh | Data arrays |
| --- | --- | --- | --- |
| VTK (XML) | `.vtp` | `.vtu` | kept |
| VTK (classic) | `.vtk` | `.vtk` | kept |
| PLY | `.ply` | `.ply` | lost |
| OBJ | `.obj` | `.obj` | lost |
| STL | `.stl` | `.stl` | lost |

PLY, OBJ, and STL can only store a surface, so writing a volumetric mesh to them keeps only its
outer surface, and the data arrays are lost. Both cases are reported in the status log.
