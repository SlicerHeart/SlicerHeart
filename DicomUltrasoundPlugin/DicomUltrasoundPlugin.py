import os
import string
from __main__ import vtk, qt, ctk, slicer
import logging
import numpy
try:
  import pydicom as dicom
except:
  # Slicer-4.10 backward compatibility
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
    self.tags['manufacturer'] = "0008,0070"
    self.tags['manufacturerModelName'] = "0008,1090"

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
      loadables.extend(self.examinePhilipsAffinity3DUS(filePath))
      loadables.extend(self.examineGeKretzUS(filePath))
      loadables.extend(self.examineGeUSMovie(filePath))
      loadables.extend(self.examineGeImage3dApi(filePath))
      loadables.extend(self.examineEigenArtemis3DUS(filePath))

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
      logging.debug("Failed to parse DICOM file: {0}".format(str(e)))
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

  def examinePhilipsAffinity3DUS(self, filePath):
    supportedSOPClassUID = '1.2.840.10008.5.1.4.1.1.3.1' # UltrasoundMultiframeImageStorage

    # Quick check of SOP class UID without parsing the file...
    try:
      sopClassUID = slicer.dicomDatabase.fileValue(filePath, self.tags['sopClassUID'])
      if sopClassUID != supportedSOPClassUID:
        # Unsupported class
        # logging.debug("Not PhilipsAffinity3DUS: sopClassUID "+sopClassUID+" != supportedSOPClassUID "+supportedSOPClassUID)
        return []
    except Exception as e:
      # Quick check could not be completed (probably Slicer DICOM database is not initialized).
      # No problem, we'll try to parse the file and check the SOP class UID then.
      pass

    try:
      ds = dicom.read_file(filePath, stop_before_pixels=True)
    except Exception as e:
      logging.debug("Failed to parse DICOM file: {0}".format(str(e)))
      return []

    if ds.SOPClassUID != supportedSOPClassUID:
      # Unsupported class
      logging.debug("Not PhilipsAffinity3DUS: sopClassUID "+ds.SOPClassUID+" != supportedSOPClassUID "+supportedSOPClassUID)
      return []

    voxelSpacingTag = findPrivateTag(ds, 0x200d, 0x03, "Philips US Imaging DD 036")
    if not voxelSpacingTag:
      # this is most likely not a PhilipsAffinity image
      return []
    if voxelSpacingTag not in ds.keys():
      return []

    confidence = 0.9

    if ds.PhotometricInterpretation != 'MONOCHROME2':
      logging.warning('Warning: unsupported PhotometricInterpretation')
      confidence = .4

    if ds.BitsAllocated != 8 or ds.BitsStored != 8 or ds.HighBit != 7:
      logging.warning('Warning: Bad scalar type (not unsigned byte)')
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
    loadable.tooltip = "Philips Affinity 3D ultrasound"
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
      ds = dicom.read_file(filePath, defer_size=50) # use defer_size to not load large fields
    except Exception as e:
      logging.debug("Failed to parse DICOM file: {0}".format(str(e)))
      return []

    if ds.SOPClassUID != supportedSOPClassUID:
      # Unsupported class
      return []

    # Check if these expected DICOM tags are available:
    # (7fe1,0011) LO [KRETZ_US]                               #   8, 1 PrivateCreator
    # (7fe1,1101) OB 4b\52\45\54\5a\46\49\4c\45\20\31\2e\30\20\20\20\00\00\01\00\02\00... # 3471038, 1 Unknown Tag & Data
    kretzUsTag = dicom.tag.Tag('0x7fe1', '0x11')
    kretzUsDataTag = dicom.tag.Tag('0x7fe1', '0x1101')

    if kretzUsTag not in ds.keys():
      return []
    if kretzUsDataTag not in ds.keys():
      return []

    confidence = 0.9

    # These manufacturers values have been found in successfully loadable files:
    # - Kretztechnik
    # - GE Healthcare
    # - GE Healthcare Austria GmbH & Co OG
    if (ds.Manufacturer != 'Kretztechnik') and (ds.Manufacturer.find('GE Healthcare')<0):
      logging.warning('Warning: unknown manufacturer: '+ds.Manufacturer)
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

  def examineGeUSMovie(self, filePath):
    supportedSOPClassUIDs = [
      '1.2.840.10008.5.1.4.1.1.6.1' # UltrasoundImageStorage
      ]

    # Quick check of SOP class UID without parsing the file...
    try:
      sopClassUID = slicer.dicomDatabase.fileValue(filePath, self.tags['sopClassUID'])
      if not sopClassUID in supportedSOPClassUIDs:
        # Unsupported class
        return []
    except Exception as e:
      # Quick check could not be completed (probably Slicer DICOM database is not initialized).
      # No problem, we'll try to parse the file and check the SOP class UID then.
      pass

    try:
      ds = dicom.read_file(filePath, defer_size=30) # use defer_size to not load large fields
    except Exception as e:
      logging.debug("Failed to parse DICOM file: {0}".format(str(e)))
      return []

    if not ds.SOPClassUID in supportedSOPClassUIDs:
      # Unsupported class
      return []

    geUsMovieGroupRootTag = dicom.tag.Tag('0x7fe1', '0x0010')
    geUsMovieGroupRootItem = ds.get(geUsMovieGroupRootTag)

    if not geUsMovieGroupRootItem:
      return []
    if geUsMovieGroupRootItem.name != 'Private Creator':
      return []
    if geUsMovieGroupRootItem.value != 'GEMS_Ultrasound_MovieGroup_001':
      return []

    confidence = 0.8

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
    loadable.tooltip = "GE ultrasound image sequence"
    loadable.warning = "Importing of this file format is experimental: images may be distorted, size measurements may be inaccurate."
    loadable.selected = True
    loadable.confidence = confidence

    return [loadable]

  def examineGeImage3dApi(self, filePath):
    if not hasattr(slicer.modules, 'ultrasoundimage3dreader'):
      return []

    supportedSOPClassUIDs = [
      '1.2.840.10008.5.1.4.1.1.3.1',  # Ultrasound Multi-frame Image IOD
      '1.2.840.10008.5.1.4.1.1.6.1',  # Ultrasound Image IOD
      ]

    # Quick check of SOP class UID without parsing the file...
    try:
      sopClassUID = slicer.dicomDatabase.fileValue(filePath, self.tags['sopClassUID'])
      if not sopClassUID in supportedSOPClassUIDs:
        # Unsupported class
        return []
    except Exception as e:
      # Quick check could not be completed (probably Slicer DICOM database is not initialized).
      # No problem, we'll try to parse the file and check the SOP class UID then.
      pass

    try:
      ds = dicom.read_file(filePath, defer_size=30) # use defer_size to not load large fields
    except Exception as e:
      logging.debug("Failed to parse DICOM file: {0}".format(str(e)))
      return []

    if not ds.SOPClassUID in supportedSOPClassUIDs:
      # Unsupported class
      return []

    try:
      # Check if '3D' data type is present (for example "Trace+3D")
      #
      # (7fe1,0010) LO [GEMS_Ultrasound_MovieGroup_001]         #  30, 1 PrivateCreator
      # (7fe1,1001) SQ (Sequence with explicit length #=1)      # 76006288, 1 Unknown Tag & Data
      #   (fffe,e000) na (Item with explicit length #=6)          # 76006280, 1 Item
      #     (7fe1,0010) LO [GEMS_Ultrasound_MovieGroup_001]         #  30, 1 PrivateCreator
      #     (7fe1,1002) LO [Trace+3D]                               #   8, 1 Unknown Tag & Data

      # Get private tags
      movieGroupTag = findPrivateTag(ds, 0x7fe1, 0x01, 'GEMS_Ultrasound_MovieGroup_001')
      imageTypeTag = findPrivateTag(ds, 0x7fe1, 0x02, 'GEMS_Ultrasound_MovieGroup_001')
      contains3D = False
      movieGroup = ds[movieGroupTag].value
      for movieGroupItem in movieGroup:
          if imageTypeTag in movieGroupItem:
              if '3D' in movieGroupItem[imageTypeTag].value:
                  contains3D = True
                  break
      if not contains3D:
        # Probably 2D file
        return []
    except:
      # Not a GE MovieGroup file
      return []

    # It looks like a GE 3D ultrasound file
    import UltrasoundImage3dReader
    reader = UltrasoundImage3dReader.UltrasoundImage3dReaderFileReader(None)
    try:
      reader.getLoader(filePath)
    except Exception as e:
      logging.debug("3D ultrasound loader not found error: {0}".format(str(e)))
      logging.info("File {0} looks like a GE 3D ultrasound file. Installing Image3dAPI reader may make the file loadable (https://github.com/MedicalUltrasound/Image3dAPI).")
      return []

    # GE generic moviegroup reader has confidence=0.8
    # this one is much better than that, so use much higher value
    confidence = 0.90

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
    loadable.tooltip = "GE 3D ultrasound image sequence (using Image3dAPI)"
    loadable.selected = True
    loadable.confidence = confidence

    return [loadable]

  def examineEigenArtemis3DUS(self, filePath):
    supportedSOPClassUID = '1.2.840.10008.5.1.4.1.1.3.1' # UltrasoundMultiframeImageStorage

    # Quick check of SOP class UID without parsing the file...
    try:
      sopClassUID = slicer.dicomDatabase.fileValue(filePath, self.tags['sopClassUID'])
      if sopClassUID != supportedSOPClassUID:
        # Unsupported class
        #logging.debug("Not EigenArtemis3DUS: sopClassUID "+sopClassUID+" != supportedSOPClassUID "+supportedSOPClassUID)
        return []
    except Exception as e:
      # Quick check could not be completed (probably Slicer DICOM database is not initialized).
      # No problem, we'll try to parse the file and check the SOP class UID then.
      pass

    try:
      ds = dicom.read_file(filePath, stop_before_pixels=True)
    except Exception as e:
      logging.debug("Failed to parse DICOM file: {0}".format(str(e)))
      return []

    if ds.SOPClassUID != supportedSOPClassUID:
      # Unsupported class
      logging.debug("Not EigenArtemis3DUS: sopClassUID "+ds.SOPClassUID+" != supportedSOPClassUID "+supportedSOPClassUID)
      return []

    if not (ds.Manufacturer == "Eigen" and ds.ManufacturerModelName == "Artemis"):
      return []

    confidence = 0.9

    if ds.PhotometricInterpretation != 'MONOCHROME2':
      logging.warning('Warning: unsupported PhotometricInterpretation')
      confidence = .4

    if ds.BitsAllocated != 8 or ds.BitsStored != 8 or ds.HighBit != 7:
      logging.warning('Warning: Bad scalar type (not unsigned byte)')
      confidence = .4

    if ds.SamplesPerPixel != 1:
      logging.warning('Warning: multiple samples per pixel')
      confidence = .4

    """Use manufacturer-specific conventions, per communication
    from Rajesh Venkateraman (email to Andrey Fedorov et al on Feb 10, 2020):

    > please take the PixelAspectRatio tag divide by 1000 and that would be your isotropic resolution for display in all 3 dimensions.
    >
    > Image Patient Orientation would be [1 0 0; 0 1 0] for each frame
    >
    > The origin of the volume is the center of the 3D cube and the span would be
    >
    > For X: [-0.5*Rows*PixelAspectRatio[0]/1000, -0.5*Rows*PixelAspectRatio[0]/1000 ]
    >
    > For Y: [-0.5*Columns*PixelAspectRatio[0]/1000, -0.5*Columns*PixelAspectRatio[0]/1000 ]
    >
    > For Z: [-0.5*NumberOfSlices*PixelAspectRatio[0]/1000, -0.5* NumberOfSlices *PixelAspectRatio[0]/1000 ]

    Also, cross-check with the private attributes, if those are available.
    """

    pixelSpacingPrivate = None
    pixelSpacingPublic = None

    try:
      pixelSpacingPrivateTag = findPrivateTag(ds, 0x1129, 0x16, "Eigen, Inc")
      if pixelSpacingPrivateTag == None:
        pixelSpacingPrivateTag = findPrivateTag(ds, 0x1129, 0x16, "Eigen Artemis")
      if pixelSpacingPrivateTag is not None:
        pixelSpacingPrivate = float(pixelSpacingPrivateTag.value)
    except KeyError:
      logging.warning("examineEigenArtemis3DUS: spacing not available in private tag")

    if hasattr(ds, "PixelAspectRatio"):
      if ds.PixelAspectRatio[0] != ds.PixelAspectRatio[1]:
        logging.warning("examineEigenArtemis3DUS: PixelAspectRatio items are not equal!")
      pixelSpacingPublic = float(ds.PixelAspectRatio[0])/1000.
      if pixelSpacingPrivate is not None and pixelSpacingPrivate != pixelSpacingPublic:
        logging.warning("examineEigenArtemis3DUS: private tag based spacing does not match computed spacing")
    else:
      if pixelSpacingPrivate is None:
        logging.debug("examineEigenArtemis3DUS: unable to find spacing information")
        return []

    # prefer private, if available
    outputSpacing = pixelSpacingPrivate if pixelSpacingPrivate is not None else pixelSpacingPublic
    outputOrigin = [0.5*float(ds.Rows)*outputSpacing,
                    0.5*float(ds.Columns)*outputSpacing,
                    -0.5*float(ds.NumberOfSlices)*outputSpacing]

    logging.debug("examineEigenArtemis3DUS: assumed pixel spacing: %s" % str(outputSpacing))

    name = ''
    if hasattr(ds, 'SeriesNumber') and ds.SeriesNumber:
      name = '{0}:'.format(ds.SeriesNumber)
    if hasattr(ds, 'Modality') and ds.Modality:
      name = '{0} {1}'.format(name, ds.Modality)
    if hasattr(ds, 'SeriesDescription') and ds.SeriesDescription:
      name = '{0} {1}'.format(name, ds.SeriesDescription)
    else:
      name = name+" Eigen Artemis 3D US"
    if hasattr(ds, 'InstanceNumber') and ds.InstanceNumber:
      name = '{0} [{1}]'.format(name, ds.InstanceNumber)

    loadable = DICOMLoadable()
    loadable.files = [filePath]
    loadable.name = name.strip()  # remove leading and trailing spaces, if any
    loadable.tooltip = "Eigen Artemis 3D ultrasound"
    loadable.selected = True
    loadable.confidence = confidence
    loadable.spacing = outputSpacing
    loadable.origin = outputOrigin

    return [loadable]

  def load(self,loadable):
    """Load the selection as an Ultrasound
    """
    loadedNode = None
    if "GE Kretz 3D Ultrasound" in loadable.tooltip:
      loadedNode = self.loadKretzUS(loadable)
    elif "GE ultrasound image sequence" in loadable.tooltip:
      loadedNode = self.loadGeUsMovie(loadable)
    elif "Image3dAPI" in loadable.tooltip:
      loadedNode = self.loadImage3dAPI(loadable)
    elif "Philips Affinity 3D ultrasound" in loadable.tooltip:
      loadedNode = self.loadPhilipsAffinity3DUS(loadable)
    elif "Eigen Artemis 3D ultrasound" in loadable.tooltip:
      loadedNode = self.loadEigenArtemis3DUS(loadable)
    else:
      loadedNode = self.loadPhilips4DUSAsSequence(loadable)

    # Show sequence browser toolbar if a sequence has been loaded
    if loadedNode and loadedNode.IsA('vtkMRMLSequenceNode'):
      sequenceBrowserNode = slicer.modules.sequences.logic().GetFirstBrowserNodeForSequenceNode(loadedNode)
      if sequenceBrowserNode:
        slicer.modules.sequences.showSequenceBrowser(sequenceBrowserNode)

    return loadedNode

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

  def loadPhilipsAffinity3DUS(self,loadable):
    """Load files in the traditional Slicer manner
    using the volume logic helper class
    and the vtkITK archetype helper code
    """
    name = slicer.util.toVTKString(loadable.name)
    filePath = loadable.files[0]
    fileList = vtk.vtkStringArray()
    fileList.InsertNextValue(slicer.util.toVTKString(filePath))
    volumesLogic = slicer.modules.volumes.logic()
    outputVolume = volumesLogic.AddArchetypeScalarVolume(filePath,name,0,fileList)

    # Override spacing, as GDCM cannot retreive image spacing correctly for this type of image
    ds = dicom.read_file(filePath, stop_before_pixels=True)
    outputSpacingStr = ds[findPrivateTag(ds, 0x200d, 0x03, "Philips US Imaging DD 036")]
    outputVolume.SetSpacing(float(outputSpacingStr[0]), float(outputSpacingStr[1]), float(outputSpacingStr[2]))

    appLogic = slicer.app.applicationLogic()
    selectionNode = appLogic.GetSelectionNode()
    selectionNode.SetReferenceActiveVolumeID(outputVolume.GetID())
    appLogic.PropagateVolumeSelection(0)
    appLogic.FitSliceToAll()

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
    pixelSize = pixelShape[0] * pixelShape[1] * pixelShape[2] * pixelShape[3]
    totalFileSize = os.path.getsize(filePath)
    headerSize = totalFileSize-pixelSize

    outputSequenceNode = slicer.vtkMRMLSequenceNode()

    for frame in range(frames):

      imgReader = vtk.vtkImageReader()
      imgReader.SetFileDimensionality(3)
      imgReader.SetFileName(filePath)
      imgReader.SetNumberOfScalarComponents(1)
      imgReader.SetDataScalarTypeToUnsignedChar()
      imgReader.SetDataExtent(0,columns-1, 0,rows-1, 0,slices-1)
      imgReader.SetHeaderSize(headerSize+frame*slices*rows*columns)
      imgReader.FileLowerLeftOn()
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
      slicer.modules.sequences.setToolBarActiveBrowserNode(outputSequenceBrowserNode)

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
    pixelSize = pixelShape[0] * pixelShape[1] * pixelShape[2] * pixelShape[3]
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

  def loadGeUsMovie(self, loadable):
    #import vtkSlicerGeUsMovieReaderModuleLogicPython
    logic = slicer.modules.geusmoviereader.logic()
    nodeName = slicer.mrmlScene.GenerateUniqueName(loadable.name)

    # This can be a long operation - indicate it to the user
    qt.QApplication.setOverrideCursor(qt.Qt.WaitCursor)

    loadedSequence = logic.LoadGeUsMovieFile(loadable.files[0], nodeName)

    qt.QApplication.restoreOverrideCursor()

    # Show in slice views
    sequenceBrowserNode = slicer.modules.sequences.logic().GetFirstBrowserNodeForSequenceNode(loadedSequence)
    if sequenceBrowserNode:
      imageProxyVolumeNode = sequenceBrowserNode.GetProxyNode(loadedSequence)
    if imageProxyVolumeNode:
      appLogic = slicer.app.applicationLogic()
      selectionNode = appLogic.GetSelectionNode()
      selectionNode.SetReferenceActiveVolumeID(imageProxyVolumeNode.GetID())
      appLogic.PropagateVolumeSelection(0)
      appLogic.FitSliceToAll()

    return loadedSequence

  def loadEigenArtemis3DUS(self,loadable):

    name = slicer.util.toVTKString(loadable.name)
    filePath = loadable.files[0]
    fileList = vtk.vtkStringArray()
    fileList.InsertNextValue(slicer.util.toVTKString(filePath))
    volumesLogic = slicer.modules.volumes.logic()
    outputVolume = volumesLogic.AddArchetypeScalarVolume(filePath,name,0,fileList)

    outputVolume.SetSpacing(loadable.spacing, loadable.spacing, loadable.spacing)
    outputVolume.SetOrigin(loadable.origin[0], loadable.origin[1], loadable.origin[2])

    ijk2ras = vtk.vtkMatrix4x4()
    outputVolume.GetIJKToRASMatrix(ijk2ras)

    rot = vtk.vtkMatrix4x4()
    rot.DeepCopy((0, 1, 0, 0,
                  0, 0, 1, 0,
                  1, 0, 0, 0,
                  0, 0, 0, 1))

    ijk2ras_updated = vtk.vtkMatrix4x4()
    ijk2ras.Multiply4x4(rot, ijk2ras, ijk2ras_updated)
    outputVolume.SetIJKToRASMatrix(ijk2ras_updated)

    appLogic = slicer.app.applicationLogic()
    selectionNode = appLogic.GetSelectionNode()
    selectionNode.SetReferenceActiveVolumeID(outputVolume.GetID())
    appLogic.PropagateVolumeSelection(0)
    appLogic.FitSliceToAll()

    return outputVolume

  def loadImage3dAPI(self, loadable):
    filePath = loadable.files[0]
    loadedNode = slicer.util.loadNodeFromFile(filePath, "Image3DUS", properties={'name': loadable.name})
    return loadedNode[0] if type(loadedNode) == list else loadedNode

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

def findPrivateTag(ds, group, element, privateCreator):
  """Helper function to get private tag from private creator name"""
  for tag, data_element in ds.items():
    if (tag.group == group) and (tag.element < 0x0100):
      data_element_value = data_element.value
      if type(data_element.value) == bytes:
        data_element_value = data_element_value.decode()
      if data_element_value.rstrip() == privateCreator:
        return dicom.tag.Tag(group, (tag.element << 8) + element)
  return None
