import vtk, slicer
from slicer.util import VTKObservationMixin
import numpy as np
import qt

class PositionerAngleViewWidget(VTKObservationMixin):

  def __init__(self, viewNode, cameraNode):
    super().__init__()

    autoUpdateDelaySec = 0.1
    self._delayedUpdateTimer = qt.QTimer()
    self._delayedUpdateTimer.setSingleShot(True)
    self._delayedUpdateTimer.interval = autoUpdateDelaySec * 1000
    self._delayedUpdateTimer.connect("timeout()", self.updateFromCameraNode)

    self.cornerAnnotationColor = [1,1,0] # yellow
    self.cornerAnnotationFontSize = 24
    self.cornerAnnotationActor = vtk.vtkCornerAnnotation()
    self.cornerAnnotationActor.PickableOff()
    self.cornerAnnotationActor.DragableOff()
    self.cornerAnnotationActor.SetMinimumFontSize(self.cornerAnnotationFontSize)
    self.cornerAnnotationActor.SetMaximumFontSize(self.cornerAnnotationFontSize)
    self.cornerAnnotationActor.SetNonlinearFontScaleFactor(1.0)
    self.cornerAnnotationActor.GetTextProperty().SetColor(self.cornerAnnotationColor)
    self.cornerAnnotationActor.GetTextProperty().SetShadow(True)
    self.cornerAnnotationActor.GetTextProperty().SetFontFamilyToArial()

    self.viewNode = None
    self.cameraNode = None
    self.setViewNode(viewNode)
    self.setCameraNode(cameraNode)

  def __del__(self):
    super().__del__()
    self.viewNode = None
    self.cameraNode = None
    self.removeObservers()

  def setCameraNode(self, cameraNode):
    # Remove old camera node observers
    self.removeObservers(self.cameraNode)
    self.cameraNode = cameraNode
    self.addObserver(self.cameraNode, vtk.vtkCommand.ModifiedEvent, self.onCameraNodeModified)
    self.onCameraNodeModified(self.cameraNode)

  def setViewNode(self, viewNode):
    oldViewNode = self.viewNode
    self.viewNode = viewNode
    layoutManager = slicer.app.layoutManager()
    oldView = None
    view = None

    for sliceViewName in layoutManager.sliceViewNames():
      currentView = layoutManager.sliceWidget(sliceViewName).sliceView()
      if self.viewNode == currentView.mrmlSliceNode():
        view = currentView
      if oldViewNode == currentView.mrmlSliceNode():
        oldView = view
      if (not oldViewNode or oldView) and view:
        break

    if oldView:
      oldRenderer = oldView.renderWindow().GetRenderers().GetFirstRenderer()
      oldRenderer.RemoveActor(self.cornerAnnotationActor)
    if view:
      renderer = view.renderWindow().GetRenderers().GetFirstRenderer()
      renderer.AddActor(self.cornerAnnotationActor)

  def onCameraNodeModified(self, cameraNode, event=None):
    """
    Called whenever one of the camera nodes is modified.
    Events are compressed to avoid frequent updates (text rendering is slow).
    """
    self._delayedUpdateTimer.start()

  def updateFromCameraNode(self):
    view = None
    layoutManager = slicer.app.layoutManager()

    # Get widget from view node

    # 3D view
    for threeDViewIndex in range(layoutManager.threeDViewCount):
      currentView = layoutManager.threeDWidget(threeDViewIndex).threeDView()
      if self.viewNode == currentView.mrmlViewNode():
        view = currentView
        break

    if not view:
      # Slice view
      for sliceViewName in layoutManager.sliceViewNames():
        currentView = layoutManager.sliceWidget(sliceViewName).sliceView()
        if self.viewNode == currentView.mrmlSliceNode():
          view = currentView
          break

    if not view:
      return

    viewNormal = np.array(self.cameraNode.GetCamera().GetDirectionOfProjection())
    viewNormal *= -1.0
    self.updatePositionerAngle(viewNormal, view)

  def updatePositionerAngle(self, vector, view):
    positionerAngleText = self.formatPositionerAngle(self.positionerAngleFromViewNormal(vector))
    self.cornerAnnotationActor.SetText(vtk.vtkCornerAnnotation.UpperRight, positionerAngleText)
    view.scheduleRender()

  @staticmethod
  def positionerAngleFromViewNormal(viewNormal):
    """
    Get the RAO/LAO and CRA/CAU angles.
    """
    # According to https://www5.informatik.uni-erlangen.de/Forschung/Publikationen/2014/Koch14-OVA.pdf
    nx = viewNormal[0]  # R
    ny = viewNormal[1]  # A
    nz = viewNormal[2]  # S
    import math
    if abs(ny) > 1e-6:
      primaryAngleDeg = math.atan2(nx, -ny) * 180.0 / math.pi
    elif nx >= 0:
      primaryAngleDeg = 90.0
    else:
      primaryAngleDeg = -90.0
    secondaryAngleDeg = math.asin(nz) * 180.0 / math.pi
    return [primaryAngleDeg, secondaryAngleDeg]

  @staticmethod
  def formatPositionerAngle(positionerAngles):
    """
    Format the positioner angle string for corner annotation display.
    """
    primaryAngleDeg, secondaryAngleDeg = positionerAngles
    text =  f'{"RAO" if primaryAngleDeg < 0 else "LAO"} {abs(primaryAngleDeg):.1f}\n'
    text += f'{"CRA" if secondaryAngleDeg < 0 else "CAU"} {abs(secondaryAngleDeg):.1f}'
    return text
