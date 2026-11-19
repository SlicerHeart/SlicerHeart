"""Tests of unit and coordinate system conversion of the ImportExportSimulationModel module.

Run from the Slicer Python console:

    import slicer.testing
    slicer.testing.runUnitTest([r"<path>/ImportExportSimulationModel/Testing/Python"], "ImportExportSimulationModelConversionTest")
"""

import vtk

import slicer
import slicer.ScriptedLoadableModule

from ImportExportSimulationModelLib.Units import (
    guessSimulationUnit, LENGTH_QUANTITY, normalizedArrayName, simulationUnitByQuantity,
    unitSystemConversionFactor,
)
from ImportExportSimulationModelLib.MeshArrays import (
    flippedComponentIndices, flippedComponentNames, POINT_LOCATION,
)
from ImportExportSimulationModelLib.MeshConversion import convertMesh


class ImportExportSimulationModelConversionTest(slicer.ScriptedLoadableModule.ScriptedLoadableModuleTest):

    def setUp(self):
        slicer.mrmlScene.Clear()

    def test_NonVectorArrayConversion(self):
        """2-component vectors must be flipped, Q-criterion and unknown 2-component arrays must not."""
        self.delayDisplay("Starting 2-component and Q-criterion conversion test")

        self.assertEqual(flippedComponentNames("Velocity", 2), ["x", "y"])
        self.assertEqual(flippedComponentNames("Displacement", 2), ["x", "y"])
        self.assertEqual(flippedComponentNames("TCoords", 2), [])
        self.assertEqual(flippedComponentNames("SomethingUnknown", 2), [])
        self.assertEqual(flippedComponentNames("Velocity", 2, isFloatingPoint=False), [])
        for arrayName in ("Q-Criterion", "QCriterion", "q_criterion", "fluid_Q-Criterion"):
            for numberOfComponents in (1, 3):
                self.assertEqual(flippedComponentNames(arrayName, numberOfComponents), [], arrayName)

        points = vtk.vtkPoints()
        points.InsertNextPoint(1.0, 2.0, 0.0)
        mesh = vtk.vtkPolyData()
        mesh.SetPoints(points)
        for name, values in (("Velocity", (1.0, 2.0)), ("TCoords", (0.25, 0.5)),
                             ("Q-Criterion", (3.0, 4.0, 5.0))):
            array = vtk.vtkDoubleArray()
            array.SetName(name)
            array.SetNumberOfComponents(len(values))
            array.InsertNextTuple(values)
            mesh.GetPointData().AddArray(array)
        pointData = convertMesh(mesh, {}, True, "mmgs", "mmgs").GetPointData()
        self.assertEqual(pointData.GetArray("Velocity").GetTuple(0), (-1.0, -2.0))
        self.assertEqual(pointData.GetArray("TCoords").GetTuple(0), (0.25, 0.5))
        self.assertEqual(pointData.GetArray("Q-Criterion").GetTuple(0), (3.0, 4.0, 5.0))

        self.delayDisplay("2-component and Q-criterion conversion test passed")

    def test_TensorConversion(self):
        """Stress and strain arrays must be rotated with the coordinate system."""
        self.delayDisplay("Starting tensor conversion test")

        # RAS <-> LPS negates the first two axes, so a tensor component is negated if exactly
        # one of the axes it refers to is one of those two.
        self.assertEqual(flippedComponentNames("Velocity", 3), ["x", "y"])
        self.assertEqual(flippedComponentNames("Stress", 6), ["yz", "xz"])
        self.assertEqual(flippedComponentNames("Stress", 9), ["xz", "yz", "zx", "zy"])
        # Components stored in arrays of their own, one component per array.
        for arrayName, isNegated in (("Stress_xx", False), ("Stress_xy", False),
                                     ("Stress_xz", True), ("Stress_yy", False),
                                     ("Stress_yz", True), ("Stress_zz", False),
                                     ("Strain_xz", True), ("Strain_zx", True),
                                     ("sigma_yz", True), ("StressXZ", True)):
            self.assertEqual(bool(flippedComponentIndices(arrayName, 1)), isNegated, arrayName)
        # Invariants do not depend on the coordinate system.
        for arrayName in ("VonMisesStress", "VonMisesStrain", "PrincipalStress_1",
                          "PrincipalStrain_1", "Pressure", "Jacobian"):
            self.assertEqual(flippedComponentIndices(arrayName, 1), [], arrayName)
        # An integer array is never transformed.
        self.assertEqual(flippedComponentIndices("Stress_xz", 1, isFloatingPoint=False), [])

        # Build a mesh that holds the same tensor in every supported representation.
        tensorComponents = {"xx": 1.0, "yy": 2.0, "zz": 3.0, "xy": 4.0, "yz": 5.0, "xz": 6.0}
        points = vtk.vtkPoints()
        points.InsertNextPoint(0.0, 0.0, 0.0)
        mesh = vtk.vtkPolyData()
        mesh.SetPoints(points)

        for componentName, value in tensorComponents.items():
            array = vtk.vtkDoubleArray()
            array.SetName("Stress_" + componentName)
            array.InsertNextTuple1(value)
            mesh.GetPointData().AddArray(array)

        symmetricTensor = vtk.vtkDoubleArray()
        symmetricTensor.SetName("StressTensor")
        symmetricTensor.SetNumberOfComponents(6)
        # VTK order: XX, YY, ZZ, XY, YZ, XZ
        symmetricTensor.InsertNextTuple([tensorComponents[name]
                                         for name in ("xx", "yy", "zz", "xy", "yz", "xz")])
        mesh.GetPointData().AddArray(symmetricTensor)

        for arrayName, value in (("VonMisesStress", 7.0), ("PrincipalStress_1", 8.0),
                                 ("VonMisesStrain", 0.5), ("PrincipalStrain_1", 0.25)):
            array = vtk.vtkDoubleArray()
            array.SetName(arrayName)
            array.InsertNextTuple1(value)
            mesh.GetPointData().AddArray(array)

        # Convert between coordinate systems only, so that the values are not scaled as well.
        quantities = {}
        convertedMesh = convertMesh(
            mesh, quantities, True, "mmgs", "mmgs")
        pointData = convertedMesh.GetPointData()

        for componentName, value in tensorComponents.items():
            expectedValue = -value if componentName in ("xz", "yz") else value
            self.assertAlmostEqual(pointData.GetArray("Stress_" + componentName).GetTuple1(0),
                                   expectedValue, msg="Stress_" + componentName)

        expectedTensor = [tensorComponents["xx"], tensorComponents["yy"], tensorComponents["zz"],
                          tensorComponents["xy"], -tensorComponents["yz"], -tensorComponents["xz"]]
        self.assertEqual(list(pointData.GetArray("StressTensor").GetTuple(0)), expectedTensor)

        # Von Mises and principal values are invariants: they must not change.
        self.assertAlmostEqual(pointData.GetArray("VonMisesStress").GetTuple1(0), 7.0)
        self.assertAlmostEqual(pointData.GetArray("PrincipalStress_1").GetTuple1(0), 8.0)
        self.assertAlmostEqual(pointData.GetArray("VonMisesStrain").GetTuple1(0), 0.5)
        self.assertAlmostEqual(pointData.GetArray("PrincipalStrain_1").GetTuple1(0), 0.25)

        # Converting back must restore the original values.
        restoredMesh = convertMesh(
            convertedMesh, quantities, True, "mmgs", "mmgs")
        restoredPointData = restoredMesh.GetPointData()
        for componentName, value in tensorComponents.items():
            self.assertAlmostEqual(
                restoredPointData.GetArray("Stress_" + componentName).GetTuple1(0), value)

        # Stress is scaled as a pressure, strain is dimensionless: check that the scaling and the
        # negation are applied together.
        quantities = {(POINT_LOCATION, "Stress_xz"): "pressure",
                      (POINT_LOCATION, "Stress_xx"): "pressure"}
        scaledMesh = convertMesh(
            mesh, quantities, True, "cgs", "mmgs")
        scaledPointData = scaledMesh.GetPointData()
        self.assertAlmostEqual(scaledPointData.GetArray("Stress_xx").GetTuple1(0), 0.1)
        self.assertAlmostEqual(scaledPointData.GetArray("Stress_xz").GetTuple1(0), -0.6)

        self.delayDisplay("Tensor conversion test passed")

    def test_IntegerArrayScaling(self):
        """Scaling an integer array must not disturb the other arrays."""
        self.delayDisplay("Starting integer array scaling test")

        points = vtk.vtkPoints()
        points.InsertNextPoint(0.0, 0.0, 0.0)
        mesh = vtk.vtkPolyData()
        mesh.SetPoints(points)

        for name, arrayType in (("first", vtk.vtkDoubleArray), ("counts", vtk.vtkIntArray),
                                ("last", vtk.vtkDoubleArray)):
            array = arrayType()
            array.SetName(name)
            array.InsertNextTuple1(3)
            mesh.GetPointData().AddArray(array)
        mesh.GetPointData().SetActiveScalars("counts")

        # All three arrays are lengths, so all of them must be scaled by 10 (cm -> mm) exactly
        # once, even though the integer array has to be replaced with a floating-point array.
        quantities = {(POINT_LOCATION, name): LENGTH_QUANTITY
                      for name in ("first", "counts", "last")}
        convertedMesh = convertMesh(
            mesh, quantities, False, "cgs", "mmgs")

        pointData = convertedMesh.GetPointData()
        self.assertEqual(pointData.GetNumberOfArrays(), 3)
        for name in ("first", "counts", "last"):
            self.assertAlmostEqual(pointData.GetArray(name).GetTuple1(0), 30.0)
        self.assertEqual(pointData.GetArray("counts").GetDataType(), vtk.VTK_DOUBLE)
        # The replaced array must remain the active scalars of the mesh.
        self.assertEqual(pointData.GetScalars().GetName(), "counts")
        # The original mesh must not be modified.
        self.assertEqual(mesh.GetPointData().GetArray("first").GetTuple1(0), 3.0)

        self.delayDisplay("Integer array scaling test passed")

    def test_UnitConversionFactors(self):
        self.delayDisplay("Starting unit conversion factor test")

        # Conversion factors from CGS to mm-g-s, computed from the length exponent of each quantity.
        expectedFactors = {
            "length": 10.0,           # 1 cm = 10 mm
            "velocity": 10.0,         # 1 cm/s = 10 mm/s
            "pressure": 0.1,          # 1 dyn/cm2 = 1 g/(cm*s2) = 0.1 g/(mm*s2)
            "density": 1e-3,          # 1 g/cm3 = 0.001 g/mm3
            "dynamicViscosity": 0.1,  # 1 g/(cm*s) = 0.1 g/(mm*s)
            "flowRate": 1000.0,       # 1 cm3/s = 1000 mm3/s
            "force": 10.0,            # 1 dyn = 1 g*cm/s2 = 10 g*mm/s2
            "resistance": 1e-4,       # 1 dyn*s/cm5 = 1 g/(cm4*s) = 1e-4 g/(mm4*s)
            "compliance": 1e4,        # 1 cm5/dyn = 1 cm4*s2/g = 1e4 mm4*s2/g
            "dimensionless": 1.0,
            "time": 1.0,
            "mass": 1.0,
        }
        for quantity, expectedFactor in expectedFactors.items():
            simulationUnit = simulationUnitByQuantity(quantity)
            self.assertEqual(simulationUnit.quantity, quantity)
            factor = unitSystemConversionFactor(simulationUnit.lengthExponent, "cgs", "mmgs")
            self.assertAlmostEqual(factor / expectedFactor, 1.0, places=9)
            # The inverse conversion must restore the original value.
            inverseFactor = unitSystemConversionFactor(simulationUnit.lengthExponent, "mmgs", "cgs")
            self.assertAlmostEqual(factor * inverseFactor, 1.0, places=9)

        self.delayDisplay("Unit conversion factor test passed")

    def test_ArrayNameQuantityGuess(self):
        self.delayDisplay("Starting array name test")

        self.assertEqual(normalizedArrayName("GlobalNodeID"), "global_node_id")
        self.assertEqual(normalizedArrayName("vWSS"), "v_wss")
        self.assertEqual(normalizedArrayName("Q-Criterion"), "q_criterion")
        self.assertEqual(normalizedArrayName("VonMisesStress"), "von_mises_stress")

        # Prefixes and suffixes are ignored: the quantity is recognized wherever it is in the
        # name. Every component of a tensor is therefore recognized as the same quantity.
        for componentName in ("xx", "xy", "xz", "yy", "yz", "zz"):
            self.assertEqual(guessSimulationUnit("Stress_" + componentName).quantity, "pressure")
            self.assertEqual(guessSimulationUnit("Strain_" + componentName).quantity,
                             "dimensionless")
        for arrayName in ("Stress", "Stress_xx", "solid_Stress", "solid_Stress_1",
                          "mean_stress_xy", "VonMisesStress", "PrincipalStress_1",
                          "average_pressure", "vinplane_traction"):
            self.assertEqual(guessSimulationUnit(arrayName).quantity, "pressure", arrayName)
        for arrayName in ("Strain", "Strain_xz", "PrincipalStrain_1", "VonMisesStrain",
                          "mean_strain_xy", "solid_Strain_1"):
            self.assertEqual(guessSimulationUnit(arrayName).quantity, "dimensionless", arrayName)
        for arrayName in ("Velocity", "Velocity_1", "fluid_Velocity", "average_speed"):
            self.assertEqual(guessSimulationUnit(arrayName).quantity, "velocity", arrayName)

        expectedQuantities = {
            # Array names of svFSI/SimVascular results.
            "Velocity": "velocity",
            "Pressure": "pressure",
            "Displacement": "length",
            "Acceleration": "acceleration",
            "WSS": "pressure",
            "vWSS": "pressure",
            "Vorticity": "frequency",
            "Divergence": "frequency",
            "Stress_xx": "pressure",
            "VonMisesStress": "pressure",
            "PrincipalStress_1": "pressure",
            "Strain_xx": "dimensionless",
            "VonMisesStrain": "dimensionless",
            "PrincipalStrain_1": "dimensionless",
            "Jacobian": "dimensionless",
            "Q-Criterion": "dimensionless",
            "GlobalNodeID": "dimensionless",
            "GlobalElementID": "dimensionless",
            "ModelFaceID": "dimensionless",
            "ModelRegionID": "dimensionless",
            "Density": "density",
            "Viscosity": "dynamicViscosity",
            "flow_rate": "flowRate",
            "Area": "area",
            "Time": "time",
            # Camel case names with several words are matched word by word, and so are the
            # same names written with underscores.
            "WallShearStress": "pressure",
            "wall_shear_stress": "pressure",
            "KinematicViscosity": "kinematicViscosity",
            "kinematic_viscosity": "kinematicViscosity",
            "FlowRate": "flowRate",
            # The quantity may be anywhere in the name.
            "average_pressure": "pressure",
            "average_speed": "velocity",
            "vinplane_traction": "pressure",
            # A name that matches no rule must not be scaled.
            "attribute": "dimensionless",
            "SomethingUnknown": "dimensionless",
        }
        for arrayName, expectedQuantity in expectedQuantities.items():
            quantity = guessSimulationUnit(arrayName).quantity
            self.assertEqual(quantity, expectedQuantity,
                             "%s: expected %s, got %s" % (arrayName, expectedQuantity, quantity))

        # A word that is only a part of another word must not match: 'acceleration' contains
        # 'ratio', 'duration' contains 'ratio', 'linear' contains 'area' backwards, and so on.
        self.assertEqual(guessSimulationUnit("Acceleration").quantity, "acceleration")
        self.assertEqual(guessSimulationUnit("Duration").quantity, "time")
        self.assertEqual(guessSimulationUnit("Concentration").quantity, "dimensionless")

        # Integer arrays are never scaled, whatever their name is.
        self.assertEqual(guessSimulationUnit("Velocity", isFloatingPoint=False).quantity,
                         "dimensionless")

        self.delayDisplay("Array name test passed")
