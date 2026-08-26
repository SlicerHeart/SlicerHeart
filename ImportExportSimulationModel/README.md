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
| 6-component symmetric tensor (VTK order `xx, yy, zz, xy, yz, xz`) | `yz` and `xz` components negated |
| 9-component tensor (row-major) | `xz`, `yz`, `zx`, `zy` components negated |
| Single tensor component in its own 1-component array (`Stress_xz`, `Strain_yz`, `sigma_xz`, `StressXZ`) | negated if that component is negated |
| Invariants and other scalars (pressure, `VonMisesStress`, `VonMisesStrain`, `PrincipalStress_1`, `PrincipalStrain_1`, `Jacobian`, ...) | unchanged |
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

Reading: `.vtu`, `.vtp`, `.vtk`, `.stl`, `.ply`, `.obj`. A model is loaded as a surface mesh
(`vtkPolyData`) or as a volumetric mesh (`vtkUnstructuredGrid`), whichever the file contains.

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
