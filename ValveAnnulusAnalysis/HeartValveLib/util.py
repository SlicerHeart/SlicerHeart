#
#   Utility methods for interfacing with Slicer
# 

def createPolyDataFromPointArray(pointArray):
  """Create vtkPolyData from a numpy array. Performs deep copy."""

  from __main__ import vtk
  number_of_points = pointArray.shape[0]
  # Points
  points = vtk.vtkPoints()
  points.SetNumberOfPoints(number_of_points)
  import vtk.util.numpy_support
  pointArrayDestination = vtk.util.numpy_support.vtk_to_numpy(points.GetData())
  pointArrayDestination[:] = pointArray[:]
  # Vertices
  vertices = vtk.vtkCellArray()
  for i in range(number_of_points):
    vertices.InsertNextCell(1)
    vertices.InsertCellPoint(i)
  # PolyData
  polyData = vtk.vtkPolyData()
  polyData.SetPoints(points)
  polyData.SetVerts(vertices)
  return polyData

def getPointArrayFromPolyData(polyData):
  """Return point coordinates of a vtkPolyData object as a numpy array. Performs shallow copy."""

  import vtk.util.numpy_support
  pointArray = vtk.util.numpy_support.vtk_to_numpy(polyData.GetPoints().GetData())
  return pointArray
  
def createPointModelFromPointArray(pointArray, visible = True, color = None):
  """Create and display a MRML model node from a numpy array
  that contains 3D point coordinates, by showing a vertex at each point."""

  from __main__ import slicer
  modelNode = slicer.modules.models.logic().AddModel(createPolyDataFromPointArray(pointArray))
  if color is not None:
    modelNode.GetDisplayNode().SetColor(color)
  modelNode.GetDisplayNode().SetVisibility(1 if visible else 0)
  return modelNode


def createTubeModelFromPointArray(pointArray, loop=True, visible=True, color=None, radius=None, name=None,
                                  keepGeneratorNodes=False):
  """Create and display a MRML model node from a numpy array
  that contains 3D point coordinates, by showing a tube model that connects all points."""

  from __main__ import slicer
  pointModelNode = createPointModelFromPointArray(pointArray, color)
  tubeModelNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelNode")
  tubeModelNode.CreateDefaultDisplayNodes()
  if color is not None:
    tubeModelNode.GetDisplayNode().SetColor(color)
  pointModelNode.GetDisplayNode().SetVisibility(0)
  tubeModelNode.GetDisplayNode().SetVisibility(1 if visible else 0)
  markupsToModelNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsToModelNode")
  if markupsToModelNode is None:
    raise AttributeError("MarkupsToModel extension was not found. Please install MarkupsToModel extension.")
  markupsToModelNode.SetModelType(markupsToModelNode.Curve)
  markupsToModelNode.SetTubeLoop(loop)
  if radius is not None:
    markupsToModelNode.SetTubeRadius(radius)
  markupsToModelNode.SetAndObserveOutputModelNodeID(tubeModelNode.GetID())
  markupsToModelNode.SetAndObserveInputNodeID(pointModelNode.GetID())
  if name is not None:
    tubeModelNode.SetName(slicer.mrmlScene.GetUniqueNameByString(name+" curve"))
    pointModelNode.SetName(slicer.mrmlScene.GetUniqueNameByString(name+" points"))
    markupsToModelNode.SetName(slicer.mrmlScene.GetUniqueNameByString(name+" generator"))
  if keepGeneratorNodes:
    return tubeModelNode, pointModelNode, markupsToModelNode
  else:
    slicer.mrmlScene.RemoveNode(markupsToModelNode)
    slicer.mrmlScene.RemoveNode(pointModelNode.GetDisplayNode())
    slicer.mrmlScene.RemoveNode(pointModelNode)
    return [tubeModelNode]
