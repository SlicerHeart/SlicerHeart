import os
import string
import vtk, qt, ctk, slicer
import logging
import numpy as np


class UltrasoundImage3dReaderFileReader(object):

  def __init__(self, parent):
    self.Parent = parent

  def description(self):
    return "3D ultrasound image"

  def fileType(self):
    return "Image3DUS"

  def extensions(self):
    return ["3D ultrasound image (*.3dus)"]

  def typeLibFromProgId(self, progId):
    """Loads the type library from progId"""
    import comtypes.client

    clsid = str(comtypes.GUID.from_progid(progId))

    import winreg
    with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "CLSID\\"+clsid+"\\TypeLib", 0, winreg.KEY_READ) as key:
      typelib = winreg.EnumValue(key, 0)[1]
    with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "CLSID\\"+clsid+"\\Version", 0, winreg.KEY_READ) as key:
      version = winreg.EnumValue(key, 0)[1]

    try:
      major_ver, minor_ver = version.split(".")
      return comtypes.client.GetModule([typelib, int(major_ver), int(minor_ver)])
    except OSError as err:
      # API 1.2-only compatibility fallback to avoid breaking existing loaders
      if (version != "1.2") or (err.winerror != -2147319779): # Library not registered
        raise # rethrow
      # Fallback to TypeLib version 1.0
      return comtypes.client.GetModule([typelib, 1, 0])

  def safeArrayToNumpy(self, safearr_ptr, copy=True):
    """Convert a SAFEARRAY buffer to its numpy equivalent"""

    import platform
    import comtypes
    import comtypes.client

    import ctypes
    # only support 1D data for now
    assert(comtypes._safearray.SafeArrayGetDim(safearr_ptr) == 1)
    # access underlying pointer
    data_ptr = ctypes.POINTER(safearr_ptr._itemtype_)()
    comtypes._safearray.SafeArrayAccessData(safearr_ptr, ctypes.byref(data_ptr))
    upper_bound = comtypes._safearray.SafeArrayGetUBound(safearr_ptr, 1) + 1 # +1 to go from inclusive to exclusive bound
    lower_bound = comtypes._safearray.SafeArrayGetLBound(safearr_ptr, 1)
    array_size = upper_bound - lower_bound
    # wrap pointer in numpy array
    arr = np.ctypeslib.as_array(data_ptr,shape=(array_size,))
    return np.copy(arr) if copy else arr

  def frameTo3dArray(self, frame):
    """Convert Image3d data into a numpy 3D array"""
    arr_1d = self.safeArrayToNumpy(frame.data, copy=False)
    assert(arr_1d.dtype == np.uint8) # only tested with 1byte/elm
    arr_3d = np.lib.stride_tricks.as_strided(arr_1d, shape=frame.dims, strides=(1, frame.stride0, frame.stride1))
    return np.copy(arr_3d)

  def getLoader(self, filePath):
    try:
      import comtypes
    except ModuleNotFoundError:
      slicer.util.showStatusMessage("Installing comtypes Python package...")
      slicer.app.processEvents()
      slicer.util.pip_install('comtypes')
      import comtypes

    import platform
    import comtypes
    import comtypes.client

    errorType = -1
    errorMessage = None
    loaderProgIds = [
      "GEHC_CARD_US.Image3dFileLoader",
      "CanonLoader.Image3dFileLoader",
      "HitCV3DLoader.Image3dFileLoader",
      "SiemensLoader.Image3dFileLoader",
      "PhilipsLoader.Image3dFileLoader",
      "KretzLoader.KretzImage3dFileLoader"
      ]
    for loaderProgId in loaderProgIds:
      # create loader object
      try:
        image3dAPI = self.typeLibFromProgId(loaderProgId)
      except:
        logging.debug("Ultrasound image reader not installed: "+loaderProgId)
        continue

      try:
        loaderObj = comtypes.client.CreateObject(loaderProgId)
        loader = loaderObj.QueryInterface(image3dAPI.IImage3dFileLoader)
      except:
        logging.debug("Error instantiating image reader: "+loaderProgId)
        continue

      # load file
      try:
        errorType, errorMessage = loader.LoadFile(filePath)
        logging.debug("Reader {0} image reading result for {1}: {2} ({3})".format(loaderProgId, filePath, errorType, errorMessage))
        if errorType == 0:
          # success
          break
      except Exception as e:
        logging.debug("Reader {0} cannot read image {1}".format(loaderProgId, filePath))
        logging.error("Failed to load 3D ultrasound file: " + str(e))
        import traceback
        traceback.print_exc()
        continue

    if errorType != 0:
      raise ValueError("Failed to read {0} as ultrasound image".format(filePath))

    return loader

  def canLoadFile(self, filePath):
    # importing comtypes makes the application crash on exit, so we don't want
    # it to be called, unless it is necessary, so we don't use this deep check:
    #
    # # Any file extension is possible, check if we can find a reader for this
    # try:
    #   loader = self.getLoader(filePath)
    # except:
    #   return False
    # return loader is not None
    #
    # We don't use canLoadFile's default implementation either, because that would
    # prevent programmatically loading data from files that do not have 3dus file extension
    # (e.g., from DICOM files, which can have any extension).
    return True

  def load(self, properties):
    sequenceNode = None
    tableNode = None
    colorTableNode = None
    tempVolumeNode = None
    sequenceBrowserNode = None

    try:
      filePath = properties["fileName"]

      maxDimension = 200
      if maxDimension in properties.keys():
        maxDimension = int(properties["maxDimension"])

      loader = self.getLoader(filePath)
      source = loader.GetImageSource()
      numberOfFrames = source.GetFrameCount()

      # Get node base name from filename
      if 'name' in properties.keys():
        baseName = properties['name']
      else:
        baseName = os.path.splitext(os.path.basename(filePath))[0]
        baseName = slicer.mrmlScene.GenerateUniqueName(baseName)

      # We only create a volume sequence node (and later sequence browser node) if there are
      # more than 1 frames, to keep the scene as simple as possible.
      if numberOfFrames > 1:
        # Temporary volume node to construct volume sequence
        tempVolumeNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", baseName+" temp")
        # Create sequence node
        sequenceNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSequenceNode", baseName)
        sequenceNode.SetIndexName("time")
        sequenceNode.SetIndexUnit("ms")
        sequenceNode.SetIndexType(slicer.vtkMRMLSequenceNode.NumericIndex)
        nodeForStoringMetadata = sequenceNode
      else:
        tempVolumeNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", baseName)
        nodeForStoringMetadata = tempVolumeNode

      nodeForStoringMetadata.SetAttribute("DICOM.instanceUIDs", slicer.dicomDatabase.instanceForFile(filePath))

      # retrieve probe info
      probe = source.GetProbeInfo()
      nodeForStoringMetadata.SetAttribute("SlicerHeart.ProbeName", probe.name)
      nodeForStoringMetadata.SetAttribute("SlicerHeart.ProbeType", str(probe.type))

      # retrieve ECG info
      ecg = source.GetECG()
      tableNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode", baseName+" ECG")
      tableNode.SetAttribute("DICOM.instanceUIDs", slicer.dicomDatabase.instanceForFile(filePath))
      ecgSamples = self.safeArrayToNumpy(ecg.samples)
      numberOfSamples = len(ecgSamples)
      ecgTimestamps = np.arange(ecg.start_time, ecg.start_time+numberOfSamples*ecg.delta_time, ecg.delta_time)
      trigTimes = self.safeArrayToNumpy(ecg.trig_times)
      slicer.util.updateTableFromArray(tableNode, [ecgTimestamps, ecgSamples, trigTimes], ["time", "ecg", "triggerTimes"])

      # get image geometry
      bbox = source.GetBoundingBox()
      origins = [bbox.origin_x, bbox.origin_y, bbox.origin_z]
      dirs = []
      dirs.append(np.array([bbox.dir1_x,   bbox.dir1_y,   bbox.dir1_z]))
      dirs.append(np.array([bbox.dir2_x,   bbox.dir2_y,   bbox.dir2_z]))
      dirs.append(np.array([bbox.dir3_x,   bbox.dir3_y,   bbox.dir3_z]))
      lpsToRas = np.diag([-1,-1,1,1])

      # set color table
      colorTableNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLColorTableNode", baseName+" colormap")
      colorTableNode.SetAttribute("DICOM.instanceUIDs", slicer.dicomDatabase.instanceForFile(filePath))
      colorMapArray = source.GetColorMap()
      numberOfColors = len(colorMapArray)
      colorTableNode.SetTypeToUser()
      colorTableNode.SetNumberOfColors(numberOfColors)
      wasModified = colorTableNode.StartModify()
      for colorIndex in range(numberOfColors):
        color = colorMapArray[colorIndex]
        r = float(color & 255) / 255.0
        g = float((color >> 8) & 255) / 255.0
        b = float((color >> 16) & 255) / 255.0
        a = float((color >> 24) & 255) / 255.0
        success=colorTableNode.SetColor(colorIndex, "US{0:3d}".format(colorIndex), r, g, b, a)
      colorTableNode.EndModify(wasModified)

      for frameIndex in range(numberOfFrames):
        maxRes = np.ctypeslib.as_ctypes(np.array([maxDimension, maxDimension, maxDimension], dtype=np.ushort))

        frame = source.GetFrame(frameIndex, bbox, maxRes)
        tempVolumeNode.SetAttribute("DICOM.instanceUIDs", slicer.dicomDatabase.instanceForFile(filePath))
        tempVolumeNode.SetAttribute("SlicerHeart.FrameFormat", str(frame.format))
        voxels = self.frameTo3dArray(frame)
        slicer.util.updateVolumeFromArray(tempVolumeNode, voxels)

        ijkToLps = np.eye(4)
        for axisIndex in range(3):
          # all units from Image3dAPI are in meters according to https://github.com/MedicalUltrasound/Image3dAPI/wiki#image-geometry
          voxelToPhysicalAxis = dirs[axisIndex] / frame.dims[axisIndex] * 1000.0
          origin = origins[axisIndex] * 1000.0
          # we need to use 2-axisIndex because numpy uses KJI index order instead of IJK
          ijkToLps[0:3, 2-axisIndex] = voxelToPhysicalAxis
          ijkToLps[3, 2-axisIndex] = origin
        ijkToRas = np.dot(lpsToRas, ijkToLps)
        ijkToRasMatrix = slicer.util.vtkMatrixFromArray(ijkToRas)
        tempVolumeNode.SetIJKToRASMatrix(ijkToRasMatrix)

        # Save in sequence node
        if numberOfFrames > 1:
          addedNode = sequenceNode.SetDataNodeAtValue(tempVolumeNode, str(frame.time))
        else:
          nodeForStoringMetadata.SetAttribute("SlicerHeart.FrameTime", str(frame.time))

      if numberOfFrames > 1:
        slicer.mrmlScene.RemoveNode(tempVolumeNode)
        tempVolumeNode = None
        sequenceBrowserNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSequenceBrowserNode", baseName+" browser")
        sequenceBrowserNode.SetAndObserveMasterSequenceNodeID(sequenceNode.GetID())
        # Save ECG reference to browser node (we may want to show it in the future in sequence browser widget, too)
        sequenceBrowserNode.SetNodeReferenceID('SlicerHeart.ECG', tableNode.GetID())
        # Save ECG reference to sequence node (just in case it is dissociated from the browser node)
        sequenceNode.SetNodeReferenceID('SlicerHeart.ECG', tableNode.GetID())
        proxyVolumeNode = sequenceBrowserNode.GetProxyNode(sequenceNode)
      else:
        tempVolumeNode.CreateDefaultDisplayNodes()
        proxyVolumeNode = tempVolumeNode

      # Set color table
      proxyVolumeNode.GetDisplayNode().SetAndObserveColorNodeID(colorTableNode.GetID())
      # Set ECG table reference (it is visible in subject hierarchy)
      proxyVolumeNode.SetNodeReferenceID('SlicerHeart.ECG', tableNode.GetID())

      # Show in slice views
      selectionNode = slicer.app.applicationLogic().GetSelectionNode()
      selectionNode.SetReferenceActiveVolumeID(proxyVolumeNode.GetID())
      slicer.app.applicationLogic().PropagateVolumeSelection(1) 

      if numberOfFrames > 1:
        # Show sequence browser toolbar if a sequence has been loaded
        slicer.modules.sequences.showSequenceBrowser(sequenceBrowserNode)

    except Exception as e:
      logging.error("Failed to load 3D ultrasound file: "+str(e))
      import traceback
      traceback.print_exc()
      # Remove partially initialized nodes
      for node in [tempVolumeNode, sequenceBrowserNode, tableNode, colorTableNode, sequenceNode]:
        if node:
          slicer.mrmlScene.RemoveNode(node)
      return False

    if numberOfFrames > 1:
      self.Parent.loadedNodes = [sequenceNode.GetID(), sequenceBrowserNode.GetID()]
    else:
      self.Parent.loadedNodes = [proxyVolumeNode.GetID()]
    return True


# class UltrasoundImage3dReaderFileWriter(object):

#   def __init__(self, parent):
#     self.Parent = parent
#     print("UltrasoundImage3dReaderFileWriter - __init__")


#
# UltrasoundImage3dReader
#

class UltrasoundImage3dReader:
  """
  This class is the 'hook' for slicer to detect and recognize the plugin
  as a loadable scripted module
  """
  def __init__(self, parent):
    parent.title = "Ultrasound Image3D API Plugin"
    parent.categories = ["Developer Tools"]
    parent.contributors = ["Andras Lasso (PerkLab)"]
    parent.helpText = """
    Plugin that uses Image3D API to read 3D ultrasound files (https://github.com/MedicalUltrasound/Image3dAPI#description).
    """
    parent.acknowledgementText = """
    """

    # don't show this module - it only appears in the DICOM module
    parent.hidden = True
