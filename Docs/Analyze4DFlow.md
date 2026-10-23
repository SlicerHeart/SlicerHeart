# Analyze 4D Flow

Computes flow metrics in a measurement plane, streamlines or pathlines, speed images, and hemodynamic quantities from a
flow field: a vector volume or grid transform sequence created by [Import 4D Flow](Import4DFlow.md), a vector volume
sequence loaded from file, or a model sequence (for example, a CFD result).

## Units

- All computations are done in mm/s (velocity), mm2 (area), mm3/s (flow rate), mm3 (volume) and ms (time). The velocity
  of the input flow field is converted to mm/s when it is read:
  - vector volume: the unit in the voxel value units of the volume (`m/s`, `cm/s` or `mm/s`; stored in the `units` field
    of the NRRD file), or in the `SlicerHeart.velocityUnit` attribute of its sequence. Vector volumes without unit
    information are assumed to be in mm/s.
  - grid transform (legacy format of flow fields created by earlier versions of Import 4D Flow): m/s.
  - model: the unit in the `SimulationModel.PointArray.<velocity array name>.Unit` model node attribute, which is set
    when the model is loaded by the [Import/Export Simulation Model](ImportExportSimulationModel.md) module (`m/s`,
    `cm/s` or `mm/s`). Models without this attribute are assumed to be in mm/s.
- Outputs that store velocities (speed volume, masked flow field, `Speed` point data of the flow metrics model,
  streamlines and pathlines) are in mm/s; the unit is set in the voxel value units of output volumes. A masked flow field
  stored in a grid transform is in m/s (legacy format).
- Tables, plots and the module GUI show values in display units: velocity in cm/s (including `Speed threshold`),
  flow rate in ml/s, volume in ml, area in mm2, time in ms, volume per minute in l/min, pressure in mmHg.

## Methods

Methods marked *(slicerheart_4dflow)* are implemented in the
[slicerheart_4dflow](https://github.com/JolleyLab/slicerheart_4dflow) Python package (see
[Import 4D Flow](Import4DFlow.md#corrections)) and are only available for image flow fields:

- `Flow metrics` / `Method`:
  - `plane probe`: velocity is sampled on the plane.
  - `disc sampling (slicerheart_4dflow)`: velocity is sampled on a disc whose radius is half of the smaller plane size,
    with mask-normalized interpolation, so velocity outside the lumen does not leak in.

  Both methods fill the same tables.
- `Streamlines` / `Method`:
  - `streamlines`: instantaneous streamlines in each frame.
  - `pathlines (slicerheart_4dflow)`: time-resolved particle paths, emitted from the measurement plane in every frame and
    traced for one cardiac cycle (using the heart rate).
- `Hemodynamics` *(slicerheart_4dflow)*: requires the lumen as `Mask`. Computed by `Compute hemodynamics`:
  - volume sequences of vorticity magnitude, relative helicity, kinetic energy density and viscous energy loss
  - a table of the per-frame lumen totals: kinetic energy, energy loss rate, mean vorticity
  - a wall shear stress model (WSS of each frame, TAWSS, OSI) on the lumen surface
  - relative pressure (mmHg), and the pressure drop between the measurement plane and a second plane

  Blood density and viscosity can be adjusted. A divergence-free filtered flow field is recommended.
- `Mass conservation` *(slicerheart_4dflow)*: compares the net flow volume per heart beat of the selected inflow and
  outflow flow metrics tables.

## How to use

### Compute flow metrics in a plane

- Create a plane using the Markups module that specifies where samples will be taken, and select it as `Measurement plane`.
- Select output nodes in the `Flow metrics` section: `Output model` (plane points with the velocity values), `Output table`
  (metrics of each frame) and `Output summary table`.
- Optionally set a mask segment: all velocity values outside the mask will be set to zero.
  - The segmentation can be created using the Segment Editor module:
    - Segment the magnitude image using the Threshold effect, or use the lumen computed by Import 4D Flow.
    - Use the Scissors effect to cut off other vessels. If the vessel region is isolated from the others then the Islands
      effect's `Keep selected island` method can be used to remove everything else.
  - The segmentation can vary in time to follow a moving vessel. A time-varying segmentation can be created by the
    following steps:
    - Segment one time point near the middle of the sequence.
    - Use the Sequence Registration extension to compute the warping transform for all time points. Select
      `Output transform sequence`, and in the `Advanced` section set `Fixed frame index` to the frame that was segmented
      and `Transform direction` to `fixed frame to moving frames`.
    - Apply the computed transform sequence to the segmentation.
- Optionally adjust parameters:
  - `Sampling distance`: for very small cross-sections, reduce the sampling distance to get a representative number of
    samples.
  - `Speed threshold` (cm/s): if no mask segment is set then sample points where the speed is below this threshold are
    excluded from the flow metrics computation (they are considered to be outside the vessel). If all the sample points
    are below the threshold then the area, flow rate and velocity values are 0 - in this case lower the
    `Speed threshold` value (for example, to 10 cm/s).
  - `Heart rate`: needed for the summary metrics (for example, volume per minute). Set it from the DICOM header
    (`Set from DICOM`) or from the acquisition length (`Set from length`).
- Click `Analyze`.
- Click `Show plot` to display the flow metrics over time.

### Generate streamlines

- Create a plane using the Markups module that specifies where streamlines are started, and select it as
  `Measurement plane`.
- Optionally set a mask segment (see above).
- Select or create a model node for `Output streamlines`.
- Optionally adjust parameters:
  - `Sampling distance`: reduce the value to generate more seed points for streamlines.
  - `Speed threshold` (cm/s): if speed falls below this threshold the streamline is terminated.
  - `Maximum length`: maximum length of a streamline.
  - `Bidirectional`: enable to trace streamlines in the reverse flow direction as well.
  - `Compute all metrics`: enable to compute all possible streamline point data (velocity vector, vorticity, rotation,
    angular velocity, etc.), at the cost of using about 4x more storage space in memory and files.
- Click `Analyze`.
- Optional: set up transparent volume rendering of the magnitude image:
  - Go to the Volume Rendering module, select the magnitude image, click the eye icon to show volume rendering.
  - Select the US-Silver preset.
  - Scalar opacity mapping: ramp function, O=0 for X<146; O=1 for X>187 and beyond.
  - Gradient opacity: ramp function, O=0 for X<65, O=1 for X=160.
  - Enable `Surface smoothing` in the `Techniques` section.
  - If these settings don't work, go to the advanced section under gradient opacity and bring the ambient light up to 1,
    then move the gradient opacity points to the left until you see the rendering (you may need to add another point).
  - To reduce background noise, use the Gradient Anisotropic Diffusion module: adjust the conductance and iterations,
    choose a new output volume, and apply.

### Generate image overlay colored by speed

- Select or create a volume node for `Output speed image`.
- To create a Doppler-like visualization with color depending on flow direction:
  - Create a plane using the Markups module and select it as `Measurement plane`.
  - Check `Project to measurement plane`.
- Optionally set a mask segment (see above).
- Optionally adjust parameters:
  - `Speed threshold` (cm/s): areas where the speed is below this threshold will not be highlighted with color.
- Click `Analyze`.
- Choose the speed volume as foreground layer in slice views.
- Optional: set up volume rendering of the speed image.

### Get the velocity values and positions on a plane as numpy arrays

After `Analyze`, the flow metrics model (`Output model` in the `Flow metrics` section) contains the sample points of the
plane and the velocity vectors (mm/s) in the `Speed` point data array. Type this in the Python console in Slicer:

```python
flowMetricsModelNode = slicer.util.getModuleLogic("Analyze4DFlow").getParameterNode().outputFlowMetricsModel
velocities = arrayFromModelPointData(flowMetricsModelNode, "Speed")  # mm/s, RAS
positions = arrayFromModelPoints(flowMetricsModelNode)  # mm, RAS
```
