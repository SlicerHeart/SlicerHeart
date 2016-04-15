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
    allfiles = []
    for files in fileLists:
      loadables += self.examineFiles(files)
      allfiles += files

    return loadables

  def examineFiles(self,files):
    """ Returns a list of DICOMLoadable instances
    corresponding to ways of interpreting the
    files parameter.
    """
    loadables = []

    if len(files) > 1:
      # there should only be one instance per 4D volume
      return []

    filePath = files[0]
    
    # currently only this one (bogus, non-standard) Philips 4D US format is supported
    supportedSOPClassUID = '1.2.840.113543.6.6.1.3.10002'
    
    # Quick check of SOP class UID without parsing the file...
    try:
      sopClassUID = slicer.dicomDatabase.fileValue(filePath,self.tags['sopClassUID'])
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
      
    if ds.PhotometricInterpretation != 'MONOCHROME2':
      logging.warning('Warning: unsupported PhotometricInterpretation')
      loadable.confidence = .4

    if ds.BitsAllocated != 8 or ds.BitsStored != 8 or ds.HighBit != 7:
      logging.warning('Warning: Bad scalar type (not unsigned byte)')
      loadable.confidence = .4

    if ds.PhysicalUnitsXDirection != 3 or ds.PhysicalUnitsYDirection != 3:
      logging.warning('Warning: Units not in centimeters')
      loadable.confidence = .4

    if ds.SamplesPerPixel != 1:
      logging.warning('Warning: multiple samples per pixel')
      loadable.confidence = .4

    name = ''
    if hasattr(ds,'SeriesNumber') and ds.SeriesNumber:
      name = '{0}:'.format(ds.SeriesNumber)
    if hasattr(ds,'Modality') and ds.Modality:
      name = '{0} {1}'.format(name, ds.Modality)
    if hasattr(ds,'SeriesDescription') and ds.SeriesDescription:
      name = '{0} {1}'.format(name, ds.SeriesDescription)
    if hasattr(ds,'InstanceNumber') and ds.InstanceNumber:
      name = '{0} [{1}]'.format(name, ds.InstanceNumber)

    loadable = DICOMLoadable()
    loadable.files = files
    loadable.name = name.strip() # remove leading and trailing spaces, if any
    loadable.tooltip = "Philips 4D Ultrasound"
    loadable.selected = True
    loadable.confidence = 1.
    loadables.append(loadable)

    return loadables

  def load(self,loadable):
    """Load the selection as an Ultrasound
    """
    return self.loadAsSequence(loadable)
    #return self.loadAsMultiVolume(loadable)
    
  def loadAsSequence(self,loadable):
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
    
    outputSequenceNode = slicer.modulemrml.vtkMRMLSequenceNode()
    
    for frame in range(frames):
    
      imgReader = vtk.vtkImageReader()
      imgReader.SetFileDimensionality(3)
      imgReader.SetFileName(filePath);
      imgReader.SetNumberOfScalarComponents(1)
      imgReader.SetDataScalarTypeToUnsignedChar()
      imgReader.SetDataExtent(0,columns-1, 0,rows-1, 0,slices-1)
      imgReader.SetHeaderSize(headerSize+frame*slices*rows*columns)
      imgReader.Update()
          
      outputNode = slicer.vtkMRMLScalarVolumeNode() 
      outputNode.SetAndObserveImageData(imgReader.GetOutput())
      outputNode.SetSpacing(spacing)

      timeStampSec = "{:.3f}".format(frame * frameTimeMsec * 0.001)
      outputSequenceNode.SetDataNodeAtValue(outputNode, timeStampSec)

    outputSequenceNode.SetName(slicer.mrmlScene.GenerateUniqueName(loadable.name))
    slicer.mrmlScene.AddNode(outputSequenceNode)

    # Create storage node that allows saving node as nrrd
    outputSequenceStorageNode = slicer.modulemrml.vtkMRMLVolumeSequenceStorageNode()
    slicer.mrmlScene.AddNode(outputSequenceStorageNode)
    outputSequenceNode.SetAndObserveStorageNodeID(outputSequenceStorageNode.GetID())

    if not hasattr(loadable, 'createBrowserNode') or loadable.createBrowserNode:
      # Add a browser node and show the volume in the slice viewer for user convenience
      outputSequenceBrowserNode = slicer.modulemrml.vtkMRMLSequenceBrowserNode()
      outputSequenceBrowserNode.SetName(slicer.mrmlScene.GenerateUniqueName(outputSequenceNode.GetName()+' browser'))
      slicer.mrmlScene.AddNode(outputSequenceBrowserNode)
      outputSequenceBrowserNode.SetAndObserveMasterSequenceNodeID(outputSequenceNode.GetID())
      masterOutputNode = outputSequenceBrowserNode.GetVirtualOutputDataNode(outputSequenceNode)
    
      # Automatically select the volume to display
      appLogic = slicer.app.applicationLogic()
      selNode = appLogic.GetSelectionNode()
      selNode.SetReferenceActiveVolumeID(masterOutputNode.GetID())
      appLogic.PropagateVolumeSelection()
      appLogic.FitSliceToAll()

      outputSequenceBrowserNode.ScalarVolumeAutoWindowLevelOff() # for performance optimization

      # create Subject hierarchy nodes for the loaded series
      self.addSeriesInSubjectHierarchy(loadable, masterOutputNode)

    return outputSequenceNode
    
  def loadAsMultiVolume(self,loadable):
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
    parent.contributors = ["Steve Pieper, Isomics Inc."]
    parent.helpText = """
    Plugin to the DICOM Module to parse and load Ultrasound data from DICOM files.
    No module interface here, only in the DICOM module
    """
    parent.acknowledgementText = """
    This DICOM Plugin was developed by Steve Pieper, Isomics, Inc.
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
