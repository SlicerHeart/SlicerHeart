import os
import string
from __main__ import vtk, qt, ctk, slicer
import logging
import numpy
import dicom
from DICOMLib import DICOMPlugin
from DICOMLib import DICOMLoadable

#
# This is the plugin to handle translation of DICOM objects
# that can be represented as multivolume objects
# from DICOM files into MRML nodes.  It follows the DICOM module's
# plugin architecture.
#

class DicomUltrasoundPluginClass(DICOMPlugin):
  """ Ultrasound specific interpretation code
  """

  def __init__(self):
    super(DicomUltrasoundPluginClass,self).__init__()
    self.loadType = "Ultrasound"

    self.tags['sopClassUID'] = "0008,0016"

  def examine(self,fileLists):
    """ Returns a list of DICOMLoadable instances
    corresponding to ways of interpreting the
    fileLists parameter.
    """
    loadables = []
    for files in fileLists:
      loadables += self.examineFiles(files)

    return loadables

  def examineFiles(self,files):
    """ Returns a list of DICOMLoadable instances
    corresponding to ways of interpreting the
    files parameter.
    """
    loadables = []

    for filePath in files:
      # there should only be one instance per 4D volume, but on some Voluson systems
      # all sequences get the same series ID, so try to load each file separately

      loadables.extend(self.examinePhilips4DUS(filePath))
      loadables.extend(self.examineGeKretzUS(filePath))

    return loadables

  def examinePhilips4DUS(self, filePath):
    # currently only this one (bogus, non-standard) Philips 4D US format is supported
    supportedSOPClassUID = '1.2.840.113543.6.6.1.3.10002'

    # Quick check of SOP class UID without parsing the file...
    try:
      sopClassUID = slicer.dicomDatabase.fileValue(filePath, self.tags['sopClassUID'])
      if sopClassUID != supportedSOPClassUID:
        # Unsupported class
        return []
    except Exception as e:
      # Quick check could not be completed (probably Slicer DICOM database is not initialized).
      # No problem, we'll try to parse the file and check the SOP class UID then.
      pass

    try:
      ds = dicom.read_file(filePath, stop_before_pixels=True)
    except Exception as e:
      logging.debug("Failed to parse DICOM file: {0}".format(e.message))
      return []

    if ds.SOPClassUID != supportedSOPClassUID:
      # Unsupported class
      return []

    confidence = 0.9

    if ds.PhotometricInterpretation != 'MONOCHROME2':
      logging.warning('Warning: unsupported PhotometricInterpretation')
      confidence = .4

    if ds.BitsAllocated != 8 or ds.BitsStored != 8 or ds.HighBit != 7:
      logging.warning('Warning: Bad scalar type (not unsigned byte)')
      confidence = .4

    if ds.PhysicalUnitsXDirection != 3 or ds.PhysicalUnitsYDirection != 3:
      logging.warning('Warning: Units not in centimeters')
      confidence = .4

    if ds.SamplesPerPixel != 1:
      logging.warning('Warning: multiple samples per pixel')
      confidence = .4

    name = ''
    if hasattr(ds, 'SeriesNumber') and ds.SeriesNumber:
      name = '{0}:'.format(ds.SeriesNumber)
    if hasattr(ds, 'Modality') and ds.Modality:
      name = '{0} {1}'.format(name, ds.Modality)
    if hasattr(ds, 'SeriesDescription') and ds.SeriesDescription:
      name = '{0} {1}'.format(name, ds.SeriesDescription)
    if hasattr(ds, 'InstanceNumber') and ds.InstanceNumber:
      name = '{0} [{1}]'.format(name, ds.InstanceNumber)

    loadable = DICOMLoadable()
    loadable.files = [filePath]
    loadable.name = name.strip()  # remove leading and trailing spaces, if any
    loadable.tooltip = "Philips 4D Ultrasound"
    loadable.selected = True
    loadable.confidence = confidence

    return [loadable]

  def examineGeKretzUS(self, filePath):
    # E Kretz uses 'Ultrasound Image Storage' SOP class UID
    supportedSOPClassUID = '1.2.840.10008.5.1.4.1.1.6.1'

    # Quick check of SOP class UID without parsing the file...
    try:
      sopClassUID = slicer.dicomDatabase.fileValue(filePath, self.tags['sopClassUID'])
      if sopClassUID != supportedSOPClassUID:
        # Unsupported class
        return []
    except Exception as e:
      # Quick check could not be completed (probably Slicer DICOM database is not initialized).
      # No problem, we'll try to parse the file and check the SOP class UID then.
      pass

    try:
      ds = dicom.read_file(filePath, defer_size=30) # use defer_size to not load large fields
    except Exception as e:
      logging.debug("Failed to parse DICOM file: {0}".format(e.message))
      return []

    if ds.SOPClassUID != supportedSOPClassUID:
      # Unsupported class
      return []

    confidence = 0.9

    if (ds.Manufacturer != 'Kretztechnik') and (ds.Manufacturer != 'GE Healthcare'):
      logging.warning('Warning: unsupported manufacturer: '+ds.Manufacturer)
      confidence = .4

    # Check if these expected DICOM tags are available:
    # (7fe1,0011) LO [KRETZ_US]                               #   8, 1 PrivateCreator
    # (7fe1,1101) OB 4b\52\45\54\5a\46\49\4c\45\20\31\2e\30\20\20\20\00\00\01\00\02\00... # 3471038, 1 Unknown Tag & Data
    kretzUsTag = dicom.tag.Tag('0x7fe1', '0x11')
    kretzUsDataTag = dicom.tag.Tag('0x7fe1', '0x1101')

    if kretzUsTag not in ds.keys():
      return []
    if kretzUsDataTag not in ds.keys():
      return []

    name = ''
    if hasattr(ds, 'SeriesNumber') and ds.SeriesNumber:
      name = '{0}:'.format(ds.SeriesNumber)
    if hasattr(ds, 'Modality') and ds.Modality:
      name = '{0} {1}'.format(name, ds.Modality)
    if hasattr(ds, 'SeriesDescription') and ds.SeriesDescription:
      name = '{0} {1}'.format(name, ds.SeriesDescription)
    if hasattr(ds, 'InstanceNumber') and ds.InstanceNumber:
      name = '{0} [{1}]'.format(name, ds.InstanceNumber)
    name = name.strip() # remove leading and trailing spaces, if any

    loadable = DICOMLoadable()
    loadable.files = [filePath]
    loadable.name = name
    loadable.tooltip = "GE Kretz 3D Ultrasound"
    loadable.warning = "Importing of this file format is experimental: images may be distorted, size measurements may be inaccurate."
    loadable.selected = True
    loadable.confidence = confidence

    loadableHighRes1 = DICOMLoadable()
    loadableHighRes1.files = loadable.files
    loadableHighRes1.name = loadable.name + " (LR)"
    loadableHighRes1.tooltip = loadable.tooltip + " (low-resolution)"
    loadableHighRes1.warning = loadable.warning
    loadableHighRes1.selected = False
    loadableHighRes1.confidence = confidence

    loadableHighRes2 = DICOMLoadable()
    loadableHighRes2.files = loadable.files
    loadableHighRes2.name = loadable.name + " (HR)"
    loadableHighRes2.tooltip = loadable.tooltip + " (high-resolution)"
    loadableHighRes2.warning = loadable.warning
    loadableHighRes2.selected = False
    loadableHighRes2.confidence = confidence

    return [loadable, loadableHighRes1, loadableHighRes2]


  def load(self,loadable):
    """Load the selection as an Ultrasound
    """
    if "GE Kretz 3D Ultrasound" in loadable.tooltip:
      return self.loadKretzUS(loadable)
    else:
      return self.loadPhilips4DUSAsSequence(loadable)
      #return self.loadPhilips4DUSAsMultiVolume(loadable)

  def loadKretzUS(self, loadable):
    import vtkSlicerKretzFileReaderLogicPython
    logic = slicer.modules.kretzfilereader.logic()
    nodeName = slicer.mrmlScene.GenerateUniqueName(loadable.name)

    ds = dicom.read_file(loadable.files[0], defer_size=30)  # use defer_size to not load large fields
    kretzUsDataTag = dicom.tag.Tag('0x7fe1', '0x1101')
    kretzUsDataItem = ds.get(kretzUsDataTag)
    volFileOffset = kretzUsDataItem.file_tell # add 12 bytes for tag, VR, and length,

    # This can be a long operation - indicate it to the user
    qt.QApplication.setOverrideCursor(qt.Qt.WaitCursor)


    outputSpacing = [0.667, 0.667, 0.667]
    if "(low-resolution)" in loadable.tooltip:
      outputSpacing = [1.0, 1.0, 1.0]
    elif "(high-resolution)" in loadable.tooltip:
      outputSpacing = [0.333, 0.333, 0.333]

    outputVolume = logic.LoadKretzFile(loadable.files[0], nodeName, True, outputSpacing, volFileOffset)

    qt.QApplication.restoreOverrideCursor()

    # Show in slice views
    selectionNode = slicer.app.applicationLogic().GetSelectionNode()
    selectionNode.SetReferenceActiveVolumeID(outputVolume.GetID())
    slicer.app.applicationLogic().PropagateVolumeSelection(1)

    return outputVolume

  def loadPhilips4DUSAsSequence(self,loadable):
    """Load the selection as an Ultrasound, store in a Sequence node
    """

    # get the key info from the "fake" dicom file
    filePath = loadable.files[0]
    ds = dicom.read_file(filePath, stop_before_pixels=True)
    columns = ds.Columns
    rows = ds.Rows
    slices = ds[(0x3001,0x1001)].value # private tag!
    spacing = (
            ds.PhysicalDeltaX * 10,
            ds.PhysicalDeltaY * 10,
            ds[(0x3001,0x1003)].value * 10 # private tag!
            )
    frames  = int(ds.NumberOfFrames)
    imageComponents = frames
    frameTimeMsec = ds.FrameTime

    pixelShape = (frames, slices, rows, columns)
    pixelSize = reduce(lambda x,y : x*y, pixelShape)
    totalFileSize = os.path.getsize(filePath)
    headerSize = totalFileSize-pixelSize

    outputSequenceNode = slicer.vtkMRMLSequenceNode()

    for frame in range(frames):

      imgReader = vtk.vtkImageReader()
      imgReader.SetFileDimensionality(3)
      imgReader.SetFileName(filePath);
      imgReader.SetNumberOfScalarComponents(1)
      imgReader.SetDataScalarTypeToUnsignedChar()
      imgReader.SetDataExtent(0,columns-1, 0,rows-1, 0,slices-1)
      imgReader.SetHeaderSize(headerSize+frame*slices*rows*columns)
      imgReader.FileLowerLeftOn();
      imgReader.Update()

      outputNode = slicer.vtkMRMLScalarVolumeNode()
      outputNode.SetAndObserveImageData(imgReader.GetOutput())
      outputNode.SetSpacing(spacing)

      timeStampSec = "{:.3f}".format(frame * frameTimeMsec * 0.001)
      outputSequenceNode.SetDataNodeAtValue(outputNode, timeStampSec)

    outputSequenceNode.SetName(slicer.mrmlScene.GenerateUniqueName(loadable.name))
    slicer.mrmlScene.AddNode(outputSequenceNode)

    # Create storage node that allows saving node as nrrd
    outputSequenceStorageNode = slicer.vtkMRMLVolumeSequenceStorageNode()
    slicer.mrmlScene.AddNode(outputSequenceStorageNode)
    outputSequenceNode.SetAndObserveStorageNodeID(outputSequenceStorageNode.GetID())

    if not hasattr(loadable, 'createBrowserNode') or loadable.createBrowserNode:
      # Add a browser node and show the volume in the slice viewer for user convenience
      outputSequenceBrowserNode = slicer.vtkMRMLSequenceBrowserNode()
      outputSequenceBrowserNode.SetName(slicer.mrmlScene.GenerateUniqueName(outputSequenceNode.GetName()+' browser'))
      slicer.mrmlScene.AddNode(outputSequenceBrowserNode)
      outputSequenceBrowserNode.SetAndObserveMasterSequenceNodeID(outputSequenceNode.GetID())
      masterOutputNode = outputSequenceBrowserNode.GetProxyNode(outputSequenceNode)

      # Automatically select the volume to display
      appLogic = slicer.app.applicationLogic()
      selNode = appLogic.GetSelectionNode()
      selNode.SetReferenceActiveVolumeID(masterOutputNode.GetID())
      appLogic.PropagateVolumeSelection()
      appLogic.FitSliceToAll()
      slicer.modules.sequencebrowser.setToolBarActiveBrowserNode(outputSequenceBrowserNode)

      # create Subject hierarchy nodes for the loaded series
      self.addSeriesInSubjectHierarchy(loadable, masterOutputNode)

    return outputSequenceNode

  def loadPhilips4DUSAsMultiVolume(self,loadable):
    """Load the selection as an Ultrasound, store in MultiVolume
    """

    # get the key info from the "fake" dicom file
    filePath = loadable.files[0]
    ds = dicom.read_file(filePath, stop_before_pixels=True)
    columns = ds.Columns
    rows = ds.Rows
    slices = ds[(0x3001,0x1001)].value # private tag!
    spacing = (
            ds.PhysicalDeltaX * 10,
            ds.PhysicalDeltaY * 10,
            ds[(0x3001,0x1003)].value * 10 # private tag!
            )
    frames  = int(ds.NumberOfFrames)
    imageComponents = frames

    # create the correct size and shape vtkImageData
    image = vtk.vtkImageData()
    imageShape = (slices, rows, columns, frames)
    image.SetDimensions(columns, rows, slices)
    image.AllocateScalars(vtk.VTK_UNSIGNED_CHAR, imageComponents)
    from vtk.util.numpy_support import vtk_to_numpy
    imageArray = vtk_to_numpy(image.GetPointData().GetScalars()).reshape(imageShape)

    # put the data in a numpy array
    # -- we need to read the file as raw bytes
    pixelShape = (frames, slices, rows, columns)
    pixels = numpy.fromfile(filePath, dtype=numpy.uint8)
    pixelSize = reduce(lambda x,y : x*y, pixelShape)
    headerSize = len(pixels)-pixelSize
    pixels = pixels[headerSize:]
    pixels = pixels.reshape(pixelShape)

    slicer.modules.imageArray = imageArray
    slicer.modules.pixels = pixels

    # copy the data from numpy to vtk (need to shuffle frames to components)
    for frame in range(frames):
      imageArray[:,:,:,frame] = pixels[frame]

    # create the multivolume node and display it
    multiVolumeNode = slicer.vtkMRMLMultiVolumeNode()

    multiVolumeNode.SetScene(slicer.mrmlScene)

    multiVolumeDisplayNode = slicer.mrmlScene.CreateNodeByClass('vtkMRMLMultiVolumeDisplayNode')
    multiVolumeDisplayNode.SetReferenceCount(multiVolumeDisplayNode.GetReferenceCount()-1)
    multiVolumeDisplayNode.SetScene(slicer.mrmlScene)
    multiVolumeDisplayNode.SetDefaultColorMap()
    slicer.mrmlScene.AddNode(multiVolumeDisplayNode)

    multiVolumeNode.SetAndObserveDisplayNodeID(multiVolumeDisplayNode.GetID())
    multiVolumeNode.SetAndObserveImageData(image)
    multiVolumeNode.SetNumberOfFrames(frames)
    multiVolumeNode.SetName(loadable.name)
    slicer.mrmlScene.AddNode(multiVolumeNode)

    #
    # automatically select the volume to display
    #
    appLogic = slicer.app.applicationLogic()
    selNode = appLogic.GetSelectionNode()
    selNode.SetReferenceActiveVolumeID(multiVolumeNode.GetID())
    appLogic.PropagateVolumeSelection()

    return multiVolumeNode

#
# DicomUltrasoundPlugin
#

class DicomUltrasoundPlugin:
  """
  This class is the 'hook' for slicer to detect and recognize the plugin
  as a loadable scripted module
  """
  def __init__(self, parent):
    parent.title = "DICOM Ultrasound Import Plugin"
    parent.categories = ["Developer Tools.DICOM Plugins"]
    parent.contributors = ["Andras Lasso (PerkLab), Steve Pieper (Isomics Inc.)"]
    parent.helpText = """
    Plugin to the DICOM Module to parse and load Ultrasound data from DICOM files.
    No module interface here, only in the DICOM module.
    """
    parent.acknowledgementText = """
    Philips 4D reader was developed by Steve Pieper, Isomics, Inc.
    based on MultiVolume example code by Andrey Fedorov, BWH.
    and was partially funded by NIH grants U01CA151261 and 3P41RR013218.
    """

    # don't show this module - it only appears in the DICOM module
    parent.hidden = True

    # Add this extension to the DICOM module's list for discovery when the module
    # is created.  Since this module may be discovered before DICOM itself,
    # create the list if it doesn't already exist.
    try:
      slicer.modules.dicomPlugins
    except AttributeError:
      slicer.modules.dicomPlugins = {}
    slicer.modules.dicomPlugins['DicomUltrasoundPlugin'] = DicomUltrasoundPluginClass
