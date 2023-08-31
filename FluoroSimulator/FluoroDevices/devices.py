import vtk
import os
import math
import slicer
import logging
import numpy as np
from CardiacDeviceSimulatorUtils.devices import CardiacDeviceBase

#
# ValveClipBase abstract device class
#
class FluoroDeviceBase(CardiacDeviceBase):

  NAME = "GenericValveClip"
  ID = "GenericValveClip"
  RESOURCES_PATH = os.path.join(os.path.dirname(__file__), "..",  "Resources")

  PARAMETER_NODE = None

  MODEL_CACHE = {}  # shared cache of polydata that is rendered to show the device in 3D

  # Models are from Canon Alphenix biplane system (https://www.youtube.com/watch?v=GWQmyhBFUBI)
  # purchased from https://www.turbosquid.com/3d-models/angiography-x-ray-obj/539501

  # Innova 3100 (3131 biplane):
  # Frontal gantry:
  # - L arm: +/- 100 deg
  # - C arm: -117 .. 105 deg (RAO/LAO)
  # - P arm: -45 .. 50 deg (CAU/CRA)
  # - SID: 890 .. 1190 mm
  # - SOD: 720 mm
  # - Isocenter to floor: 1070 mm
  # Lateral gantry:
  # - L arm: +/- 100 deg
  # - C arm: 2 .. 115 deg LAO
  # - P arm: -90 .. 45 deg (CAU/CRA)
  # - SID: 840 .. 1370 mm
  # - SOD: 710 .. 880 mmm
  # Table:
  # - Tabletop length: 3330 mm
  # - Tabletop 460 mm in patient trunk Area, 670 mm maximum
  # - Table longitudinal travel: 1700 mm
  # - Table transverse travel: +/- 140 mm
  # - Table vertical travel: 780 mm to 1080 mm
  # - Table rotation: +/- 180 deg

  @classmethod
  def getFrontalGantryParameters(cls, displayFrontalPrefix=False):
    prefix = "Frontal - " if displayFrontalPrefix else ""
    return {
      "frontalArmAngleL": cls._genParameters(f"{prefix}L-arm angle:", "Positive = counterclockwise", 0, "deg", -90, 90, 1.0, 1),
      "frontalArmAngleP": cls._genParameters(f"{prefix}P-arm angle:", "Positive = clockwise", 0, "deg", -180, 180, 1.0, 1),
      "frontalArmAngleC": cls._genParameters(f"{prefix}C-arm angle:", "Positive = detector moves away from the arm", 0, "deg", -180, 180, 1.0, 1),
      "frontalSourceToObjectDistance": cls._genParameters(f"{prefix}SOD:", "Source to object distance (between the generator and the isocenter)", 720, "mm", 600, 800, 5.0, 1, visible=False),
      "frontalSourceToImageDistance": cls._genParameters(f"{prefix}SID:", "Source to image distance (between the generator and detector)", 940, "mm", 800, 1200, 5.0, 1),
    }

  @classmethod
  def getLateralGantryParameters(cls):
    return {
      "lateralArmAngleP": cls._genParameters("Lateral - P-arm angle:", "Positive = clockwise", 0, "deg", -180, 180, 1.0, 1),
      "lateralArmAngleC": cls._genParameters("Lateral - C-arm angle:", "Positive = clockwise", 0, "deg", -180, 180, 1.0, 1),
      "lateralArmOffset": cls._genParameters("Lateral - Shift:", "Negative = cranial, positive is caudal angle", 0, "mm", -500, 2000, 1.0, 1),
      "lateralSourceToObjectDistance": cls._genParameters("Lateral - SOD:", "Source to object distance (between the generator and the isocenter)", 720, "mm", 600, 800, 5.0, 1, visible=False),
      "lateralSourceToImageDistance": cls._genParameters("Lateral - SID:", "Source to image distance (between the generator and detector)", 1100, "mm", 800, 1400, 5.0, 1)
    }

  @classmethod
  def getTableParameters(cls):
    return {
      "tableShiftLateral": cls._genParameters("Table transverse:", "Table pan in supine patient's left/right direction, positive = left", 0, "mm", -80, 80, 5.0, 1),
      "tableShiftLongitudinal": cls._genParameters("Table longitudinal:", "Table pan in supine patient's superior/inferior direction, positive = inferior", 0, "mm", -1000, 500, 5.0, 1),
      "tableShiftVertical": cls._genParameters("Table height:", "Table raise, zero = tabletop at isocenter, positive = higher", -30, "mm", -120, 10, 5.0, 1),
    }

  @classmethod
  def setupDeviceModel(cls):
    """
    Setup device model including guide, sleeve, catheter.
    """
    parameterNode = cls.PARAMETER_NODE
    if not parameterNode:
      return
    if parameterNode.GetParameter('DeviceClassId') in [None, '']:
      logging.error('setupDeviceModel: Device type not defined')
      return

    # Get parameters
    parameterValues = cls.getParameterValuesFromNode(parameterNode)

    # Create all transforms (if not created already)
    positioningTransform = parameterNode.GetNodeReference('PositioningTransform')
    shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    transformationFolderShItem = shNode.GetItemByDataNode(positioningTransform)
    transforms = [ # node reference, parent node reference, biplane only
      ("frontal-arm-l-rotation-transform", "PositioningTransform", False),
      ("frontal-arm-p-rotation-transform", "frontal-arm-l-rotation-transform", False),
      ("frontal-arm-c-rotation-transform", "frontal-arm-p-rotation-transform", False),
      ("frontal-arm-detector-translation-transform", "frontal-arm-c-rotation-transform", False),
      ("lateral-arm-offset-transform", "PositioningTransform", True),
      ("lateral-arm-p-rotation-transform", "lateral-arm-offset-transform", True),
      ("lateral-arm-c-rotation-transform", "lateral-arm-p-rotation-transform", True),
      ("lateral-arm-detector-translation-transform", "lateral-arm-c-rotation-transform", True),
      ("table-vertical-transform", "PositioningTransform", False),
      ("table-lateral-transform", "table-vertical-transform", False),
      ("table-longitudinal-transform", "table-lateral-transform", False),
    ]
    for transformNodeRef, parentTransformNodeRef, forBiplaneOnly in transforms:
      transformNode = parameterNode.GetNodeReference(transformNodeRef)
      toRemove = (forBiplaneOnly and not cls.BIPLANE)
      if toRemove:
        if transformNode:
          slicer.mrmlScene.RemoveNode(transformNode)
        continue
      # Transform is needed
      if transformNode:
        # Transform is already added
        continue
      # Need to add the transform now
      transformNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLinearTransformNode", transformNodeRef)
      parameterNode.SetNodeReferenceID(transformNodeRef, transformNode.GetID())
      transformNode.SetAndObserveTransformNodeID(parameterNode.GetNodeReferenceID(parentTransformNodeRef))
      shNode.SetItemParent(shNode.GetItemByDataNode(transformNode), transformationFolderShItem)

    # Create subject hierarchy folder for C-arm model (if does not exist already)
    parameterNodeShItem = shNode.GetItemByDataNode(parameterNode)
    carmFolderShItem = shNode.GetItemChildWithName(parameterNodeShItem, "C-arm")
    if not carmFolderShItem:
      carmFolderShItem = shNode.CreateFolderItem(parameterNodeShItem, "C-arm")
      shNode.SetItemExpanded(carmFolderShItem, False)

    # Load all models from files (if not loaded already)
    models = [ # model and file name, parent transform name, forBiplaneOnly
      ("frontal-arm-l",    "frontal-arm-l-rotation-transform", False),
      ("frontal-arm-p",    "frontal-arm-p-rotation-transform", False),
      ("frontal-arm-c",    "frontal-arm-c-rotation-transform", False),
      ("frontal-detector", "frontal-arm-detector-translation-transform", False),
      ("lateral-arm-p",    "lateral-arm-p-rotation-transform", True),
      ("lateral-arm-c",    "lateral-arm-c-rotation-transform", True),
      ("lateral-detector", "lateral-arm-detector-translation-transform", True),
      ("table-base",       "PositioningTransform", False),
      ("table-middle",     "table-lateral-transform", False),
      ("table-top",        "table-longitudinal-transform", False),
      ]
    for modelNodeRef, parentTransformNodeRef, forBiplaneOnly in models:
      modelNode = parameterNode.GetNodeReference(modelNodeRef)
      toRemove = (forBiplaneOnly and not cls.BIPLANE)
      if toRemove:
        if modelNode:
          slicer.mrmlScene.RemoveNode(modelNode)
        continue
      # Model is needed
      if modelNode:
        # Model is already added
        continue
      # Need to add the model now
      if modelNodeRef not in cls.MODEL_CACHE:
        # Model has not been read from file yet, read it now
        reader = vtk.vtkPLYReader()
        reader.SetFileName(os.path.join(cls.RESOURCES_PATH, "Models", modelNodeRef+".ply"))
        reader.Update()
        model_RAS = vtk.vtkPolyData()

        # models are stores in files as LPS, but we need in the scene as RAS
        # TODO: use this single line instead of the several lines below when
        # the ConvertBetweenRASAndLPS method is exposed in Slicer core:
        #   slicer.vtkMRMLModelStorageNode.ConvertBetweenRASAndLPS(reader.GetOutput(), model_RAS)
        transformRasLps = vtk.vtkTransform()
        transformRasLps.Scale(-1, -1, 1)
        transformFilter = vtk.vtkTransformPolyDataFilter()
        transformFilter.SetTransform(transformRasLps)
        transformFilter.SetInputData(reader.GetOutput())
        transformFilter.Update()
        model_RAS = transformFilter.GetOutput()

        cls.MODEL_CACHE[modelNodeRef] = model_RAS
      modelNode = slicer.modules.models.logic().AddModel(cls.MODEL_CACHE[modelNodeRef])
      modelNode.SetName(modelNodeRef)
      parameterNode.SetNodeReferenceID(modelNodeRef, modelNode.GetID())
      modelNode.SetAndObserveTransformNodeID(parameterNode.GetNodeReferenceID(parentTransformNodeRef))
      shNode.SetItemParent(shNode.GetItemByDataNode(modelNode), carmFolderShItem)
      modelNode.GetDisplayNode().SetViewNodeIDs(["vtkMRMLViewNode1"])

    # If Lights module is available (provided by Sandbox extension) then use physically based rendering
    usePBR = hasattr(slicer.modules, 'lights')
    if usePBR:
      import Lights
      lightsLogic = Lights.LightsLogic()
      # Apply advanced lighting to all view nodes
      viewNodes = slicer.util.getNodesByClass("vtkMRMLViewNode")
      for viewNode in viewNodes:
        # Check if the C-arm is visible in this view and skip the view if it not
        modelNode = parameterNode.GetNodeReference(models[0][0])
        if not modelNode.GetDisplayNode().IsDisplayableInView(viewNode.GetID()):
          continue
        # Update lighting
        lightsLogic.addManagedView(viewNode)
        # Move camera if it is too close to the isocenter
        cameraNode = slicer.modules.cameras.logic().GetViewActiveCameraNode(viewNode)
        cameraPos = np.zeros(3)
        cameraNode.GetPosition(cameraPos)
        focalPointPos = np.zeros(3)
        cameraNode.GetFocalPoint(focalPointPos)
        cameraDistance = np.linalg.norm(cameraPos-focalPointPos)
        if cameraDistance < 1500:
          cameraNode.SetPosition(4000, 1500, -80)
          cameraNode.SetViewUp(0,1,0)
          cameraNode.ResetClippingRange()

      # Enable SSAO
      lightsLogic.setUseSSAO(True)
      lightsLogic.setSSAOSizeScaleLog(1.5)
      # Enable image-based lighting
      lightsModuleDir = os.path.dirname(slicer.modules.lights.path)
      mipmapImageFile = os.path.join(lightsModuleDir, 'Resources/hospital_room.jpg')
      lightsLogic.setImageBasedLighting(mipmapImageFile)
    # Use PBR interpolation if image-based lighting is available; otherwise use basic Gouraud
    for modelNodeRef, parentTransformNodeRef, forBiplaneOnly in models:
      modelNode = parameterNode.GetNodeReference(modelNodeRef)
      if not modelNode:
        continue
      modelNode.CreateDefaultDisplayNodes()
      if usePBR:
        modelNode.GetDisplayNode().SetRoughness(0.4)
        modelNode.GetDisplayNode().SetInterpolation(slicer.vtkMRMLDisplayNode.PBRInterpolation)
      else:
        modelNode.GetDisplayNode().SetInterpolation(slicer.vtkMRMLDisplayNode.GouraudInterpolation)

    cls.computeTransforms()

  @classmethod
  def updateModel(cls, modelNode, parameterNode):
    cls.PARAMETER_NODE = parameterNode  # needed for setupDeviceModel

    # Get parameters
    parameterValues = cls.getParameterValuesFromNode(parameterNode)

    # TODO: set some polydata, maybe a room model
    # modelNode.SetAndObservePolyData(...)

    cls.computeTransforms()

  @staticmethod
  def updateTransform(parameterNode, transformNodeRef, translateX=0, translateY=0, translateZ=0, rotateX=0, rotateY=0, rotateZ=0):
    transformNode = parameterNode.GetNodeReference(transformNodeRef)
    if not transformNode:
      return
    transform = vtk.vtkTransform()
    transform.Translate(translateX, translateY, translateZ)
    transform.RotateX(rotateX)
    transform.RotateY(rotateY)
    transform.RotateZ(rotateZ)
    transformNode.SetMatrixTransformToParent(transform.GetMatrix())

  @classmethod
  def computeTransforms(cls):
    if not cls.PARAMETER_NODE:
      return

    parameterNode = cls.PARAMETER_NODE

    # Get parameters
    parameterValues = cls.getParameterValuesFromNode(cls.PARAMETER_NODE)

    slicer.app.pauseRender()
    try:

      # First plane
      FluoroDeviceBase.updateTransform(parameterNode, 'frontal-arm-c-rotation-transform', rotateX=parameterValues['frontalArmAngleC'])
      FluoroDeviceBase.updateTransform(parameterNode, 'frontal-arm-p-rotation-transform', rotateZ=parameterValues['frontalArmAngleP'])
      FluoroDeviceBase.updateTransform(parameterNode, 'frontal-arm-l-rotation-transform', rotateY=parameterValues['frontalArmAngleL'])
      FluoroDeviceBase.updateTransform(parameterNode, 'frontal-arm-detector-translation-transform',
        translateY=parameterValues['frontalSourceToImageDistance']-parameterValues['frontalSourceToObjectDistance'])

      # Table
      FluoroDeviceBase.updateTransform(parameterNode, 'table-lateral-transform', translateX=parameterValues['tableShiftLateral'])
      FluoroDeviceBase.updateTransform(parameterNode, 'table-longitudinal-transform', translateZ=parameterValues['tableShiftLongitudinal'])
      FluoroDeviceBase.updateTransform(parameterNode, 'table-vertical-transform', translateY=parameterValues['tableShiftVertical'])

      # Second plane
      if cls.BIPLANE:
        FluoroDeviceBase.updateTransform(parameterNode, 'lateral-arm-offset-transform', translateZ=parameterValues['lateralArmOffset'])
        FluoroDeviceBase.updateTransform(parameterNode, 'lateral-arm-p-rotation-transform', rotateY=parameterValues['lateralArmAngleP'])
        FluoroDeviceBase.updateTransform(parameterNode, 'lateral-arm-c-rotation-transform', rotateZ=parameterValues['lateralArmAngleC'])
        FluoroDeviceBase.updateTransform(parameterNode, 'lateral-arm-detector-translation-transform',
          translateX=parameterValues['lateralSourceToImageDistance']-parameterValues['lateralSourceToObjectDistance'])

    finally:
      slicer.app.resumeRender()

class GenericFluoro(FluoroDeviceBase):

  NAME = "Generic C-arm"
  ID = "GenericFluoro"
  BIPLANE = False

  @classmethod
  def getParameters(cls):
    return FluoroDeviceBase.getFrontalGantryParameters() | FluoroDeviceBase.getTableParameters()


class BiplaneFluoro(FluoroDeviceBase):

  NAME = "Generic Biplane C-arm"
  ID = "GenericBiplaneFluoro"
  BIPLANE = True

  @classmethod
  def getParameters(cls):
    return FluoroDeviceBase.getFrontalGantryParameters(displayFrontalPrefix=True) | FluoroDeviceBase.getLateralGantryParameters() | FluoroDeviceBase.getTableParameters()
