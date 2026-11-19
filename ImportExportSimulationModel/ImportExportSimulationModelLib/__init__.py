"""Implementation of the ImportExportSimulationModel module.

The files are in layers, a file only uses the files of the layers before it:

- Data: Units, MeshArrays
- Operations on meshes, without the scene: OperationMonitor, MeshConversion, MeshReduction,
  MeshReading, MeshWriting
- Scene: ModelImport (export is in the logic of the module)
- User interface: WidgetUtils, ArrayInfoTable
"""
