import os
import string
import vtk, qt, ctk, slicer
import logging
import numpy


class TomTecUcdPluginFileReader(object):

  def __init__(self, parent):
    self.Parent = parent

  def description(self):
    return "TomTec UCD mesh"

  def fileType(self):
    return "TomTecUCD"

  def extensions(self):
    return ["TomTec UCD mesh (*.UCD.data.zip *.UCD.datazip)"]

  def parseHeader(self, headerFilePath):
    with open(headerFilePath) as f:
      lines = f.readlines()
    properties = {}
    timestamps = []
    section = ""
    for line in lines:
      line = line.strip("\n ")
      if line.startswith("#"):
        # section header
        section = line.lstrip("# ")
        continue
      # Split line by tab
      lineItems = line.split("\t")
      # Remove empty items
      lineItems = [x.strip(' ') for x in lineItems if x]
      if not lineItems:
        # empty line
        continue
      if section == "Timestamps":
        timestamps.append(lineItems[0])
      else:
        propertyName = lineItems.pop(0)
        properties[propertyName] = lineItems
    return properties, timestamps

  def load(self, properties):
    try:
      filePath = properties["fileName"]
      tempDirectory = slicer.util.tempDirectory()

      if not slicer.util.extractArchive(filePath, tempDirectory):
        raise ValueError("Failed to extract file: "+filePath)

      # Parse header
      properties = {}
      timestamps = []
      headerSuffix = "_header.txt"
      headerFilePath = None
      for root, dirs, filenames in os.walk(tempDirectory):
        for filename in filenames:
          if filename.endswith(headerSuffix):
            # found header
            print(filename)
            headerFilePath = os.path.join(root, filename)
            properties, timestamps = self.parseHeader(headerFilePath)
            internalBaseFilePath = headerFilePath[:-len(headerSuffix)]
            break
      if not properties:
        raise ValueError("Failed to read file as TomTec UCD data file: "+filePath)

      # Get node base name from filename
      baseName = os.path.basename(filePath)
      suffix = ".UCD.data.zip"
      if baseName.endswith(suffix):
        baseName = baseName[:-len(suffix)]
      baseName = slicer.mrmlScene.GenerateUniqueName(baseName)

      sequenceNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSequenceNode", baseName)
      sequenceNode.SetIndexName("time")
      sequenceNode.SetIndexUnit("ms")
      sequenceNode.SetIndexType(slicer.vtkMRMLSequenceNode.NumericIndex)
      for propertyName in ["Average RR Duration", "Enddiastole time", "Endsystole time"]:
        sequenceNode.SetAttribute(propertyName, properties[propertyName][0])

      numberOfFrames = int(properties["Number of frames"][0])
      tempModelNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelNode", baseName+" temp")
      for frameIndex in range(numberOfFrames):
        # Read mesh
        meshFilePath = f"{internalBaseFilePath}_{frameIndex:02}.ucd"
        reader = vtk.vtkAVSucdReader()
        reader.SetFileName(meshFilePath)
        reader.Update()
        # TomTec UCD files store surface mesh in unstructured grid - convert it to polydata
        extractSurface = vtk.vtkGeometryFilter()
        extractSurface.SetInputConnection(reader.GetOutputPort())
        normals = vtk.vtkPolyDataNormals()
        normals.SetInputConnection(extractSurface.GetOutputPort())
        normals.Update()
        # Save in sequence node
        tempModelNode.SetAndObserveMesh(normals.GetOutput())
        addedNode = sequenceNode.SetDataNodeAtValue(tempModelNode, timestamps[frameIndex])

      import shutil
      shutil.rmtree(tempDirectory, True)

      slicer.mrmlScene.RemoveNode(tempModelNode)
      sequenceBrowserNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSequenceBrowserNode", baseName+" browser")
      sequenceBrowserNode.SetAndObserveMasterSequenceNodeID(sequenceNode.GetID())

      # Disable scalar visibility by default (there is not really anything useful to show)
      proxyModelNode = sequenceBrowserNode.GetProxyNode(sequenceNode)
      proxyModelNode.GetDisplayNode().SetScalarVisibility(False)

      # Show sequence browser toolbar if a sequence has been loaded
      slicer.modules.sequences.showSequenceBrowser(sequenceBrowserNode)

    except Exception as e:
      logging.error("Failed to load TomTec UCD data file: "+str(e))
      import traceback
      traceback.print_exc()
      return False
    return True

#
# TomTecUcdPlugin
#

class TomTecUcdPlugin:
  """
  This class is the 'hook' for slicer to detect and recognize the plugin
  as a loadable scripted module
  """
  def __init__(self, parent):
    parent.title = "TomTec UCD Plugin"
    parent.categories = ["Developer Tools"]
    parent.contributors = ["Andras Lasso (PerkLab)"]
    parent.helpText = """
    Plugin that registers a reader for TomTec UCD files storing unstructured grid sequences.
    """
    parent.acknowledgementText = """
    """

    # don't show this module - it only appears in the DICOM module
    parent.hidden = True
