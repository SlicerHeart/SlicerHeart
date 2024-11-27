import os
import xml.etree.ElementTree as ET
import slicer
from slicer.ScriptedLoadableModule import *

class FEBioMeshIO(ScriptedLoadableModule):
    def __init__(self, parent):
        ScriptedLoadableModule.__init__(self, parent)
        parent.title = "FEBio mesh file Reader"
        parent.categories = ["Informatics"]
        parent.dependencies = []
        parent.contributors = ["Andras Lasso (PerkLab, Queen's University)"]
        parent.helpText = """
        This module allows loading mesh consisting of beam elements from FEBio mesh files.
        """
        parent.acknowledgementText = """
        """

class FEBioMeshIOFileReader:
    def __init__(self, parent):
        self.parent = parent

    def description(self):
        return "FEBio mesh file"

    def fileType(self):
        return "FEBioMesh"

    def extensions(self):
        return ["FEBio mesh file (*.feb)"]

    def canLoadFile(self, filePath):
        # Check first if loadable based on file extension
        if not self.parent.supportedNameFilters(filePath):
            return False

        # Check if the file contains nodes without parsing the entire file (it can be slow for large files)
        context = ET.iterparse(filePath, events=("start", "end"))
        for event, elem in context:
            if event == "start" and elem.tag == "node":
                # found "node" element, so this FEBio file probably contains a mesh
                return True
        return False

    def load(self, properties):
        import vtk
        from vtk.util import numpy_support
        import numpy as np
        try:
            filePath = properties["fileName"]

            # Get node base name from filename
            if "name" in properties.keys():
                baseName = properties["name"]
            else:
                baseName = os.path.splitext(os.path.basename(filePath))[0]
                baseName = slicer.mrmlScene.GenerateUniqueName(baseName)

            # Parse the XML file
            tree = ET.parse(filePath)
            root = tree.getroot()

            # Extract nodes
            nodes = []
            for node in root.findall(".//Nodes/node"):
                coords = list(map(float, node.text.split(',')))
                nodes.append(coords)

            # Convert nodes to a NumPy array
            nodes_array = np.array(nodes)

            # Convert the NumPy array to a VTK array
            vtk_nodes_array = numpy_support.numpy_to_vtk(num_array=nodes_array, deep=True)

            # Create vtkPoints object and set the VTK array as its data
            points = vtk.vtkPoints()
            points.SetData(vtk_nodes_array)

            # Extract elements
            elements = []
            for elem in root.findall(".//Elements/elem"):
                ids = list(map(int, elem.text.split(',')))
                elements.append([2] + [id - 1 for id in ids])  # Prepend the number of points in the line (2)

            # Convert elements to a NumPy array
            elements_array = np.array(elements, dtype=np.int64).flatten()

            # Create vtkCellArray object and set the VTK array as its data
            lines = vtk.vtkCellArray()
            vtk_elements_array = numpy_support.numpy_to_vtkIdTypeArray(elements_array, deep=True)
            lines.SetCells(len(elements), vtk_elements_array)

            # Create vtkPolyData object and set points and lines
            polydata = vtk.vtkPolyData()
            polydata.SetPoints(points)
            polydata.SetLines(lines)

            # Add the model to the scene
            loadedNode = slicer.modules.models.logic().AddModel(polydata)

        except Exception as e:
            import traceback

            traceback.print_exc()
            errorMessage = f"Failed to read file: {str(e)}"
            self.parent.userMessages().AddMessage(vtk.vtkCommand.ErrorEvent, errorMessage)
            return False

        self.parent.loadedNodes = [loadedNode.GetID()]
        return True
