import unittest
import vtk, qt, ctk, slicer
from slicer.ScriptedLoadableModule import *
import logging

import os
import ntpath  
import xml.etree.ElementTree as ET 
import re
import zipfile
import shutil
import struct
import numpy as np
import math

################################################################################
# EAMapReader
#

class EAMapReader(ScriptedLoadableModule):

  def __init__(self, parent):
    ScriptedLoadableModule.__init__(self, parent)
    self.parent.title = "EA Map Reader" 
    self.parent.categories = ["Cardiac Electrophysiology"]
    self.parent.dependencies = []
    self.parent.contributors = ["Stephan Hohmann (Hannover Medical School)"]
    self.parent.helpText = """
This extension reads electroanatomic maps exported from various systems into 3D Slicer.
Currently supported are Ensite NavX (Abbott, St. Paul, MN), CARTO 3 (Biosense Webster, Diamond Bar, CA), and RHYTHMIA (Boston Scientific, Marlborough, MA). 
For research use only. The manufacturers of the respective mapping systems are not affiliated with the development of this extension. 
This software has not been approved for clinical use, and imported maps should be cross-checked with their representation on the original mapping system.
See documentation for detailed export instructions.
"""
    self.parent.helpText += self.getDefaultModuleDocumentationLink()
    self.parent.acknowledgementText = """
This extension was developed by Stephan Hohmann, Hannover Medical School.
This work was funded by the Deutsche Forschungsgemeinschaft (DFG, German Research Foundation) - project no. 380200397.
If you use EAMapReader in your own research please cite the following publication: Hohmann S, Henkenberens C, Zormpas C, Christiansen H, Bauersachs J, Duncker D, Veltmann C. A novel open-source software based high-precision workflow for target definition in cardiac radioablation. J Cardiovasc Electrophysiol 2020. doi:10.1111/jce.14660 

""" 

################################################################################
# EAMapReaderWidget
#

class EAMapReaderWidget(ScriptedLoadableModuleWidget):

  def setup(self):
    ScriptedLoadableModuleWidget.setup(self)
    
    self.logic = EAMapReaderLogic()
    self.logic.logCallback = self.addLog
    self.logic.progressCallback = self.updateProgress
    self.loadingInProgress = False
    
    # Instantiate and connect widgets ...
    self.buttonEnsite = qt.QPushButton("Ensite")
    self.buttonEnsite.toolTip = "Import Ensite map."
    self.buttonEnsite.enabled = True
    self.layout.addWidget(self.buttonEnsite)
    
    self.buttonCarto = qt.QPushButton("CARTO 3")
    self.buttonCarto.toolTip = "Import CARTO 3 map."
    self.buttonCarto.enabled = True
    self.layout.addWidget(self.buttonCarto)
    
    self.buttonRhythmia = qt.QPushButton("RHYTHMIA")
    self.buttonRhythmia.toolTip = "Import RHYTHMIA Map."
    self.buttonRhythmia.enabled = True
    self.layout.addWidget(self.buttonRhythmia)
    
    self.statusLabel = qt.QPlainTextEdit()
    self.statusLabel.setTextInteractionFlags(qt.Qt.TextSelectableByMouse)
    self.statusLabel.setCenterOnScroll(True)
    self.layout.addWidget(self.statusLabel)
    
    self.progressBar=qt.QProgressBar()
    self.progressBar.setRange(0, 100) 
    self.progressBar.setValue(0)
    self.layout.addWidget(self.progressBar)
    
    # connections
    self.buttonEnsite.connect('clicked(bool)', self.onButtonEnsite)
    self.buttonCarto.connect('clicked(bool)', self.onButtonCarto)
    self.buttonRhythmia.connect('clicked(bool)', self.onButtonRhythmia)
  
  def cleanup(self):
    pass
  
  def reenableButtons(self):
    self.buttonEnsite.text = "Ensite"
    self.buttonEnsite.enabled = True
    self.buttonCarto.text = "CARTO 3"
    self.buttonCarto.enabled = True
    self.buttonRhythmia.text = "RHYTHMIA"
    self.buttonRhythmia.enabled = True
  
  def onButtonEnsite(self):
    if self.loadingInProgress:
      self.loadingInProgress = False
      self.logic.abortRequested = True
      self.buttonEnsite.text = "Cancelling..."
      self.buttonEnsite.enabled = False
      return
    self.clearLog()
    self.filename = qt.QFileDialog.getOpenFileName(self.parent, "Open Ensite file", "", "XML files (*.xml);;All files (*.*)", qt.QFileDialog.ExistingFile)
    if len(self.filename) > 0:
      self.loadingInProgress = True
      self.buttonEnsite.text = "Cancel Ensite import."
      if not self.logic.readEnsite(self.filename):
        self.addLog("Import failed.")
      self.loadingInProgress = False
      self.logic.abortRequested = False
      self.reenableButtons()
  
  def onButtonCarto(self):
    if self.loadingInProgress:
      self.loadingInProgress = False
      self.logic.abortRequested = True
      self.buttonCarto.text = "Cancelling..."
      self.buttonCarto.enabled = False
      return
    self.clearLog()
    self.filename = qt.QFileDialog.getOpenFileName(self.parent, "Open CARTO 3 file", "", "ZIP archives (*.zip);;All files (*.*)", qt.QFileDialog.ExistingFile)
    if len(self.filename) > 0:
      self.loadingInProgress = True
      self.buttonCarto.text = "Cancel CARTO 3 import."
      if not self.logic.readCarto(self.filename):
        self.addLog("Import failed.")
      self.loadingInProgress = False
      self.logic.abortRequested = False
      self.reenableButtons()
  
  def onButtonRhythmia(self):
    if self.loadingInProgress:
      self.loadingInProgress = False
      self.logic.abortRequested = True
      self.buttonRhythmia.text = "Cancelling..."
      self.buttonRhythmia.enabled = False
      return
    self.clearLog()
    self.filename = qt.QFileDialog.getOpenFileName(self.parent, "Open RHYTHMIA file", "", "RHYTHMIA exported archive (*.000);;All files (*.*)", qt.QFileDialog.ExistingFile)
    if len(self.filename) > 0:
      self.loadingInProgress = True
      self.buttonRhythmia.text = "Cancel RHYTHMIA import."
      if not self.logic.readRhythmia(self.filename):
        self.addLog("Import failed.")
      self.loadingInProgress = False
      self.logic.abortRequested = False
      self.reenableButtons()
  
  def clearLog(self):
    # Clear text in log window
    self.statusLabel.plainText = ''
    self.progressBar.setValue(0)
    slicer.app.processEvents()  # force update
  
  def addLog(self, text):
    # Append text to log window
    self.statusLabel.appendPlainText(text)
    slicer.app.processEvents()  # force update
  
  def updateProgress(self, percent):
    # Update progress bar
    self.progressBar.setValue(percent)
    slicer.app.processEvents()  # force update

################################################################################
# EAMapReaderLogic
#

class EAMapReaderLogic(ScriptedLoadableModuleLogic):
  """ Uses ScriptedLoadableModuleLogic base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """
  def __init__(self):
    ScriptedLoadableModuleLogic.__init__(self)
    self.logCallback = None
    self.progressCallback = None
    self.abortRequested = False
    self.progress = 0
  
  def addLog(self, text):
    logging.info(text)
    if self.logCallback:
      self.logCallback(text)
  
  def updateProgress(self):
    if self.progressCallback:
      self.progressCallback(self.progress)
  
  def getTempDirectoryBase(self):
    tempDir = qt.QDir(slicer.app.temporaryPath)
    fileInfo = qt.QFileInfo(qt.QDir(tempDir), "EAMapReader")
    dirPath = fileInfo.absoluteFilePath()
    qt.QDir().mkpath(dirPath)
    return dirPath
  
  def createTempDirectory(self):
    tempDir = qt.QDir(self.getTempDirectoryBase())
    tempDirName = qt.QDateTime().currentDateTime().toString("yyyyMMdd_hhmmss_zzz")
    fileInfo = qt.QFileInfo(qt.QDir(tempDir), tempDirName)
    dirPath = fileInfo.absoluteFilePath()
    qt.QDir().mkpath(dirPath)
    return dirPath
  
  ################################################################################
  # Model creation 
  #
  
  def mkVtkIdList(self, it):
    vil = vtk.vtkIdList()
    for i in it:
      vil.InsertNextId(int(i))
    return vil
  
  def CreateMesh(self, modelNode, arrayVertices, arrayVertexNormals, arrayTriangles, labelsScalars, arrayScalars):
    # based on https://vtk.org/Wiki/VTK/Examples/Python/DataManipulation/Cube.py
    # modelNode : a vtkMRMLModelNode in the Slicer scene which will hold the mesh
    # arrayVertices : list of triples [[x1,y1,z2], [x2,y2,z2], ... ,[xn,yn,zn]] of vertex coordinates
    # arrayVertexNormals : list of triples [[nx1,ny1,nz2], [nx2,ny2,nz2], ... ] of vertex normals
    # arrayTriangles : list of triples of 0-based indices defining triangles
    # labelsScalars : list of strings such as ["bipolar", "unipolar"] to label the individual scalars data sets
    # arrayScalars : list of n m-tuples for n vertices and m individual scalar sets
    
    # create the building blocks of polydata including data attributes.
    mesh    = vtk.vtkPolyData()
    points  = vtk.vtkPoints()
    normals = vtk.vtkFloatArray()
    polys   = vtk.vtkCellArray()
    
    # load the array data into the respective VTK data structures
    #self.addLog("  Initializing vertices.")
    for i in range(len(arrayVertices)):
      points.InsertPoint(i, arrayVertices[i])
    
    if self.abortRequested: 
      return False
    
    #self.addLog("  Initializing triangles.")
    for i in range(len(arrayTriangles)):
      polys.InsertNextCell(self.mkVtkIdList(arrayTriangles[i]))
    
    if self.abortRequested: 
      return False
    
    # Normals: http://vtk.1045678.n5.nabble.com/Set-vertex-normals-td5734525.html
    # First pre-allocating memory for the vtkDataArray using vtkDataArray::SetNumberOfComponents() and vtkDataArray::SetNumberOfTuples()
    # and then setting the actual values through SetTuple() is orders of magnitude faster than inserting them one-by-one (and allocating memory dynamically)
    # with InsertTuple() 
    normals.SetNumberOfComponents(3)
    normals.SetNumberOfTuples(len(arrayVertexNormals))
    #self.addLog("  Initializing normals.")
    for i in range(len(arrayVertexNormals)):
      normals.SetTuple3(i, arrayVertexNormals[i][0], arrayVertexNormals[i][1], arrayVertexNormals[i][2])
      if self.abortRequested: 
        return False
    
    # put together the mesh object
    # self.addLog("  Building mesh.")
    mesh.SetPoints(points)
    mesh.SetPolys(polys)
    if(len(arrayVertexNormals) == len(arrayVertices)):
      mesh.GetPointData().SetNormals(normals)
    
    if self.abortRequested: 
      return False
    
    # self.addLog("  Adding scalar data.")
    
    # Add scalars
    scalars = []
    for j in range(len(labelsScalars)):
      scalars.append(vtk.vtkFloatArray())
      scalars[j].SetNumberOfComponents(1)
      scalars[j].SetNumberOfTuples(len(arrayScalars))
      for i in range(len(arrayScalars)):
        scalars[j].SetTuple1(i,arrayScalars[i][j])
        if self.abortRequested: 
          return False
      scalars[j].SetName(labelsScalars[j])
      mesh.GetPointData().AddArray(scalars[j])
    
    if self.abortRequested: 
      return False
    
    modelNode.SetAndObservePolyData(mesh)
    self.addLog("Model created.")
    return True
  
  def transformNode(self, node, matrix):
    transform = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLLinearTransformNode')
    transformMatrix = vtk.vtkMatrix4x4()
    transformMatrix.Zero()
    
    for row in range(4):
      for col in range(4): 
        transformMatrix.SetElement(row, col, matrix[row][col])
    
    transform.SetMatrixTransformToParent(transformMatrix) 
    
    # Apply transform to node... 
    node.SetAndObserveTransformNodeID(transform.GetID())    
    # ... and harden it
    transformLogic = slicer.vtkSlicerTransformLogic()
    transformLogic.hardenTransform(node)
    # delete transform node
    slicer.mrmlScene.RemoveNode(transform)
    
  ################################################################################
  # XML parsing helper functions 
  #
  
  def findallRecursive(self, node, element):
    for item in node.findall(element):
      yield item
    for child in node:
      for item in self.findallRecursive(child, element):
        yield item
  
  def TextToFloat(self, text):
    # First remove any leading and trailing spaces and newlines
    leadingNonDigits = "^[^0-9.-]*"
    trailingNonDigits = "[^0-9.-]*$" 
    text = re.sub(leadingNonDigits, "",text)
    text = re.sub(trailingNonDigits, "",text)
    lines = re.split("\n",text)
    numbers = []
    for i in range(len(lines)):
      lines[i] = re.sub(leadingNonDigits, "",lines[i])
      lines[i] = re.sub(trailingNonDigits, "",lines[i])
      lineSplit = re.split("\s+", lines[i])
      #print(lines[i])
      #print(lineSplit)
      thisNumbers = []
      for j in range(len(lineSplit)):
        thisNumbers.append(float(lineSplit[j])) 
      numbers.append(thisNumbers)
    return numbers
  
  ################################################################################
  # Ensite import
  #
  
  def readEnsite(self, filename):
    self.progress = 0
    self.updateProgress()
    if self.abortRequested: 
      return False
    
    self.addLog("Importing Ensite map:")      
    self.addLog("  Parsing file "+filename)
    tree = ET.parse(filename)
    root = tree.getroot()
    
    self.progress = 5
    self.updateProgress()
    if self.abortRequested: 
      return False
    
    volumes = list(self.findallRecursive(root, "Volume"))
    
    self.addLog("  Found "+str(len(volumes))+" volumes(s) in file.")
    self.progress = 10
    self.updateProgress()
    if self.abortRequested: 
      return False
    
    progressSteps = 6
    progressEnd = 100
    progressIncrement = ((progressEnd - self.progress)/progressSteps)/len(volumes)
    
    volumeCounter = 0
    for volume in volumes:
      try:
        plaintext = volume.find("Vertices").text
        vertices = self.TextToFloat(plaintext)
        self.addLog("  Reading volume "+str(volumeCounter)+".")
        self.addLog("  Read "+str(len(vertices))+" vertices.")
        self.progress = self.progress + progressIncrement
        self.updateProgress()
      except AttributeError:
        self.addLog("  ERROR: No vertices found in volume "+str(volumeCounter)+".")
        return False

      if self.abortRequested:  
        return False
      
      try:
        plaintext = volume.find("Map_data").text
        map_data = self.TextToFloat(plaintext)
        
        self.addLog("  Read "+str(len(map_data))+" map data points.")
        no_scalars = False
        self.progress = self.progress + progressIncrement
        self.updateProgress()
      except AttributeError:
        self.addLog("  No map data points (scalars) found in volume "+str(volumeCounter)+".")
        no_scalars = True
      
      if self.abortRequested: 
        return False
      
      try:
        plaintext = volume.find("Normals").text
        vertexnormals = self.TextToFloat(plaintext)
        
        self.addLog("  Read "+str(len(vertexnormals))+" vertex normals.")
        self.progress = self.progress + progressIncrement
        self.updateProgress()
      except AttributeError:
        self.addLog("  ERROR: No vertex normals found in volume "+str(volumeCounter)+".")
        return False

      if self.abortRequested: 
        return False
      
      try:
        plaintext = volume.find("Polygons").text
        triangles_all = self.TextToFloat(plaintext)
        # Change base from 1 to 0
        for i in range(len(triangles_all)):
          for j in range(3):
            triangles_all[i][j] = int(triangles_all[i][j]-1)
      except AttributeError:
        self.addLog("  ERROR: No polygon information found in volume "+str(volumeCounter)+".")
        return False
      
      # Triangles are binned into different "Surfaces of origin" (i.e. models in the file),
      # according to the separate table Surface_of_origin
      
      try:
        plaintext = volume.find("Surface_of_origin").text
        surface_of_origin_1tuple = self.TextToFloat(plaintext) # TextToFloat returns a list of "1-tuples" (lists of length 1): [[1.0], [2.0], [1.0], [0.0], ...]
        surface_of_origin = []
        for i in range(len(surface_of_origin_1tuple)):         # Convert this into a list of lists into a list of integers: [1, 2, 1, 0, ...]
          surface_of_origin.append(surface_of_origin_1tuple[i][0]) 
      
        # Initialize triangles as list of n empty lists, with n being the maximum surface number in surface_of_origin
        triangles = [ [] for _ in range(int(max(surface_of_origin)+1))]   
      
        for i in range(len(surface_of_origin)):
          triangles[int(surface_of_origin[i])].append(triangles_all[i])
        
        self.addLog("  Read "+str(len(triangles_all))+" triangles in "+str(len(triangles))+" separate meshes.")
      except:
        self.addLog("  NOTE: No \"Surface of Origin\" information in file.")
        triangles = [[]]  
        triangles[0]=triangles_all
                  

      self.progress = self.progress + progressIncrement
      self.updateProgress()
      if self.abortRequested: 
        return False
      
      for i in range(len(triangles)):
        meshName = "Ensite_"+str(volumeCounter)+"-"+str(i)
        self.addLog("Creating model "+meshName+":")
        
        modelNode = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLModelNode')

        if not no_scalars:
          names = ["Map data"]
          scalars = map_data
        else:
          names = []
          scalars = []

        if not self.CreateMesh(modelNode, vertices, vertexnormals, triangles[i], names, scalars):
          slicer.mrmlScene.RemoveNode(modelNode) 
          return False
        
        self.progress = self.progress + (2*progressIncrement)/len(triangles)
        self.updateProgress()
        if self.abortRequested: 
          return False
        
        # Ensite mesh coordinates are LPS, Slicer is RAS
        matrixLPStoRAS = [[-1, 0, 0, 0],
                          [ 0,-1, 0, 0],
                          [ 0, 0, 1, 0],
                          [ 0, 0, 0, 1]]
        self.transformNode(modelNode, matrixLPStoRAS)
              
        modelNode.SetName(meshName)
        modelNode.CreateDefaultDisplayNodes() 
      
    self.addLog("Done.")
    self.progress = 100
    self.updateProgress()
    
    return True

  ################################################################################
  # CARTO 3 import 
  #
  
  def readCarto(self, filename):
    self.progress = 0
    self.updateProgress()
    if not zipfile.is_zipfile(filename):
      self.addLog("File is not a valid zip archive: "+filename)
      return False 
    if self.abortRequested: 
      return False
    
    self.addLog("Importing CARTO 3 map:")      
    tempDir = self.createTempDirectory()
    self.addLog("  Extracting archive "+filename+" to "+tempDir)
    
    with zipfile.ZipFile(filename, "r") as cartoArchive:
      fileList = cartoArchive.namelist()
      for singleFile in fileList:
        if singleFile.endswith(".mesh") or singleFile.endswith("_car.txt") or singleFile == "VisiTagExport/Sites.txt":
          cartoArchive.extract(singleFile, tempDir)
        if self.abortRequested:
          shutil.rmtree(tempDir) 
          return False
          
    self.progress = 10
    self.updateProgress()
    
    progressSteps = len(os.listdir(tempDir))
    progressEnd = 100
    progressIncrement = ((progressEnd - self.progress)/progressSteps)
         
    for filename in os.listdir(tempDir):
      if filename.endswith(".mesh"):
        if not self.readCartoMesh(os.path.join(tempDir, filename)):
          shutil.rmtree(tempDir)
          return False
      if filename.endswith("_car.txt"):
        if not self.readCartoPoints(os.path.join(tempDir, filename)):
          shutil.rmtree(tempDir)
          return False
      self.progress = self.progress + progressIncrement
      self.updateProgress()
      if self.abortRequested:
        shutil.rmtree(tempDir) 
        return False
    
    if os.path.exists(os.path.join(tempDir, "VisiTagExport/Sites.txt")):
      if not self.readCartoAblationSites(os.path.join(tempDir, "VisiTagExport/Sites.txt")):
        shutil.rmtree(tempDir)
    
    #Delete temp dir
    self.addLog("Cleaning up temporary files.")
    shutil.rmtree(tempDir)
    
    self.progress = 100
    self.updateProgress()
    self.addLog("Done.")
    
    return True

  def readCartoMesh(self, filename):
    meshName = ntpath.basename(filename)
    self.addLog("Reading "+meshName+":")
    section = "none"
    verticesText = ""
    trianglesText = ""
    scalarsText = ""
    attributesText = ""
    scalarLabels = ""
    
    with open(filename, "r", encoding="latin-1") as filehandle:
      for line in filehandle:
        if self.abortRequested:
          return False
        # Remove trailing newline and trailing and leading spaces
        line = re.sub("[\n]$", "", line)
        line = re.sub("[ ]*$", "", line)
        line = re.sub("^[ ]*", "", line)
        
        if len(line) == 0: # empty line
          continue
        if line[0] == ";": # comment line
          continue  
        if line.find("[GeneralAttributes]") > -1:
          section = "general"
          continue  
        if line.find("[VerticesSection]") > -1:
          section = "vertices"  
          continue  
        if line.find("[TrianglesSection]") > -1:
          section = "triangles" 
          continue  
        if line.find("[VerticesColorsSection]") > -1:
          section = "scalars"
          continue  
        if line.find("[VerticesAttributesSection]") > -1:          
          section = "attributes"          
          continue 
        
        if section == "general":
          # Look for scalar labels
          if line.find("ColorsNames") > -1:
            line = re.sub("^ColorsNames[ ]*=[ ]*", "", line)
            scalarLabels = re.split("\s+",line)
        if section == "vertices":
          # remove line number ("0 =")
          line = re.sub("[0-9]*[ ]*=[ ]*", "", line)
          # add "clean" line to string
          verticesText = verticesText+line+'\n'
        if section == "triangles":
          line = re.sub("[0-9]*[ ]*=[ ]*", "", line)
          trianglesText = trianglesText+line+'\n'
        if section == "scalars":
          line = re.sub("[0-9]*[ ]*=[ ]*", "", line)
          scalarsText = scalarsText+line+'\n'
        if section == "attributes":
          line = re.sub("[0-9]*[ ]*=[ ]*", "", line)
          attributesText = attributesText+line+'\n'
    
    verticesLong = self.TextToFloat(verticesText)
    vertices = []
    vertexnormals = []
    for i in range(len(verticesLong)):
      vertices.append([verticesLong[i][0], verticesLong[i][1], verticesLong[i][2]])
      vertexnormals.append([verticesLong[i][3], verticesLong[i][4], verticesLong[i][5]])
      if self.abortRequested:
        return False
    
    trianglesLong = self.TextToFloat(trianglesText)
    triangles = []
    for i in range(len(trianglesLong)):
      triangles.append([trianglesLong[i][0], trianglesLong[i][1], trianglesLong[i][2]])
      if self.abortRequested:
        return False
      
    if len(scalarsText) > 0:
      scalars = self.TextToFloat(scalarsText)
    else:
      scalars = []
    
    if len(attributesText) > 0:
      attributes = self.TextToFloat(attributesText)   # currently not used
    else:
      attributes = []
    
    self.addLog("  Read "+str(len(vertices))+" vertices, "+str(len(vertexnormals))+" vertex normals, and "+str(len(triangles))+" triangles.")
    self.addLog("  Read "+str(len(scalarLabels))+" sets of scalars: "+str(scalarLabels)+".")
    
    meshName = "CARTOmesh_"+re.sub(".mesh$", "", meshName)
    self.addLog("Creating model "+meshName+":")
    
    modelNode = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLModelNode')
    if not self.CreateMesh(modelNode, vertices, vertexnormals, triangles, scalarLabels, scalars):
      slicer.mrmlScene.RemoveNode(modelNode)
      return False
    
    self.transformCarto(modelNode)
    
    modelNode.SetName(meshName)  
    modelNode.CreateDefaultDisplayNodes()
    
    return True

  def readCartoPoints(self, filename):
    pointsName = ntpath.basename(filename)
    self.addLog("Reading "+pointsName+":")
    
    fiducialsNode = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLMarkupsFiducialNode')
    fiducialsNode.GetMarkupsDisplayNode().SetVisibility(0)
    
    with open(filename, "r") as filehandle:
      for line in filehandle:
        if self.abortRequested:
          return False
        # Remove trailing newline and trailing and leading spaces
        line = re.sub("[\n]$", "", line)
        line = re.sub("[ ]*$", "", line)
        line = re.sub("^[ ]*", "", line)
        if len(line) == 0: # empty line
          continue
        lineElements = re.split("[ \t]*", line)
        if lineElements[0] == "VERSION_5_0" or lineElements[0] == "VERSION_4_0":
          pointsName = lineElements[1]
        if lineElements[0] == "P":
            pointNr = int(lineElements[2])
            pointX = float(lineElements[4]) 
            pointY = float(lineElements[5]) 
            pointZ = float(lineElements[6])  
            unipolar = float(lineElements[10])
            bipolar = float(lineElements[11])
            lat = float(lineElements[12])
            n = fiducialsNode.AddFiducial(pointX, pointY, pointZ)
            fiducialsNode.SetNthControlPointLabel(n, "Point # "+str(pointNr)+" in "+pointsName)
            fiducialsNode.SetNthControlPointDescription(n, "Bipolar "+str(bipolar)+" / Unipolar "+str(unipolar)+" / LAT "+str(lat))
            fiducialsNode.SetNthControlPointLocked(n, 1)
             
    self.transformCarto(fiducialsNode)        
    
    pointsName = "CARTOpoints_"+re.sub("_car.txt$", "", pointsName)
    fiducialsNode.SetName(pointsName)
    fiducialsNode.GetMarkupsDisplayNode().SetTextScale(0)
    fiducialsNode.GetMarkupsDisplayNode().SetVisibility(1)
    
    self.addLog("Created markup fiducials "+pointsName+".")
    fiducialsNode.CreateDefaultDisplayNodes()

    return True

  def readCartoAblationSites(self, filename):
    pointsName = ntpath.basename(filename)
    self.addLog("Reading "+pointsName+":")
    
    fiducialsNode = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLMarkupsFiducialNode')
    fiducialsNode.GetMarkupsDisplayNode().SetVisibility(0)
    
    with open(filename, "r") as filehandle:
      for line in filehandle:
        if self.abortRequested:
          return False
        # Remove trailing newline and trailing and leading spaces
        line = re.sub("[\n]$", "", line)
        line = re.sub("[ ]*$", "", line)
        line = re.sub("^[ ]*", "", line)
        if len(line) == 0: # empty line
          continue
        lineElements = re.split("\s+", line)
        if lineElements[0] == "Session" or lineElements[0] == "VERSION_4_0":
          continue
        pointNr = int(lineElements[2])
        pointX = float(lineElements[3]) 
        pointY = float(lineElements[4]) 
        pointZ = float(lineElements[5])  
        duration = float(lineElements[6])
        avgForce = float(lineElements[7])
        power = float(lineElements[8])
        fti = float(lineElements[9])
        n = fiducialsNode.AddFiducial(pointX, pointY, pointZ)
        fiducialsNode.SetNthControlPointLabel(n, "Ablation site # "+str(pointNr))
        fiducialsNode.SetNthControlPointDescription(n, "FTI "+str(fti)+" ("+str(duration)+" sec, "+str(power)+" W, "+str(avgForce)+" g")
        fiducialsNode.SetNthControlPointLocked(n, 1)
             
    self.transformCarto(fiducialsNode)        
    
    pointsName = "CARTOablationsites"
    fiducialsNode.SetName(pointsName)
    fiducialsNode.GetMarkupsDisplayNode().SetTextScale(0)
    fiducialsNode.GetMarkupsDisplayNode().SetUseGlyphScale(False)
    fiducialsNode.GetMarkupsDisplayNode().SetGlyphSize(6)
    fiducialsNode.GetMarkupsDisplayNode().SetSelectedColor(1,0,0)
    fiducialsNode.GetMarkupsDisplayNode().SetVisibility(1)
    
    self.addLog("Created markup fiducials "+pointsName+".")
    fiducialsNode.CreateDefaultDisplayNodes()
    
    return True



  def transformCarto(self, node):
    # CARTO mesh is in LPS and seems to be additionally rotated 90 deg around the LR axis
    # Transform matrix from CARTO to Slicer is
    # -1.0  0.0  0.0  0.0
    #  0.0  0.0  1.0  0.0
    #  0.0  1.0  0.0  0.0
    #  0.0  0.0  0.0  1.0
  
    matrix = [[-1, 0,  0,  0],
              [0,  0,  1,  0],
              [0,  1,  0,  0],
              [0,  0,  0,  1]]
    self.transformNode(node, matrix) 
  
  ################################################################################
  # RHYTHMIA import
  #
  def readRhythmia(self, filename):
    
    self.progress = 0
    self.updateProgress()
    
    tempDir = self.createTempDirectory()
    filenameStem = os.path.splitext(os.path.basename(filename))[0]   
    archiveConcatenated = os.path.join(tempDir, filenameStem+".ALL")
    print(archiveConcatenated)
    if not self.concatenateRhythmiaFiles(filename, archiveConcatenated):
      shutil.rmtree(tempDir)
      return False 
    
    if not self.expandBinaryPayloadFromRhythmiaArchive(archiveConcatenated , os.path.join(tempDir, "archive.xml"), tempDir):
      shutil.rmtree(tempDir)
      return False 
    
    if not self.processRhythmiaXML(os.path.join(tempDir, "archive.xml"), tempDir):
      shutil.rmtree(tempDir)
      return False      
    
    self.progress = 100  
    self.updateProgress()
    
    # Delete temp dir
    self.addLog("Cleaning up temporary files.")
    shutil.rmtree(tempDir)
    
    self.progress = 100
    self.updateProgress()
    self.addLog("Done.")
    
    return True
  
  def concatenateRhythmiaFiles(self, startfilename, targetfilename):
    # Get all files startfilename.000 , .001, .002, ...
    filePathStem = os.path.splitext(startfilename)[0]
    filesToAdd = []
    i=0
    while(os.path.isfile(filePathStem+"."+str(i).zfill(3))):
      filesToAdd.append(filePathStem+"."+str(i).zfill(3))
      i += 1
    progressIncrement = (20-self.progress) / len(filesToAdd)
    # Merge all these files into one (in the temp dir)
    with open(targetfilename, "wb", 0) as targetfile:
      for fileToAdd in filesToAdd:
        with open(fileToAdd, "rb") as fid:
          self.addLog("Reading file "+fileToAdd+" ...")
          targetfile.write(fid.read())
        self.progress += progressIncrement
        self.updateProgress()
        if self.abortRequested:
          return False
      targetfile.flush()
      os.fsync(targetfile.fileno())
    self.progress = 20
    self.updateProgress()
    return True
            
        
  def expandBinaryPayloadFromRhythmiaArchive(self, archiveFilename, xmlFilename, folder): 
    # Parse the (completed, concatenated) Rhythmia archive archiveFilename and extract the binary chunks
    # into separate files in the directory folder
    # Also, write the remaining XML (stripped from binary data) into xmlFilename       
    
    
    tagBinaryStart = re.compile(b"<inlinedbin .* BIN=[0-9]*>")
    tagBinaryEnd = re.compile(b"</inlinedbin>")
    
    pointer = 0
    xmlBuffer = ""
    binaryFilenamePattern =  "binary"
        
    # We are using a rather rough method here by loading the entire (multi-GB) archive into
    # (virtual) memory as one chunk. If this should cause problems with even larger archives in
    # the future, chunk-wise processing might be an option (caution: expressions spanning chunk boundaries)
    # See e.g. https://stackoverflow.com/questions/29052510/search-string-with-regex-in-large-binary-file-2-gb-or-more
    # and https://stackoverflow.com/questions/14289421/how-to-use-mmap-in-python-when-the-whole-file-is-too-big
    
    readChunkSize = 500 * 1024 * 1024 # 500 MB, arbitrary
    archiveBuffer = bytes("", 'ASCII') # explicite bytes() type cast necessary for Python3 compatability, see https://stackoverflow.com/questions/21689365/python-3-typeerror-must-be-str-not-bytes-with-sys-stdout-write/21689447
    readChunk = ""
    archiveFileSize = os.stat(archiveFilename).st_size
    progressStart = self.progress
    progressEnd = 50
    
    self.addLog("Unpacking archive ... (This can take several minutes and Slicer might appear unresponsive)")    
    with open(archiveFilename, "rb") as archiveFile:
      while True:
        readChunk = archiveFile.read(readChunkSize)   # Read in chunks of 500 MB to allow processing of cancel requests between chunks 
        if len(readChunk) == 0: # End of file
          break
        archiveBuffer += readChunk
        self.progress = progressStart + ((progressEnd-progressStart)*(len(archiveBuffer)/archiveFileSize))
        self.updateProgress() 
        if self.abortRequested:
          return False
    
    self.progress = progressEnd  
    self.updateProgress()
    
    progressStart = self.progress
    progressEnd = 80
            
    binaryFileCounter = 0
    
    while pointer < len(archiveBuffer):
      # locate beginning and end of next opening <inlinedbin> tag
      nextInlinedbinOpening = tagBinaryStart.search(archiveBuffer, pointer)
      
      # next <inlinedbin> tag found
      if nextInlinedbinOpening:
        openingTagStart = nextInlinedbinOpening.start()
        openingTagEnd = nextInlinedbinOpening.end()
      
        # copy everything from current seek pointer till the end of the opening tag
        # to the "clean" XML
        # Note: In Python3, the archiveBuffer is (binary) bytes, but the xmlBuffer is a string --> explicite decoding necessary
        xmlBuffer += archiveBuffer[pointer:openingTagEnd].decode('ASCII')
        
        # locate beginning and end of next closing <inlinedbin> tag, start search at
        # end of opening tag
        nextInlinedbinClosing = tagBinaryEnd.search(archiveBuffer, openingTagEnd)
        if nextInlinedbinClosing: 
          closingTagStart = nextInlinedbinClosing.start()
          closingTagEnd = nextInlinedbinClosing.end()
          
          # write out binary payload
          binaryFileName = binaryFilenamePattern+str(binaryFileCounter).zfill(8)+".dat"
          binaryFileCounter += 1
          with open(os.path.join(folder, binaryFileName), "wb", 0) as binaryFile:
            binaryFile.write(archiveBuffer[openingTagEnd:closingTagStart])
            binaryFile.flush()
            os.fsync(binaryFile.fileno())
          
          # write filename into clean XML
          xmlBuffer += binaryFileName
          
          # set pointer to beginning of closing tag (next search from here)
          pointer = closingTagStart
        else:
          self.addLog("Premature end of archive file (closing </inlinedbin> tag not found)")
          xmlBuffer += archiveBuffer[pointer:].decode('ASCII')
          pointer = pointer = len(archiveBuffer)
          return False
      
      else: # no opening <inlinedbin> found
        # copy everything from current pointer location till end of buffer into clean XML
        xmlBuffer += archiveBuffer[pointer:].decode('ASCII')
        pointer = len(archiveBuffer)
      
      self.progress = progressStart+((progressEnd-progressStart)*(pointer/len(archiveBuffer)))
      self.updateProgress()
      if self.abortRequested:
        return False
      
    # Correct one remaining non-XML-conformant statement:
    # the <inlinedbin> tags contain an attribute declaration like BIN=580 (the number of bytes)
    # However, this should read BIN="580" in order to be standard-conformant
    
    xmlBuffer = re.sub(r'BIN=([0-9]*)', r'BIN="\1"', xmlBuffer)
     
    with open(xmlFilename, "w") as xmlFile:
      xmlFile.write(xmlBuffer)
    
    return True 
  
   # convert voltage values from log(uV) to mV
  def calculateRhythmiaVoltage(self, x):
    return math.exp(x) / 1000
    
  def processRhythmiaXML(self, xmlFilename, folder):
    calculateRhythmiaVoltageVectorized = np.vectorize(self.calculateRhythmiaVoltage)
    matrixRhythmiaToSlicer = [[ 1, 0, 0, 0],
                              [ 0, 0,-1, 0],
                              [ 0, 1, 0, 0],
                              [ 1, 0, 0, 1]]
    
    tree = ET.parse(xmlFilename)
    root = tree.getroot()
    
    patientsList = []
    patients = list(self.findallRecursive(root, "Patient"))
    for patient in patients:
      patProperties = patient.find("PatientInfo").find("Properties")
      if patProperties is not None:
        patID = patProperties.find("PatientID").text
        patName = patProperties.find("NameLast").text+", "+patProperties.find("NameFirst").text
        patientsList.append([patID, patName])
        
        # Create patient in subject hierarchy
        subjectHierarchyNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        sceneRoot = subjectHierarchyNode.GetSceneItemID()
        subjectHierarchyNode.CreateSubjectItem(sceneRoot, patID+" ("+patName+")")
        currentSubjectHierarchyPatientID = subjectHierarchyNode.GetItemChildWithName(sceneRoot, patID+" ("+patName+")")
      
      studies = list(self.findallRecursive(patient, "Study"))
      for study in studies:
        studyName = study.find("Properties").find("Label").text
        
        # Create study in subject hierarchy
        subjectHierarchyNode.CreateStudyItem(currentSubjectHierarchyPatientID, studyName)
        currentSubjectHierarchyStudyID = subjectHierarchyNode.GetItemChildWithName(currentSubjectHierarchyPatientID, studyName)
        
        self.addLog("Processing study \""+studyName+"\" of patient ID "+patID+" ("+patName+")...")
        anatomies = list(self.findallRecursive(study, "Anatomy")) 
        
        for anatomyNumber, anatomy in enumerate(anatomies):
          anatomyName = anatomy.find("Properties").find("Label").text
          if anatomyName == None: 
            anatomyName = "unnamed"+str(anatomyNumber)
          anatomyTransformString = anatomy.find("Transform").text
          anatomyTransformMatrix = [[1, 0, 0, 0],
                                    [0, 1, 0, 0],
                                    [0, 0, 1, 0],
                                    [0, 0, 0, 1]]
          if anatomyTransformString != None:
            anatomyTransformNumbers = re.split("\s+", anatomyTransformString) 
            i = 0
            for row in range(4):
              for col in range(4):
                anatomyTransformMatrix[col][row] = float(anatomyTransformNumbers[i]) 
                i += 1
          scalarLabels = []
          scalarValues = []
          
          meshes = list(self.findallRecursive(anatomy, "Mesh"))
          for mesh in meshes:
            if mesh.find("vertices").find("inlinedbin") is not None:
              # Geometry data exists for this mesh -> read filenames of extracted binary files
              verticesFilename = mesh.find("vertices").find("inlinedbin").text
              verticesLengthBytes = int(mesh.find("vertices").find("inlinedbin").attrib["BIN"])
              trianglesFilename = mesh.find("triangles").find("inlinedbin").text
              trianglesLengthBytes = int(mesh.find("triangles").find("inlinedbin").attrib["BIN"])
              triangleNormalsFilename = mesh.find("triangle_normals").find("inlinedbin").text
              triangleNormalsLengthBytes = int(mesh.find("triangle_normals").find("inlinedbin").attrib["BIN"])
              triangleFlagsFilename = mesh.find("triangle_flags").find("inlinedbin").text
              triangleFlagsLengthBytes = int(mesh.find("triangle_flags").find("inlinedbin").attrib["BIN"])
              
              with open(os.path.join(folder, verticesFilename), "rb") as verticesFile:
                rawBytes = verticesFile.read()
                if len(rawBytes) != verticesLengthBytes:
                  self.addLog("ERROR: Binary data size for vertices does not match. ("+verticesFilename+" : "+str(len(rawBytes))+" read / "+str(verticesLengthBytes)+" Bytes expected)")
                  return False
                vertices = np.array(struct.unpack('<{0}f'.format(int(len(rawBytes)/4)), rawBytes))    # Float32
                vertices = np.reshape(vertices, (-1,6))
                anatomyVertices = np.array(vertices[:, 0:3])
                anatomyVertexnormals = np.array(vertices[:, 3:6])
              
              with open(os.path.join(folder, trianglesFilename), "rb") as trianglesFile:
                rawBytes = trianglesFile.read()
                if len(rawBytes) != trianglesLengthBytes:
                  self.addLog("ERROR: Binary data size for triangles does not match. ("+trianglesFilename+" : "+str(len(rawBytes))+" read / "+str(verticesLengthBytes)+" Bytes expected)")
                  return False
                anatomyTriangles = np.array(struct.unpack('<{0}i'.format(int(len(rawBytes)/4)), rawBytes))  # SignedInt32
                anatomyTriangles = np.reshape(anatomyTriangles, (-1,3))
              
          engineOutputs =  list(self.findallRecursive(anatomy, "EngineOutput"))
          for engineOutput in engineOutputs:
            voltages = list(self.findallRecursive(engineOutput, "Voltage")) 
            activations = list(self.findallRecursive(engineOutput, "Activation")) 
            
            for voltage in voltages:
              if voltage.find("values").find("inlinedbin") is not None:
                scalarFilename = voltage.find("values").find("inlinedbin").text
                scalarLengthBytes = int(voltage.find("values").find("inlinedbin").attrib["BIN"])
                
                with open(os.path.join(folder, scalarFilename), "rb") as scalarFile:
                  rawBytes = scalarFile.read()
                  if len(rawBytes) != scalarLengthBytes:
                    self.addLog("ERROR: Binary data size for electrogram data does not match. ("+scalarFilename+" : "+str(len(rawBytes))+" read / "+str(verticesLengthBytes)+" Bytes expected)")
                    return False
                  scalarLabels.append("Voltage_"+voltage.find("Properties").find("SrcEgmType").text)
                  
                  scalars = np.array(struct.unpack('<{0}f'.format(int(len(rawBytes)/4)), rawBytes))
                 
                  # convert values from log(uV) to mV, using a vectorized function to conveniently iterate over the entire array
                  scalars = calculateRhythmiaVoltageVectorized(scalars)
                  if scalarValues == []:
                    for i in range(len(scalars.tolist())):
                      scalarValues.append([scalars.tolist()[i]])  # Make it a list of lists of length one
                  else:
                    for i in range(len(scalars.tolist())):
                      scalarValues[i].append(scalars.tolist()[i])  # append to the existing lists
            
            for activation in activations:
              if activation.find("values").find("inlinedbin") is not None:
                scalarFilename = activation.find("values").find("inlinedbin").text
                scalarLengthBytes = int(activation.find("values").find("inlinedbin").attrib["BIN"])
                
                with open(os.path.join(folder, scalarFilename), "rb") as scalarFile:
                  rawBytes = scalarFile.read()
                  if len(rawBytes) != scalarLengthBytes:
                    self.addLog("ERROR: Binary data size for electrogram data does not match. ("+scalarFilename+" : "+str(len(rawBytes))+" read / "+str(verticesLengthBytes)+" Bytes expected)")
                    return False
                  scalarLabels.append("LAT_"+activation.find("Properties").find("SrcEgmType").text)
                  
                  scalars = np.array(struct.unpack('<{0}f'.format(int(len(rawBytes)/4)), rawBytes))
                  if scalarValues == []:
                    for i in range(len(scalars.tolist())):
                      scalarValues.append([scalars.tolist()[i]])  # Make it a list of lists of length one
                  else:
                    for i in range(len(scalars.tolist())):
                      scalarValues[i].append(scalars.tolist()[i])  # append to the existing lists
                      
          # Create mesh for this anatomy
          meshName = "RHYTHMIAmesh_"+anatomyName
          self.addLog("Creating model "+meshName+":")
          modelNode = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLModelNode')
          # Insert below correct study in subject hierarchy
          subjectHierarchyNode.CreateItem(currentSubjectHierarchyStudyID, modelNode)
          
          if not self.CreateMesh(modelNode, anatomyVertices.tolist(), anatomyVertexnormals.tolist(), anatomyTriangles.tolist(), scalarLabels, scalarValues):
            slicer.mrmlScene.RemoveNode(modelNode)
            return False
          
          # individual transform saved in the archive (e.g. when segmentations have been aligned on the workstation)
          self.transformNode(modelNode, anatomyTransformMatrix)
          
          # general transform from Rhythmia to Slicer coordinate systems
          self.transformNode(modelNode, matrixRhythmiaToSlicer)
          modelNode.SetName(meshName)  
          modelNode.CreateDefaultDisplayNodes()
        
        pointSets = list(self.findallRecursive(study, "AnnotationPointSet"))
        unnamedCounter = 0
        for pointSet in pointSets:
          pointSetName = pointSet.find("Properties").find("OverrideLabel").text
          points = list(self.findallRecursive(pointSet, "AnnotationPoint"))
          pointsList = []
          for point in points:
            if point.find("Properties").find("OverrideLabel") is not None:
              pointLabel = point.find("Properties").find("OverrideLabel").text
            else:
              if point.find("Properties").find("Label") is not None:
                pointLabel = point.find("Properties").find("Label").text
              else:
                pointSetName = "unnamed_points"+str(unnamedCounter).zfill(2)
                unnamedCounter += 1
            
            pointXYZ = point.find("xyz").text
            pointXYZlist = re.split("\s+", pointXYZ)
            pointsList.append([pointLabel, float(pointXYZlist[0]), float(pointXYZlist[1]),float(pointXYZlist[2])]) 
          
          if(len(pointsList) > 0):
            # Create new Fiducial set here with name pointSetName
            self.addLog("Creating annotation points \""+pointSetName+"\".")
            fiducialNode = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLMarkupsFiducialNode')
            # Put it below study in subject hierarchy and name it
            subjectHierarchyNode.CreateItem(currentSubjectHierarchyStudyID, fiducialNode)
            fiducialNode.SetName(pointSetName) 
            
            # Insert points
            for fiducial in pointsList:
              fidNumber = fiducialNode.AddFiducial(fiducial[1], fiducial[2], fiducial[3])
              fiducialNode.SetNthControlPointLabel(fidNumber, fiducial[0])
              fiducialNode.SetNthControlPointLocked(fidNumber, True)
            
            # match coordinate systems RHYTHMIA -> Slicer
            self.transformNode(fiducialNode, matrixRhythmiaToSlicer)
          
    return True
