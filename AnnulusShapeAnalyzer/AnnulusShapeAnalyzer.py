import csv
import logging
import os
import sys
import vtk, qt, ctk, slicer
from slicer.ScriptedLoadableModule import *
from HeartValveBatchAnalysis.annulus_shape_analysis import *
from HeartValveLib.ValveModel import rotationMatrixToEulerAngles
import math
import numpy as np
from vtk.util.numpy_support import numpy_to_vtk, vtk_to_numpy


class AnnulusShapeAnalyzer(ScriptedLoadableModule):
    """Uses ScriptedLoadableModule base class, available at:
    https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
    """

    def __init__(self, parent):
        ScriptedLoadableModule.__init__(self, parent)
        parent.title = "Annulus Shape Analyzer"
        parent.categories = ["Cardiac"]
        parent.dependencies = []
        parent.contributors = ["Ye Han (Kitware, Inc.), Andras Lasso (PerkLab)"]
        parent.helpText = """
            Annulus Shape Analyzer
            """
        parent.acknowledgementText = """
            This work was supported by NIH R01HL153166 (PI. Matthew Jolley, 
            Computer Modeling of the Tricuspid Valve in Hypoplastic Left Heart Syndrome)
            """
        slicer.app.connect("startupCompleted()", self.registerSampleData)

    @staticmethod
    def registerSampleData():
        import SampleData
        iconsPath = os.path.join(os.path.dirname(__file__), 'Resources/Icons')

        SampleData.SampleDataLogic.registerCustomSampleDataSource(
            category='SlicerHeart',
            sampleName='AnnulusShapeAnalyzer',
            thumbnailFileName=os.path.join(iconsPath, 'AnnulusShapeAnalyzer.png'),
            uris=['https://github.com/SlicerHeart/SlicerHeart/releases/download/TestingData/AnnulusShapeAnalyzer.zip'],
            checksums=['SHA256:698b493099721a9639f48044780ab271bd1dfd51ca1f4fefccc3755ef23d28a1'],
            fileNames=['AnnulusShapeAnalyzer.zip'],
        )


class AnnulusShapeAnalyzerWidget(ScriptedLoadableModuleWidget):
    """Uses ScriptedLoadableModuleWidget base class, available at:
    https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
    """

    def __init__(self, parent=None):
        """
        Called when the user opens the module the first time and the widget is initialized.
        """
        ScriptedLoadableModuleWidget.__init__(self, parent)

    def setup(self):
        """
        Called when the user opens the module the first time and the widget is initialized.
        """
        ScriptedLoadableModuleWidget.setup(self)
        self.logic = AnnulusShapeAnalyzerLogic()

        # ---- Widget Setup ----
        # Load file
        uiWidget = slicer.util.loadUI(self.resourcePath('UI/AnnulusShapeAnalyzer.ui'))
        self.layout.addWidget(uiWidget)
        self.ui = slicer.util.childWidgetVariables(uiWidget)
        self.pathLineEdit_loadPopulationFile = self.ui.pathLineEdit_loadPopulationFile
        self.pushButton_loadPopulationFile = self.ui.pushButton_loadPopulationFile
        self.progressBar_processPopulationFile = self.ui.progressBar_processPopulationFile
        self.progressBar_processPopulationFile.setValue(0)
        self.progressBar_processPopulationFile.setHidden(True)
        self.label_processPopulationFile = self.ui.label_processPopulationFile
        self.label_processPopulationFile.setHidden(True)
        self.pushButton_processPopulationFile = self.ui.pushButton_processPopulationFile
        self.checkBox_normalizeContours = self.ui.checkBox_normalizeContours
        self.checkBox_normalizeContours.setChecked(True)
        self.checkBox_alignContours = self.ui.checkBox_alignContours
        self.checkBox_alignContours.setChecked(True)
        self.pushButton_showMeanShape = self.ui.pushButton_showMeanShape
        self.comboBox_procrustes = self.ui.comboBox_procrustes
        self.pushButton_visualizeProcrustes = self.ui.pushButton_visualizeProcrustes

        self.tableWidget_population = self.ui.tableWidget_population
        self.tableWidget_population.setColumnCount(4)
        self.tableWidget_population.setColumnWidth(0, 90)
        self.tableWidget_population.setColumnWidth(1, 120)
        self.tableWidget_population.setColumnWidth(2, 120)
        self.tableWidget_population.horizontalHeader().setStretchLastSection(True)
        self.tableWidget_population.setHorizontalHeaderLabels(["(Ref.) Valve", "Annulus Phases",
                                                               "Principal Labels", "All Labels"])

        # PCA
        self.collapsibleGroupBox_calculatePCA = self.ui.collapsibleGroupBox_calculatePCA
        self.spinBox_minimumExplainedVariance = self.ui.spinBox_minimumExplainedVariance
        self.spinBox_minimumExplainedVariance.setRange(0, 100)
        self.spinBox_minimumExplainedVariance.setValue(95)
        self.spinBox_maximumNumberOfEigenvalues = self.ui.spinBox_maximumNumberOfEigenvalues
        self.spinBox_maximumNumberOfEigenvalues.setRange(0, 10)
        self.spinBox_maximumNumberOfEigenvalues.setValue(3)
        self.pushButton_evaluateModels = self.ui.pushButton_evaluateModels
        self.pushButton_PCAResetSliders = self.ui.pushButton_PCAResetSliders
        self.comboBox_valveType = self.ui.comboBox_valveType
        self.comboBox_annulusPhase = self.ui.comboBox_annulusPhase
        self.gridLayout_PCASliders = self.ui.gridLayout_PCASliders

        # Regression
        self.CollapsibleGroupBox_shapeRegression = self.ui.CollapsibleGroupBox_shapeRegression
        self.pathLineEdit_demographicsFilePath = self.ui.pathLineEdit_demographicsFilePath
        self.pushButton_performRegression = self.ui.pushButton_performRegression
        self.pushButton_regressionResetSliders = self.ui.pushButton_regressionResetSliders
        self.tableWidget_demographics = self.ui.tableWidget_demographics
        self.tableWidget_demographics.horizontalHeader().setStretchLastSection(True)
        self.pushButton_loadAssociatedDemographics = self.ui.pushButton_loadAssociatedDemographics
        self.comboBox_regressionValveType = self.ui.comboBox_regressionValveType
        self.comboBox_regressionAnnulusPhase = self.ui.comboBox_regressionAnnulusPhase
        self.gridLayout_regressionSliders = self.ui.gridLayout_regressionSliders

        # Compare Curves
        self.CollapsibleGroupBox_compareCurve = self.ui.CollapsibleGroupBox_compareCurve
        self.comboBox_compareCurve1 = self.ui.comboBox_compareCurve1
        self.comboBox_compareCurve2 = self.ui.comboBox_compareCurve2
        self.comboBox_compareValveType = self.ui.comboBox_compareValveType
        self.comboBox_compareAnnularPhase = self.ui.comboBox_compareAnnularPhase
        self.pushButton_compareCurves = self.ui.pushButton_compareCurves
        self.tableWidget_compareResults = self.ui.tableWidget_compareResults
        self.tableWidget_compareResults.setColumnCount(2)
        self.tableWidget_compareResults.setColumnWidth(0, 150)
        self.tableWidget_compareResults.horizontalHeader().setStretchLastSection(True)
        self.tableWidget_compareResults.setHorizontalHeaderLabels(["Distance Metrics", "Value"])

        # Compute strain and curvature
        self.CollapsibleGroupBox_strainCurvature = self.ui.CollapsibleGroupBox_strainCurvature
        self.comboBox_strainCurvatureCurve = self.ui.comboBox_strainCurvatureCurve
        self.comboBox_strainCurvatureReferencePhase = self.ui.comboBox_strainCurvatureReferencePhase
        self.comboBox_strainCurvatureDeformedPhase = self.ui.comboBox_strainCurvatureDeformedPhase
        self.comboBox_strainCurvatureValveType = self.ui.comboBox_strainCurvatureValveType
        self.comboBox_strainCurvatureVisualize = self.ui.comboBox_strainCurvatureVisualize
        self.comboBox_strainCurvatureResampling = self.ui.comboBox_strainCurvatureResampling
        self.comboBox_strainCurvatureTheta0 = self.ui.comboBox_strainCurvatureTheta0
        self.pushButton_computeStrainCurvature = self.ui.pushButton_computeStrainCurvature

        # ---- Connection ----
        self.pushButton_loadPopulationFile.connect("clicked()", self.onLoadPopulationFile)
        self.pushButton_processPopulationFile.connect("clicked()", self.onProcessPopulationFile)
        self.pushButton_showMeanShape.connect("clicked()", self.onCalculateMeanShape)
        self.pushButton_visualizeProcrustes.connect("clicked()", self.onVisualizeProcrustes)
        self.pushButton_evaluateModels.connect("clicked()", self.onEvaluateModels)
        self.pushButton_PCAResetSliders.connect("clicked()", self.onPCAResetSliders)
        self.pushButton_loadAssociatedDemographics.connect("clicked()", self.onLoadAssociatedDemographics)
        self.pushButton_performRegression.connect("clicked()", self.onPerformRegressionOnSelectedVariables)
        self.pushButton_regressionResetSliders.connect("clicked()", self.onRegressionResetSliders)
        self.pushButton_compareCurves.connect("clicked()", self.onCompareCurves)
        self.pushButton_computeStrainCurvature.connect("clicked()", self.onComputeStrainCurvature)
        self.comboBox_strainCurvatureValveType.connect("currentTextChanged(QString)", self.onStrainCurvatureValveTypeChanged)

        # disable buttons/boxes before loading/processing input file
        self.checkBox_normalizeContours.setEnabled(False)
        self.checkBox_alignContours.setEnabled(False)
        self.pushButton_showMeanShape.setEnabled(False)
        self.pushButton_visualizeProcrustes.setEnabled(False)
        self.collapsibleGroupBox_calculatePCA.setEnabled(False)
        self.CollapsibleGroupBox_shapeRegression.setEnabled(False)
        self.CollapsibleGroupBox_compareCurve.setEnabled(False)
        self.CollapsibleGroupBox_strainCurvature.setEnabled(False)

    def onAnnulusPhaseChanged(self):
        new_text = None
        for annulus_phase in self.annulus_phase_list:
            if annulus_phase.plainText != self.current_annulus_phase:
                self.current_annulus_phase = annulus_phase.plainText
                new_text = annulus_phase.toHtml()
                break
        for annulus_phase in self.annulus_phase_list:
            if annulus_phase.plainText != self.current_annulus_phase:
                annulus_phase.disconnect("textChanged()", self.onAnnulusPhaseChanged)
                annulus_phase.setHtml(new_text)
                annulus_phase.connect("textChanged()", self.onAnnulusPhaseChanged)

    def onStrainCurvatureValveTypeChanged(self, text):
        self.comboBox_strainCurvatureTheta0.clear()
        self.comboBox_strainCurvatureTheta0.addItems(self.logic.all_labels[text])

    def onLoadPopulationFile(self):
        self.annulus_phase_list = self.logic.loadPopulationFile(
            self.pathLineEdit_loadPopulationFile.currentPath, self.tableWidget_population)
        self.current_annulus_phase = self.annulus_phase_list[0].plainText

        # Sync the annulus phase across all valve types and set reference checkbox to be mutually exclusive
        number_of_valve_types = len(self.annulus_phase_list)
        if number_of_valve_types == 1:
            self.checkBox_normalizeContours.setEnabled(True)
            self.checkBox_alignContours.setChecked(False)
            self.checkBox_alignContours.setEnabled(False)
        elif number_of_valve_types >= 2:
            for annulus_phase in self.annulus_phase_list:
                annulus_phase.connect("textChanged()", self.onAnnulusPhaseChanged)
            self.checkBox_normalizeContours.setEnabled(True)
            self.checkBox_alignContours.setEnabled(True)
        else:
            logging.error("Wrong number of valve types from the input file")
            return
        logging.info("File loaded successfully")
        self.pathLineEdit_loadPopulationFile.addCurrentPathToHistory()

    def onProcessPopulationFile(self):
        self.logic.processPopulationFile(self.tableWidget_population,
                                         self.checkBox_normalizeContours,
                                         self.checkBox_alignContours,
                                         self.label_processPopulationFile,
                                         self.progressBar_processPopulationFile)

        self.comboBox_annulusPhase.clear()
        self.comboBox_annulusPhase.addItems(
            self.tableWidget_population.cellWidget(0, 1).plainText.split(","))
        self.comboBox_valveType.clear()
        self.comboBox_valveType.addItems(self.logic.valve_types)

        self.comboBox_regressionAnnulusPhase.clear()
        self.comboBox_regressionAnnulusPhase.addItems(
            self.tableWidget_population.cellWidget(0, 1).plainText.split(","))
        self.comboBox_regressionValveType.clear()
        self.comboBox_regressionValveType.addItems(self.logic.valve_types)

        self.comboBox_compareAnnularPhase.clear()
        self.comboBox_compareAnnularPhase.addItems(
            self.tableWidget_population.cellWidget(0, 1).plainText.split(","))
        self.comboBox_compareValveType.clear()
        self.comboBox_compareValveType.addItems(self.logic.valve_types)

        self.comboBox_procrustes.clear()
        self.comboBox_procrustes.addItems(
            self.tableWidget_population.cellWidget(0, 1).plainText.split(","))

        self.comboBox_compareCurve1.clear()
        self.comboBox_compareCurve1.addItems(["mean", "pca", "regression"])
        self.comboBox_compareCurve1.addItems(self.logic.annulus_filenames)

        self.comboBox_compareCurve2.clear()
        self.comboBox_compareCurve2.addItems(["mean", "pca", "regression"])
        self.comboBox_compareCurve2.addItems(self.logic.annulus_filenames)

        self.comboBox_strainCurvatureCurve.clear()
        self.comboBox_strainCurvatureCurve.addItems(["mean"])
        self.comboBox_strainCurvatureCurve.addItems(self.logic.annulus_filenames)
        self.comboBox_strainCurvatureValveType.clear()
        self.comboBox_strainCurvatureValveType.addItems(self.logic.valve_types)
        self.comboBox_strainCurvatureReferencePhase.clear()
        self.comboBox_strainCurvatureReferencePhase.addItems(
            self.tableWidget_population.cellWidget(0, 1).plainText.split(","))
        self.comboBox_strainCurvatureDeformedPhase.clear()
        self.comboBox_strainCurvatureDeformedPhase.addItems(
            self.tableWidget_population.cellWidget(0, 1).plainText.split(","))
        self.comboBox_strainCurvatureVisualize.clear()
        self.comboBox_strainCurvatureResampling.clear()
        self.comboBox_strainCurvatureResampling.addItems(["laplacian", "theta"])
        self.comboBox_strainCurvatureVisualize.addItems(["strain", "absolute curvature", "relative curvature"])

        self.pushButton_showMeanShape.setEnabled(True)
        self.pushButton_visualizeProcrustes.setEnabled(True)
        self.collapsibleGroupBox_calculatePCA.setEnabled(True)
        self.CollapsibleGroupBox_shapeRegression.setEnabled(True)
        self.CollapsibleGroupBox_compareCurve.setEnabled(True)
        self.CollapsibleGroupBox_strainCurvature.setEnabled(True)

    def onCalculateMeanShape(self):
        self.logic.showMeanShape()

    def onVisualizeProcrustes(self):
        # SPV
        self.logic.visualizeProcrustes(self.comboBox_procrustes.currentText)

    def onEvaluateModels(self):
        self.logic.evaluateModels(self.comboBox_valveType.currentText,
                                  self.comboBox_annulusPhase.currentText,
                                  self.spinBox_minimumExplainedVariance.value,
                                  self.spinBox_maximumNumberOfEigenvalues.value,
                                  self.gridLayout_PCASliders)

    def onPCAResetSliders(self):
        self.logic.pcaResetSliders()

    def onLoadAssociatedDemographics(self):
        self.logic.loadAssociatedDemographics(self.pathLineEdit_demographicsFilePath, self.tableWidget_demographics)

    def onPerformRegressionOnSelectedVariables(self):
        self.logic.performRegressionOnSelectedVariables(self.comboBox_regressionValveType.currentText,
                                                        self.comboBox_regressionAnnulusPhase.currentText,
                                                        self.tableWidget_demographics,
                                                        self.gridLayout_regressionSliders)

    def onRegressionResetSliders(self):
        self.logic.regressionResetSliders()

    def onCompareCurves(self):
        self.logic.compareCurves(self.comboBox_compareCurve1.currentText,
                                 self.comboBox_compareCurve2.currentText,
                                 self.comboBox_compareValveType.currentText,
                                 self.comboBox_compareAnnularPhase.currentText,
                                 self.tableWidget_compareResults)

    def onComputeStrainCurvature(self):
        self.logic.computeStrainCurvature(self.comboBox_strainCurvatureCurve.currentText,
                                          self.comboBox_strainCurvatureValveType.currentText,
                                          self.comboBox_strainCurvatureReferencePhase.currentText,
                                          self.comboBox_strainCurvatureDeformedPhase.currentText,
                                          self.comboBox_strainCurvatureVisualize.currentText,
                                          self.comboBox_strainCurvatureResampling.currentText,
                                          self.comboBox_strainCurvatureTheta0.currentText)

    def getUI(self, objectName):
        """ Functions to recovery the widget in the .ui file
        """
        return slicer.util.findChild(self.widget, objectName)

    def cleanup(self):
        pass

    # function called each time that the user "enter" in Diagnostic Index interface
    def enter(self):
        # TODO
        pass

    # function called each time that the user "exit" in Diagnostic Index interface
    def exit(self):
        # TODO
        pass


class AnnulusShapeAnalyzerLogic(ScriptedLoadableModuleLogic):

    def __init__(self):
        super().__init__()
        self.csv_filename = None
        self.valve_types = []
        self.reference_valve_index = None
        self.principal_labels = {}  # must be 4 labels, define annulus coordinate system axes
        self.all_labels = {}  # used for annulus alignment, all annulus contour labels can be used if there are more
        self.annulus_phases = None
        self.scale_factors = None
        self.normalized_annulus_to_valve1_first_phase = None
        self.annulus_filenames = []
        self.number_of_annulus_segments = {}
        self.number_of_points_per_segment = None
        self.stop_on_warning = None
        self.filenameWithoutExtension = None
        self.shNode = None
        self.shRootFolderId = {}
        self.annulus_to_world_transform_node = {}
        self.all_aligned_annulus_point_coordinates = {}
        self.aligned_landmark_points = {}
        self.progress_bar = None
        # mean
        self.mean_nodes = {}
        self.mean_landmark_points_fiducials_nodes = {}
        # pca
        self.pca_filter = None
        self.pca_annulus_point_coordinates = None
        self.pca_valve_type = None
        self.pca_phase = None
        self.pca_nodes = []
        self.pca_grid_layout = None
        self.pca_labels = []
        self.pca_deviation_sliders = []
        self.pca_variance_ratio = []
        self.pca_landmark_points_fiducials_node = None
        self.pca_table_nodes = []
        # regression
        self.regression_variables = {}
        self.regression_annulus_point_coordinates = None
        self.regression_valve_type = None
        self.regression_phase = None
        self.regression_nodes = []
        self.regression_grid_layout = None
        self.regression_labels = []
        self.regression_sliders = []
        self.regression_landmark_points_fiducials_node = None
        # compare curves
        self.compare_nodes1 = []
        self.compare_nodes2 = []
        self.compare_landmark_points_fiducials_node1 = None
        self.compare_landmark_points_fiducials_node2 = None
        self.compare_distance_node = None
        self.compare_color_node = None
        # compute strain and curvature
        self.reference_nodes = []
        self.deformed_nodes = []
        self.reference_landmark_points_fiducials_node = None
        self.deformed_landmark_points_fiducials_node = None
        self.strain_curvature_color_node = None

    def clear(self):
        if len(self.shRootFolderId) != 0:
            for valve_type in self.valve_types:
                self.shNode.RemoveItem(self.shRootFolderId[valve_type])
        self.csv_filename = None
        self.valve_types = []
        self.reference_valve_index = None
        self.principal_labels = {}  # must be 4 labels, define annulus coordinate system axes
        self.all_labels = {}  # used for annulus alignment, all annulus contour labels can be used if there are more
        self.annulus_phases = None
        self.scale_factors = None
        self.normalized_annulus_to_valve1_first_phase = None
        self.annulus_filenames = []
        self.number_of_annulus_segments = {}
        self.number_of_points_per_segment = None
        self.stop_on_warning = None
        self.filenameWithoutExtension = None
        self.shNode = None
        self.shRootFolderId = {}
        self.annulus_to_world_transform_node = {}
        self.all_aligned_annulus_point_coordinates = {}
        self.aligned_landmark_points = {}
        self.progress_bar = None
        # mean
        self.clear_mean()
        # pca
        self.clear_pca()
        # regression
        self.regression_variables = {}
        self.clear_regression()
        # compare curves
        self.clear_compare()
        # strain and curvature
        self.clear_strain_curvature()

    def loadPopulationFile(self, csv_file_path, table_widget):
        self.clear()
        self.csv_filename = csv_file_path
        # check valve types and phases in the input file
        annulus_phases = get_unique_column_values(self.csv_filename, "Phase")
        annulus_phases_str = annulus_phases[0]
        for annulus_phase in annulus_phases[1:]:
            annulus_phases_str += ',' + annulus_phase
        valve_types = get_unique_column_values(self.csv_filename, "Valve")

        # fill in table values with default labels
        default_principal_labels = {"mitral": "A,AL,P,PM",
                                    "aortic": "R,A,L,P",
                                    "cavc": "R,MA,L,MP",
                                    "tricuspid": "S,A,L,P"}
        default_all_labels = {"mitral": "A,AL,P,PM",
                              "aortic": "R,A,L,P",
                              "cavc": "R,RA,MA,LA,L,LP,MP,RP",
                              "tricuspid": "S,A,L,P"}

        number_of_valve_types = len(valve_types)
        table_widget.setRowCount(number_of_valve_types)
        annulus_phase_list = []
        valve_group = qt.QButtonGroup()
        for index, valve_type in enumerate(valve_types):
            if valve_type in default_principal_labels.keys():
                principal_labels = qt.QTextEdit(default_principal_labels[valve_type])
                all_labels = qt.QTextEdit(default_all_labels[valve_type])
            else:
                principal_labels = qt.QTextEdit("")
                all_labels = qt.QTextEdit("")
            principal_labels.setAlignment(qt.Qt.AlignCenter)
            all_labels.setAlignment(qt.Qt.AlignCenter)

            valve_radiobutton = qt.QRadioButton(valve_type)
            valve_group.addButton(valve_radiobutton)
            annulus_phase = qt.QTextEdit(annulus_phases_str)
            annulus_phase.setAlignment(qt.Qt.AlignCenter)
            annulus_phase_list.append(annulus_phase)

            table_widget.setCellWidget(index, 0, valve_radiobutton)
            table_widget.setCellWidget(index, 1, annulus_phase)
            table_widget.setCellWidget(index, 2, principal_labels)
            table_widget.setCellWidget(index, 3, all_labels)

        valve_group.buttons()[0].setChecked(True)
        return annulus_phase_list

    def processPopulationFile(self, table_widget, normalize_contours, align_contours, progress_label, progress_bar):
        number_valve_types = table_widget.rowCount
        self.valve_types = []
        for i in range(number_valve_types):
            if table_widget.cellWidget(i, 0).isChecked():
                self.reference_valve_index = i
            valve_type = table_widget.cellWidget(i, 0).text
            self.valve_types.append(valve_type)
            self.principal_labels[valve_type] = table_widget.cellWidget(i, 2).plainText.split(",")
            self.all_labels[valve_type] = table_widget.cellWidget(i, 3).plainText.split(",")
            if len(self.principal_labels[valve_type]) != len(set(self.principal_labels[valve_type])) or \
                    len(self.all_labels[valve_type]) != len(set(self.all_labels[valve_type])):
                logging.error("Duplicate elements found in {0} valve's labels".format(valve_type))

        self.annulus_phases = table_widget.cellWidget(0, 1).plainText.split(",")

        self.progress_bar = progress_bar
        progress_label.setHidden(False)
        self.progress_bar.setHidden(False)
        if normalize_contours.isChecked():
            progress_label.setText("Normalizing contours:")
            self.scale_factors = compute_scale_factors(self.csv_filename,
                                                       valve_type=self.valve_types[self.reference_valve_index],
                                                       annulus_phases=self.annulus_phases,
                                                       progress_function=self.progress_function)
        else:
            self.scale_factors = None

        if align_contours.isChecked():
            for i in range(number_valve_types):
                if i != self.reference_valve_index:
                    valve_type_1 = self.valve_types[self.reference_valve_index]
                    valve_type_2 = self.valve_types[i]
                    progress_label.setText("Computing relative poses:")
                    normalized_annulus_to_valve1_first_phase = get_normalized_annulus_to_valve1_first_phase(
                        self.csv_filename,
                        principal_labels_1=self.principal_labels[valve_type_1],
                        valve_type_1=valve_type_1,
                        principal_labels_2=self.principal_labels[valve_type_2],
                        valve_type_2=valve_type_2,
                        annulus_phases=self.annulus_phases,
                        scale_factors=self.scale_factors,
                        progress_function=self.progress_function)
                    if self.normalized_annulus_to_valve1_first_phase is None:
                        self.normalized_annulus_to_valve1_first_phase = normalized_annulus_to_valve1_first_phase
                    else:
                        # self.normalized_annulus_to_valve1_first_phase[valve_type_1] = \
                        #     normalized_annulus_to_valve1_first_phase[valve_type_1]
                        self.normalized_annulus_to_valve1_first_phase[valve_type_2] = \
                            normalized_annulus_to_valve1_first_phase[valve_type_2]

                    np.set_printoptions(precision=4, suppress=True)
                    for annulus_phase in self.annulus_phases:
                        mean_annulus_2_to_mean_annulus_1_transform = np.dot(np.linalg.inv(
                            self.normalized_annulus_to_valve1_first_phase[valve_type_1][annulus_phase]),
                            self.normalized_annulus_to_valve1_first_phase[valve_type_2][annulus_phase])
                        logging.info("{0} phase: {1}->{2} translation [mm] = {3}".format(
                            annulus_phase, valve_type_1, valve_type_2,
                            mean_annulus_2_to_mean_annulus_1_transform[0:3, 3]))
                        logging.info("{0} phase: {1}->{2} rotation [deg] = {3}".format(
                            annulus_phase, valve_type_1, valve_type_2,
                            180.0 / math.pi * rotationMatrixToEulerAngles(
                                mean_annulus_2_to_mean_annulus_1_transform[0:3, 0:3])))
        else:
            self.normalized_annulus_to_valve1_first_phase = None

        self.annulus_filenames = get_unique_column_values(self.csv_filename, 'Filename')
        if self.annulus_phases is None:
            # if user does not provide phases then process all phases
            annulus_phases = get_unique_column_values(self.csv_filename, 'Phase')
        elif type(self.annulus_phases) == str:
            # if user provides a simple string then convert it to a single-element list
            self.annulus_phases = [self.annulus_phases]

        for valve_type in self.valve_types:
            self.number_of_annulus_segments[valve_type] = len(self.all_labels[valve_type])
        self.number_of_points_per_segment = 30
        self.stop_on_warning = False

        # Create subject hierarchy and folders for each valve type
        self.filenameWithoutExtension = os.path.splitext(os.path.basename(self.csv_filename))[0]
        self.shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)

        for valve_type in self.valve_types:
            self.shRootFolderId[valve_type] = self.shNode.CreateFolderItem(self.shNode.GetSceneItemID(),
                                                                           '{0} {1} contours'.format(
                                                                               self.filenameWithoutExtension,
                                                                               valve_type))
            self.shNode.SetItemExpanded(self.shRootFolderId[valve_type], True)
        self.annulus_to_world_transform_node = {}

        # Compute aligned annulus points, landmarks and transforms
        for annulus_phase in self.annulus_phases:
            for valve_type in self.valve_types:
                logging.info('Processing {0} valve {1} phase'.format(valve_type, annulus_phase))
                progress_label.setText('Processing {0} valve {1} phase'.format(valve_type, annulus_phase))
                slicer.app.processEvents()
                self.scale_and_align_annulus(valve_type, annulus_phase, self.progress_function)
        logging.info("Finished processing input file")
        progress_label.setHidden(True)
        self.progress_bar.setHidden(True)
        slicer.app.processEvents()

    def progress_function(self, current_step, total_steps):
        self.progress_bar.setValue(current_step / total_steps * 100)

    def scale_and_align_annulus(self, valve_type, annulus_phase, progress_function):
        type_phase = "{0} {1}".format(valve_type, annulus_phase)  # for internal dictionary storage only
        transform_node_name = "Annulus pose {0} {1}".format(valve_type, annulus_phase)

        # Get all annulus contours for this phase
        all_ordered_resampled_annulus_point_coordinates = np.array([]).reshape([0, 3])
        number_of_filenames = len(self.annulus_filenames)
        for index, annulus_filename in enumerate(self.annulus_filenames):
            logging.debug('Annulus: {0} - {1}'.format(annulus_filename, annulus_phase))
            progress_function(index, number_of_filenames)
            try:
                [annulus_point_coordinates, labels] = get_annulus_contour_points(self.csv_filename, annulus_filename,
                                                                                 annulus_phase, valve_type)
                if self.scale_factors is not None:
                    annulus_point_coordinates *= self.scale_factors[annulus_filename]
                [ordered_annulus_point_coordinates, ordered_labels] = order_annulus_contour_points(
                    annulus_point_coordinates, labels, self.all_labels[valve_type])
                ordered_resampled_annulus_point_coordinates = resample_annulus_contour_points(
                    ordered_annulus_point_coordinates, ordered_labels, self.all_labels[valve_type],
                    self.number_of_points_per_segment)
                all_ordered_resampled_annulus_point_coordinates = np.concatenate(
                    [all_ordered_resampled_annulus_point_coordinates, ordered_resampled_annulus_point_coordinates])
            except Exception as e:
                import traceback
                logging.debug(traceback.format_exc())
                logging.warning(
                    "Skipping {0} valve {1} phase - {2}: {3}".format(valve_type, annulus_phase, annulus_filename, e))
                if self.stop_on_warning:
                    return False
                continue

        if all_ordered_resampled_annulus_point_coordinates.shape[0] == 0:
            logging.warning(
                "Skipping {0} valve {1} phase completely: no valid contour was found".format(valve_type, annulus_phase))
            return

        all_annulus_point_coordinates = \
            all_ordered_resampled_annulus_point_coordinates.reshape(
                (-1, self.number_of_annulus_segments[valve_type] * self.number_of_points_per_segment, 3))

        # Correspondence between points in annulus points is already established by resampling based on landmarks.
        # For alignment of the contours we use all the points to minimize difference between all the points (not just
        # between 4-6 landmark points).
        # PCA confirms that this leads to better alignment (less PCA modes can describe same amount of variance).
        annulus_to_mean_annulus_transforms = get_annulus_to_mean_annulus_transforms(all_annulus_point_coordinates)
        self.all_aligned_annulus_point_coordinates[type_phase] = align_annulus_contours(
            all_annulus_point_coordinates,
            annulus_to_mean_annulus_transforms)

        # Landmark points
        landmark_points = \
            all_annulus_point_coordinates[:,
            range(0, self.number_of_annulus_segments[valve_type] * self.number_of_points_per_segment,
                  self.number_of_points_per_segment), :]
        self.aligned_landmark_points[type_phase] = \
            self.all_aligned_annulus_point_coordinates[type_phase][:,
            range(0, self.number_of_annulus_segments[valve_type] * self.number_of_points_per_segment,
                  self.number_of_points_per_segment), :]

        # Compute normalization transform, which puts centroid of the mean annulus into the origin and aligns
        # axes based on principal labels
        annulus_to_world_transform = np.eye(4)
        if (self.principal_labels[valve_type] is not None) and (
                self.normalized_annulus_to_valve1_first_phase is not None):
            # Get the 4 principal landmarks of the mean contour
            try:
                principal_landmark_positions = np.zeros([4, 3])
                for principal_landmark_index, principal_label in enumerate(self.principal_labels[valve_type]):
                    landmark_index = self.all_labels[valve_type].index(principal_label)
                    mean_landmark_position = np.mean(self.aligned_landmark_points[type_phase][:, landmark_index, :],
                                                     axis=0)
                    principal_landmark_positions[principal_landmark_index, :] = mean_landmark_position

                world_to_normalized_transform = get_world_to_normalized_transform(principal_landmark_positions)
                annulus_to_world_transform = np.dot(
                    self.normalized_annulus_to_valve1_first_phase[valve_type][annulus_phase],
                    world_to_normalized_transform)
            except Exception as e:
                import traceback
                logging.debug(traceback.format_exc())
                logging.warning(
                    "Skipping pose normalization for {0} valve {1} phase - {2}".format(valve_type, annulus_phase,
                                                                                       e))
                if self.stop_on_warning:
                    return False

        annulus_to_world_transform_vtk = vtk.vtkMatrix4x4()
        for row in range(3):
            for col in range(4):
                annulus_to_world_transform_vtk.SetElement(row, col, annulus_to_world_transform[row, col])

        self.annulus_to_world_transform_node[transform_node_name] = slicer.mrmlScene.AddNewNodeByClass(
            "vtkMRMLTransformNode", transform_node_name)
        self.annulus_to_world_transform_node[transform_node_name].SetMatrixTransformToParent(
            annulus_to_world_transform_vtk)
        self.shNode.SetItemParent(
            self.shNode.GetItemByDataNode(self.annulus_to_world_transform_node[transform_node_name]),
            self.shRootFolderId[valve_type])

    def draw_contour_and_landmarks(self,
                                   annulus_point_coordinates,
                                   color,
                                   radius,
                                   name,
                                   valve_type,
                                   transform_node_name,
                                   landmark_points):
        # Draw contour
        contour_nodes = createTubeModelFromPointArray(annulus_point_coordinates,
                                                      color=color,
                                                      radius=radius,
                                                      name=name,
                                                      keepGeneratorNodes=True)  # allow changing radius
        contour_nodes[1].GetDisplayNode().SetVisibility(1)
        for node in contour_nodes:
            if node.IsA('vtkMRMLTransformableNode'):
                node.SetAndObserveTransformNodeID(self.annulus_to_world_transform_node[transform_node_name].GetID())
                self.shNode.SetItemParent(self.shNode.GetItemByDataNode(node), self.shRootFolderId[valve_type])

        # Draw landmarks
        landmark_points_fiducials_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsFiducialNode",
                                                                             name + " landmarks")
        landmark_points_fiducials_node.SetAndObserveTransformNodeID(
            self.annulus_to_world_transform_node[transform_node_name].GetID())
        landmark_points_fiducials_node.CreateDefaultDisplayNodes()
        landmark_points_fiducials_display_node = landmark_points_fiducials_node.GetDisplayNode()
        # mean_landmark_points_fiducials_display_node.SetTextScale(0.1)
        landmark_points_fiducials_display_node.PointLabelsVisibilityOn()
        landmark_points_fiducials_display_node.SetColor(color)
        landmark_points_fiducials_display_node.SetUseGlyphScale(False)
        landmark_points_fiducials_display_node.SetGlyphSize(radius * 3)
        self.shNode.SetItemParent(self.shNode.GetItemByDataNode(landmark_points_fiducials_node),
                                  self.shRootFolderId[valve_type])
        for landmark_index, landmark_name in enumerate(self.all_labels[valve_type]):
            landmark_position = landmark_points[landmark_index, :]
            fid_index = landmark_points_fiducials_node.AddFiducial(landmark_position[0],
                                                                   landmark_position[1],
                                                                   landmark_position[2],
                                                                   landmark_name)
            landmark_points_fiducials_node.SetNthFiducialSelected(fid_index, False)

        return contour_nodes, landmark_points_fiducials_node

    def showMeanShape(self):
        meanTubeRadius = 0.1
        meanColors = {"ES": [1, 0, 0], "MS": [0, 1, 0], "ED": [0, 0, 1], "MD": [0, 1, 1]}

        self.clear_mean()
        for annulus_phase in self.annulus_phases:
            for valve_type in self.valve_types:
                self.showIndividualMeanShape(valve_type, annulus_phase, meanColors, meanTubeRadius)
        logging.info('Processing is completed')

        slicer.app.layoutManager().setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutOneUp3DView)
        slicer.util.resetThreeDViews()

        # Zoom in
        layoutManager = slicer.app.layoutManager()
        for threeDViewIndex in range(layoutManager.threeDViewCount):
            view = layoutManager.threeDWidget(threeDViewIndex).threeDView()
            renderer = view.renderWindow().GetRenderers().GetItemAsObject(0)
            renderer.ResetCamera()
            # Zoom in some more
            renderer.GetActiveCamera().Dolly(1.9)
            renderer.ResetCameraClippingRange()
            # Hide view labels, box, set background color
            view.mrmlViewNode().SetAxisLabelsVisible(False)
            view.mrmlViewNode().SetBoxVisible(False)

        # Make markup letters smaller
        for markupsDisplayNode in slicer.util.getNodesByClass("vtkMRMLMarkupsDisplayNode"):
            if markupsDisplayNode.GetTextScale() > 0:
                markupsDisplayNode.SetTextScale(3.0)

    def showIndividualMeanShape(self, valve_type, annulus_phase, mean_colors, mean_tube_radius):
        logging.info('Showing {0} valve {1} phase'.format(valve_type, annulus_phase))
        slicer.app.processEvents()

        type_phase = "{0} {1}".format(valve_type, annulus_phase)
        transform_node_name = "Annulus pose {0} {1}".format(valve_type, annulus_phase)

        # Draw mean contour and landmarks
        mean_annulus_point_coordinates = np.mean(self.all_aligned_annulus_point_coordinates[type_phase], axis=0)
        mean_landmark_points = np.mean(self.aligned_landmark_points[type_phase], axis=0)

        self.mean_nodes[type_phase], self.mean_landmark_points_fiducials_nodes[type_phase] = \
            self.draw_contour_and_landmarks(annulus_point_coordinates=mean_annulus_point_coordinates,
                                            color=mean_colors[annulus_phase],
                                            radius=mean_tube_radius,
                                            name=valve_type + ' ' + annulus_phase + ' mean',
                                            valve_type=valve_type,
                                            transform_node_name=transform_node_name,
                                            landmark_points=mean_landmark_points)

    def clear_mean(self):
        if len(self.mean_nodes) != 0:
            for nodes in self.mean_nodes.values():
                slicer.mrmlScene.RemoveNode(nodes[2])
                slicer.mrmlScene.RemoveNode(nodes[0])
                slicer.mrmlScene.RemoveNode(nodes[1])
            self.mean_nodes = {}

        if len(self.mean_landmark_points_fiducials_nodes) != 0:
            for node in self.mean_landmark_points_fiducials_nodes.values():
                slicer.mrmlScene.RemoveNode(node)
            self.mean_landmark_points_fiducials_nodes = {}

    def visualizeProcrustes(self, annulus_phase):
        if not hasattr(slicer.modules, 'shapepopulationviewer'):
            slicer.util.messageBox("This modules requires Shape Population Viewer (SPV) module. "
                                   "Install SPV and restart Slicer if you need to use this function.")
            return

        individualTubeRadius = 0.1
        individualColors = {"ES": [0.5, 0, 0], "MS": [0, 0.5, 0], "ED": [0, 0, 0.5], "MD": [0, 0.5, 0.5]}

        for case_index in range(len(self.annulus_filenames)):
            annulus_name = self.annulus_filenames[case_index] + " " + annulus_phase
            append = vtk.vtkAppendPolyData()

            # Visualize both annuli in one window
            for valve_type in self.valve_types:
                type_phase = "{0} {1}".format(valve_type, annulus_phase)
                transform_node_name = "Annulus pose {0} {1}".format(valve_type, annulus_phase)
                nodes = createTubeModelFromPointArray(
                    self.all_aligned_annulus_point_coordinates[type_phase][case_index],
                    color=individualColors[annulus_phase],
                    radius=individualTubeRadius,
                    name=annulus_name)

                for node in nodes:
                    if node.IsA('vtkMRMLTransformableNode'):
                        transform = vtk.vtkTransformPolyDataFilter()
                        transform.SetTransform(
                            self.annulus_to_world_transform_node[transform_node_name].GetTransformToParent())
                        transform.SetInputData(node.GetPolyData())
                        transform.Update()
                        append.AddInputData(transform.GetOutput())

                for landmark_index, landmark_name in enumerate(self.all_labels[valve_type]):
                    sphere = vtk.vtkSphereSource()
                    sphere.SetCenter(self.aligned_landmark_points[type_phase][case_index, landmark_index, 0],
                                     self.aligned_landmark_points[type_phase][case_index, landmark_index, 1],
                                     self.aligned_landmark_points[type_phase][case_index, landmark_index, 2])
                    sphere.SetRadius(individualTubeRadius * 3)
                    sphere.Update()
                    transform = vtk.vtkTransformPolyDataFilter()
                    transform.SetTransform(
                        self.annulus_to_world_transform_node[transform_node_name].GetTransformToParent())
                    transform.SetInputData(sphere.GetOutput())
                    transform.Update()
                    append.AddInputData(transform.GetOutput())

                # clean up
                for node in nodes:
                    slicer.mrmlScene.RemoveNode(node)

            append.Update()
            slicer.modules.shapepopulationviewer.widgetRepresentation().loadModel(append.GetOutput(), annulus_name)
        slicer.util.selectModule(slicer.modules.shapepopulationviewer)

    def evaluateModels(self, valve_type, annulus_phase, min_explained_variance, max_number_of_eigenvalues, grid_layout):
        self.clear_pca()
        self.pca_grid_layout = grid_layout
        self.pca_valve_type = valve_type
        self.pca_type_phase = "{0} {1}".format(valve_type, annulus_phase)
        self.pca_transform_node_name = "Annulus pose {0} {1}".format(valve_type, annulus_phase)

        individualTubeRadius = 0.1
        individualColors = {"ES": [0.5, 0, 0], "MS": [0, 0.5, 0], "ED": [0, 0, 0.5], "MD": [0, 0.5, 0.5]}

        slicer.app.processEvents()

        # Convert annulus points to multiblock data set (PCA filter requires that input format)
        annulus_points_multiblock = vtk.vtkMultiBlockDataSet()
        number_of_cases = len(self.annulus_filenames)
        annulus_points_multiblock.SetNumberOfBlocks(number_of_cases)
        for case_index in range(number_of_cases):
            points_polydata = createPolyDataFromPointArray(
                self.all_aligned_annulus_point_coordinates[self.pca_type_phase][case_index])
            annulus_points_multiblock.SetBlock(case_index, points_polydata)

        # Calculate pca
        self.pca_filter = vtk.vtkPCAAnalysisFilter()
        self.pca_filter.SetInputData(annulus_points_multiblock)
        self.pca_filter.Update()

        params = vtk.vtkFloatArray()
        params.SetNumberOfComponents(1)
        params.SetNumberOfTuples(max_number_of_eigenvalues)
        for mode_index in range(max_number_of_eigenvalues):
            params.SetTuple1(mode_index, 0)

        points_polydata = createPolyDataFromPointArray(
            self.all_aligned_annulus_point_coordinates[self.pca_type_phase][0])
        self.pca_filter.GetParameterisedShape(params, points_polydata)
        pca_annulus_point_coordinates = getPointArrayFromPolyData(points_polydata)

        variances = self.pca_filter.GetEvals()
        total_variance = 0.0
        for i in range(variances.GetNumberOfValues()):
            total_variance += variances.GetValue(i)
        for i in range(variances.GetNumberOfValues()):
            self.pca_variance_ratio.append(variances.GetValue(i) / total_variance)
        logging.info("Total variance: " + str(total_variance))

        pca_landmark_points = pca_annulus_point_coordinates[
                              range(0,
                                    self.number_of_annulus_segments[valve_type] * self.number_of_points_per_segment,
                                    self.number_of_points_per_segment), :]

        self.pca_nodes, self.pca_landmark_points_fiducials_node = \
            self.draw_contour_and_landmarks(annulus_point_coordinates=pca_annulus_point_coordinates,
                                            color=individualColors[annulus_phase],
                                            radius=individualTubeRadius,
                                            name=valve_type + ' ' + annulus_phase + ' pca',
                                            valve_type=valve_type,
                                            transform_node_name=self.pca_transform_node_name,
                                            landmark_points=pca_landmark_points)

        # Create and connect widget for interactive visualization
        for i in range(max_number_of_eigenvalues):
            # Create the variance ratio label
            label = qt.QLabel()
            label.setText(str(i + 1) + ': ' + "{:.2f} %".format(self.pca_variance_ratio[i] * 100))
            label.setAlignment(qt.Qt.AlignCenter)
            self.pca_labels.append(label)
            self.pca_grid_layout.addWidget(label, i + 1, 0)

            # Create the slider
            slider = ctk.ctkSliderWidget()
            slider.minimum = -3
            slider.maximum = 3
            slider.value = 0
            slider.decimals = 2
            slider.singleStep = 0.01
            slider.pageStep = 0.2
            self.pca_deviation_sliders.append(slider)
            self.pca_grid_layout.addWidget(slider, i + 1, 1)

            # Connect
            slider.valueChanged.connect(self.pcaUpdateShape)

        # Plot PCA figure, partially borrowed from SVA
        total_variance = 0
        number_of_variance = 0
        for ratio in self.pca_variance_ratio:
            total_variance += ratio
            number_of_variance += 1
            if total_variance >= (min_explained_variance / 100):
                break

        variance_table_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode", "PCA variance table")
        table = variance_table_node.GetTable()
        table.Initialize()

        level_min_explained_variance = np.ones(number_of_variance) * min_explained_variance
        level_min_explained_variance = numpy_to_vtk(level_min_explained_variance.ravel(),
                                                    deep=True,
                                                    array_type=vtk.VTK_FLOAT)
        evr = np.array(self.pca_variance_ratio)[0:number_of_variance].flatten() * 100
        sumevr = np.cumsum(evr)
        evr = numpy_to_vtk(evr.ravel(), deep=True, array_type=vtk.VTK_FLOAT)
        sumevr = numpy_to_vtk(sumevr.ravel(), deep=True, array_type=vtk.VTK_FLOAT)
        x = np.arange(1, number_of_variance + 1).flatten()
        x = numpy_to_vtk(x.ravel(), deep=True, array_type=vtk.VTK_FLOAT)

        level_min_explained_variance.SetName("level{0}%".format(min_explained_variance))
        x.SetName("Component")
        evr.SetName("ExplainedVarianceRatio")
        sumevr.SetName("SumExplainedVarianceRatio")

        table.AddColumn(x)
        table.AddColumn(evr)
        table.AddColumn(sumevr)
        table.AddColumn(level_min_explained_variance)

        min_explained_variance_plot_series = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLPlotSeriesNode",
                                                                                "Level {0}%".format(
                                                                                    min_explained_variance))
        min_explained_variance_plot_series.SetAndObserveTableNodeID(variance_table_node.GetID())
        min_explained_variance_plot_series.SetXColumnName("Component")
        min_explained_variance_plot_series.SetYColumnName("level{0}%".format(min_explained_variance))
        min_explained_variance_plot_series.SetPlotType(slicer.vtkMRMLPlotSeriesNode.PlotTypeScatter)
        min_explained_variance_plot_series.SetMarkerStyle(slicer.vtkMRMLPlotSeriesNode.MarkerStyleNone)
        min_explained_variance_plot_series.SetColor(1, 0, 0)

        sumevr_plot_series = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLPlotSeriesNode", "Sum variance (%)")
        sumevr_plot_series.SetAndObserveTableNodeID(variance_table_node.GetID())
        sumevr_plot_series.SetXColumnName("Component")
        sumevr_plot_series.SetYColumnName("SumExplainedVarianceRatio")
        sumevr_plot_series.SetPlotType(slicer.vtkMRMLPlotSeriesNode.PlotTypeScatter)
        sumevr_plot_series.SetColor(1, 0, 1)

        evr_plot_series = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLPlotSeriesNode", "Variance (%)")
        evr_plot_series.SetAndObserveTableNodeID(variance_table_node.GetID())
        evr_plot_series.SetXColumnName("Component")
        evr_plot_series.SetYColumnName("ExplainedVarianceRatio")
        evr_plot_series.SetPlotType(slicer.vtkMRMLPlotSeriesNode.PlotTypeScatterBar)
        evr_plot_series.SetColor(0, 0, 1)

        plot_chart_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLPlotChartNode", "PCA variance plot chart")
        plot_chart_node.AddAndObservePlotSeriesNodeID(evr_plot_series.GetID())
        plot_chart_node.AddAndObservePlotSeriesNodeID(sumevr_plot_series.GetID())
        plot_chart_node.AddAndObservePlotSeriesNodeID(min_explained_variance_plot_series.GetID())
        plot_chart_node.SetTitle('Explained Variance Ratio (%)')
        plot_chart_node.SetXAxisTitle('Component')
        plot_chart_node.SetYAxisTitle('Explained Variance Ratio (%)')

        self.pca_table_nodes.append(variance_table_node)
        self.pca_table_nodes.append(evr_plot_series)
        self.pca_table_nodes.append(sumevr_plot_series)
        self.pca_table_nodes.append(min_explained_variance_plot_series)
        self.pca_table_nodes.append(plot_chart_node)

        # Select chart in plot view
        layout_manager = slicer.app.layoutManager()
        layout_manager.setLayout(36)
        plot_widget = layout_manager.plotWidget(0)
        plot_view_node = plot_widget.mrmlPlotViewNode()
        plot_view_node.SetPlotChartNodeID(plot_chart_node.GetID())

    def clear_pca(self):
        self.pca_filter = None
        self.pca_annulus_point_coordinates = []
        self.pca_variance_ratio = []
        self.pca_valve_type = None
        self.pca_phase = None

        if self.pca_grid_layout is not None:
            self.pca_grid_layout = None

        if len(self.pca_nodes) != 0:
            slicer.mrmlScene.RemoveNode(self.pca_nodes[2])
            slicer.mrmlScene.RemoveNode(self.pca_nodes[0])
            slicer.mrmlScene.RemoveNode(self.pca_nodes[1])
            self.pca_nodes = []

        for label in self.pca_labels:
            label.deleteLater()
        self.pca_labels = []

        for slider in self.pca_deviation_sliders:
            slider.deleteLater()
        self.pca_deviation_sliders = []

        if self.pca_landmark_points_fiducials_node is not None:
            slicer.mrmlScene.RemoveNode(self.pca_landmark_points_fiducials_node)
            self.pca_landmark_points_fiducials_node = None

        if len(self.pca_table_nodes) != 0:
            for table_node in self.pca_table_nodes:
                slicer.mrmlScene.RemoveNode(table_node)
            self.pca_table_nodes = []

    def pcaResetSliders(self):
        for slider in self.pca_deviation_sliders:
            slider.reset()

    def pcaUpdateShape(self):
        params = vtk.vtkFloatArray()
        params.SetNumberOfComponents(1)
        params.SetNumberOfTuples(len(self.pca_deviation_sliders))
        for mode_index, slider in enumerate(self.pca_deviation_sliders):
            params.SetTuple1(mode_index, slider.value)

        points_polydata = createPolyDataFromPointArray(
            self.all_aligned_annulus_point_coordinates[self.pca_type_phase][0])
        self.pca_filter.GetParameterisedShape(params, points_polydata)
        point_node = self.pca_nodes[1]
        point_node.GetPolyData().SetPoints(points_polydata.GetPoints())

        pca_annulus_point_coordinates = getPointArrayFromPolyData(points_polydata)
        pca_landmark_points = pca_annulus_point_coordinates[range(0,
                                                                  self.number_of_annulus_segments[self.pca_valve_type] *
                                                                  self.number_of_points_per_segment,
                                                                  self.number_of_points_per_segment), :]

        for landmark_index, landmark_name in enumerate(self.all_labels[self.pca_valve_type]):
            pca_landmark_position = pca_landmark_points[landmark_index, :]
            self.pca_landmark_points_fiducials_node.SetNthFiducialPosition(landmark_index,
                                                                           pca_landmark_position[0],
                                                                           pca_landmark_position[1],
                                                                           pca_landmark_position[2])

    def loadAssociatedDemographics(self, demographics_file_path, table_widget):
        self.regression_variables = {}
        self.clear_regression()

        logging.info("Loading Demographics...")
        with open(demographics_file_path.currentPath, 'r') as csv_file:
            table_reader = csv.reader(csv_file)
            file_header = next(table_reader)
            file_name_idx = file_header.index("Filename")
            raw_regression_variables = {}

            # Save rows
            for row in table_reader:
                if row[file_name_idx] in self.annulus_filenames:
                    raw_regression_variables[row[file_name_idx]] = row

            if len(raw_regression_variables) < len(self.annulus_filenames):
                logging.error("Demographics file does not contain all the loaded annulus contours")
                csv_file.close()
                return

            # Get rows with valid float values
            for index, header in enumerate(file_header):
                try:
                    self.regression_variables[header] = []
                    for filename in self.annulus_filenames:
                        self.regression_variables[header].append(float(raw_regression_variables[filename][index]))
                except ValueError:
                    del self.regression_variables[header]

            logging.info("{0} regression variables.".format(len(self.regression_variables)))
            table_widget.setRowCount(len(self.regression_variables))
            table_widget.setColumnCount(2)
            table_widget.setHorizontalHeaderLabels(["Feasible Variables", "Values"])
            table_widget.setColumnWidth(0, 150)
            idx = 0
            for key, value in self.regression_variables.items():
                check_box_item = qt.QTableWidgetItem()
                check_box_item.setText(key)
                check_box_item.setCheckState(qt.Qt.Unchecked)
                table_widget.setItem(idx, 0, check_box_item)
                table_widget.setCellWidget(idx, 1, qt.QLabel(str(value)))
                idx += 1
        logging.info("Loading finished.")

    def performRegressionOnSelectedVariables(self, valve_type, annulus_phase, table_widget, grid_layout):
        # Linear regression with quadratic formulation
        # n: number of regression variables
        # m: number of samples in the dataset
        # p: number of point position variables in an annulus contour
        # Y[mxp]: all point positions in the annulus contour
        # X[mx(n+1)] = [1, x1, x2, … , xn]: vectorized user selected input variables
        # W[(n+1)⨉p] = [w0, w1, w2, … ,wn]: vectorized weights
        # minimize one point position component y[mx1] w.r.t w[(n+1)x1]:
        # |y - Xw|^2 = (y - Xw)^T(y - Xw) = w^T(X^TX)w - 2y^TXw + y^Ty
        # solution: w = (X^TX)^(-1)(X^Ty)
        # solution for minimizing multiple output Y w.r.t. W: W = (X^TX)^(-1)(X^TY)
        # interpolation scheme: y_new[1⨉p]= x_new[1⨉(n+1)]W

        logging.info("Begin performing regression...")
        self.clear_regression()
        self.regression_grid_layout = grid_layout
        self.regression_valve_type = valve_type
        self.regression_type_phase = "{0} {1}".format(valve_type, annulus_phase)
        self.regression_transform_node_name = "Annulus pose {0} {1}".format(valve_type, annulus_phase)

        individualTubeRadius = 0.1
        individualColors = {"ES": [0.5, 0, 0], "MS": [0, 0.5, 0], "ED": [0, 0, 0.5], "MD": [0, 0.5, 0.5]}

        slicer.app.processEvents()

        # Get selected regression variables
        selected_variables = {}
        for i in range(table_widget.rowCount):
            item = table_widget.item(i, 0)
            if item.checkState() == qt.Qt.Checked:
                selected_variables[item.text()] = self.regression_variables[item.text()]

        if len(selected_variables) == 0:
            logging.error("None of variables has been selected")
            return
        elif len(selected_variables) >= len(self.annulus_filenames):
            logging.error("Number of selected variables should be less than the number of input annuli")
            return

        # Concatenate input and output variables into X and Y
        n = len(selected_variables)
        m = len(self.annulus_filenames)
        X = np.ones((m, 1))
        for x in selected_variables.values():
            X = np.concatenate((X, np.array([x]).T), axis=1)

        Y = np.ndarray(shape=(0, self.all_aligned_annulus_point_coordinates[self.regression_type_phase][0].size))
        for y in self.all_aligned_annulus_point_coordinates[self.regression_type_phase]:
            Y = np.concatenate((Y, y.flatten()[np.newaxis, :]), axis=0)

        self.regression_W = np.linalg.solve(X.T @ X, X.T @ Y)

        # Create and connect widget for interactive visualization
        i = 0
        x_new = np.ones((1, n + 1))
        for key, variable in selected_variables.items():
            # Create the variance ratio label
            label = qt.QLabel(key)
            label.setAlignment(qt.Qt.AlignCenter)
            self.regression_labels.append(label)
            self.regression_grid_layout.addWidget(label, i + 1, 0)

            # Create the slider
            slider = ctk.ctkSliderWidget()
            slider.minimum = min(variable)
            slider.maximum = max(variable)
            variable_range = slider.maximum - slider.minimum
            slider.value = slider.minimum + 0.5 * variable_range
            slider.decimals = 2
            slider.singleStep = 0.01
            slider.pageStep = 0.2
            self.regression_sliders.append(slider)
            self.regression_grid_layout.addWidget(slider, i + 1, 1)

            # Connect
            slider.valueChanged.connect(self.regressionUpdateShape)

            # update params
            x_new[0, i + 1] = slider.value
            i += 1

        # Draw regression contour and landmarks
        regression_annulus_point_coordinates = (x_new @ self.regression_W).reshape((-1, 3))
        regression_landmark_points = regression_annulus_point_coordinates[
                                     range(0,
                                           self.number_of_annulus_segments[
                                               valve_type] * self.number_of_points_per_segment,
                                           self.number_of_points_per_segment), :]

        self.regression_nodes, self.regression_landmark_points_fiducials_node = \
            self.draw_contour_and_landmarks(annulus_point_coordinates=regression_annulus_point_coordinates,
                                            color=individualColors[annulus_phase],
                                            radius=individualTubeRadius,
                                            name=valve_type + ' ' + annulus_phase + ' regression',
                                            valve_type=valve_type,
                                            transform_node_name=self.regression_transform_node_name,
                                            landmark_points=regression_landmark_points)

        logging.info("Finished performing regression.")

    def regressionUpdateShape(self):
        x_new = np.ones((1, len(self.regression_sliders) + 1))
        for index, slider in enumerate(self.regression_sliders):
            x_new[0, index + 1] = slider.value

        regression_annulus_point_coordinates = (x_new @ self.regression_W).reshape((-1, 3))
        point_node = self.regression_nodes[1]
        points_polydata = createPolyDataFromPointArray(regression_annulus_point_coordinates)
        point_node.GetPolyData().SetPoints(points_polydata.GetPoints())

        regression_landmark_points = regression_annulus_point_coordinates[
                                     range(0,
                                           self.number_of_annulus_segments[self.regression_valve_type]
                                           * self.number_of_points_per_segment,
                                           self.number_of_points_per_segment), :]

        for landmark_index, landmark_name in enumerate(self.all_labels[self.regression_valve_type]):
            regression_landmark_position = regression_landmark_points[landmark_index, :]
            self.regression_landmark_points_fiducials_node.SetNthFiducialPosition(landmark_index,
                                                                                  regression_landmark_position[0],
                                                                                  regression_landmark_position[1],
                                                                                  regression_landmark_position[2])

    def regressionResetSliders(self):
        for slider in self.regression_sliders:
            slider.value = 0.5 * (slider.minimum + slider.maximum)

    def clear_regression(self):
        self.regression_annulus_point_coordinates = None
        self.regression_phase = None
        self.regression_valve_type = None

        if self.regression_grid_layout is not None:
            self.regression_grid_layout = None

        for label in self.regression_labels:
            label.deleteLater()
        self.regression_labels = []

        for slider in self.regression_sliders:
            slider.deleteLater()
        self.regression_sliders = []

        if len(self.regression_nodes) != 0:
            slicer.mrmlScene.RemoveNode(self.regression_nodes[2])
            slicer.mrmlScene.RemoveNode(self.regression_nodes[0])
            slicer.mrmlScene.RemoveNode(self.regression_nodes[1])
            self.regression_nodes = []

        if self.regression_landmark_points_fiducials_node is not None:
            slicer.mrmlScene.RemoveNode(self.regression_landmark_points_fiducials_node)
            self.regression_landmark_points_fiducials_node = None

    def compareCurves(self, curve1, curve2, valve_type, annulus_phase, table_widget):
        self.clear_compare()
        slicer.app.processEvents()

        type_phase = "{0} {1}".format(valve_type, annulus_phase)
        transform_node_name = "Annulus pose {0} {1}".format(valve_type, annulus_phase)
        curve_color = {"curve1": [0.5, 0.5, 0.5], "curve2": [1, 1, 0]}

        compare_annulus_point_coordinates = []
        compare_landmark_points = []
        for curve in [curve1, curve2]:
            if curve == "mean":
                if len(self.mean_nodes) != 0:
                    points = self.mean_nodes[type_phase][1].GetPolyData().GetPoints().GetData()
                    compare_annulus_point_coordinates.append(vtk_to_numpy(points))
                else:
                    logging.error("Mean contour need to be computed first")
                    return
            elif curve == "pca":
                if self.pca_type_phase == type_phase:
                    points = self.pca_nodes[1].GetPolyData().GetPoints().GetData()
                    compare_annulus_point_coordinates.append(vtk_to_numpy(points))
                else:
                    logging.error("PCA contour need to be computed with the same annulus type and phase first.")
                    return
            elif curve == "regression":
                if self.regression_type_phase == type_phase:
                    points = self.regression_nodes[1].GetPolyData().GetPoints().GetData()
                    compare_annulus_point_coordinates.append(vtk_to_numpy(points))
                else:
                    logging.error("Regression contour need to compute the same annulus type and phase first.")
                    return
            else:
                case_index = self.annulus_filenames.index(curve)
                compare_annulus_point_coordinates.append(
                    self.all_aligned_annulus_point_coordinates[type_phase][case_index])

        for annulus_point_coordinates in compare_annulus_point_coordinates:
            compare_landmark_points.append(annulus_point_coordinates[
                                           range(0, self.number_of_annulus_segments[valve_type]
                                                 * self.number_of_points_per_segment,
                                                 self.number_of_points_per_segment), :])

        # draw contours and landmarks
        self.compare_nodes1, self.compare_landmark_points_fiducials_node1 = \
            self.draw_contour_and_landmarks(annulus_point_coordinates=compare_annulus_point_coordinates[0],
                                            color=curve_color["curve1"],
                                            radius=0.1,
                                            name=valve_type + ' ' + annulus_phase + ' compare curve 1',
                                            valve_type=valve_type,
                                            transform_node_name=transform_node_name,
                                            landmark_points=compare_landmark_points[0])

        self.compare_nodes2, self.compare_landmark_points_fiducials_node2 = \
            self.draw_contour_and_landmarks(annulus_point_coordinates=compare_annulus_point_coordinates[1],
                                            color=curve_color["curve2"],
                                            radius=0.1,
                                            name=valve_type + ' ' + annulus_phase + ' compare curve 2',
                                            valve_type=valve_type,
                                            transform_node_name=transform_node_name,
                                            landmark_points=compare_landmark_points[1])

        # Draw distance lines between corresponding points
        distance_polydata = vtk.vtkPolyData()

        points = vtk.vtkPoints()
        points.SetData(numpy_to_vtk(
            np.concatenate((compare_annulus_point_coordinates[0], compare_annulus_point_coordinates[1]), axis=0)))
        distance_polydata.SetPoints(points)

        number_of_contour_points = compare_annulus_point_coordinates[0].shape[0]
        lines = vtk.vtkCellArray()
        for i in range(number_of_contour_points):
            line = vtk.vtkLine()
            line.GetPointIds().SetId(0, i)
            line.GetPointIds().SetId(1, i + number_of_contour_points)
            lines.InsertNextCell(line)
        distance_polydata.SetLines(lines)

        distances = np.sqrt(
            np.sum(np.square(compare_annulus_point_coordinates[1] - compare_annulus_point_coordinates[0]), axis=1))
        point_data = numpy_to_vtk(np.concatenate((distances, distances), axis=0))
        point_data.SetName("Distance")
        distance_polydata.GetPointData().SetActiveScalars('Distance')
        distance_polydata.GetPointData().SetScalars(point_data)

        self.compare_distance_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelNode", 'compare distance')
        self.compare_distance_node.CreateDefaultDisplayNodes()
        self.compare_distance_node.SetAndObservePolyData(distance_polydata)
        self.compare_distance_node.SetAndObserveTransformNodeID(
            self.annulus_to_world_transform_node[transform_node_name].GetID())
        display_node = self.compare_distance_node.GetDisplayNode()
        display_node.SetActiveScalar('Distance', vtk.vtkAssignAttribute.POINT_DATA)
        display_node.SetAndObserveColorNodeID("vtkMRMLColorTableNodeFileColdToHotRainbow.txt")
        display_node.SetScalarVisibility(True)
        display_node.SetLineWidth(10)

        self.shNode.SetItemParent(self.shNode.GetItemByDataNode(self.compare_distance_node),
                                  self.shRootFolderId[valve_type])

        # Fill metrics table
        min_value = distances.min()
        max_value = distances.max()
        mean_value = distances.mean()
        landmark_distances = np.sqrt(np.sum(np.square(compare_landmark_points[1] - compare_landmark_points[0]), axis=1))

        table_widget.setRowCount(3 + len(self.all_labels[valve_type]))

        min_label = qt.QLabel("min")
        min_label.setAlignment(qt.Qt.AlignCenter)
        min_label.setTextInteractionFlags(qt.Qt.TextSelectableByMouse)
        table_widget.setCellWidget(0, 0, min_label)
        min_value_label = qt.QLabel("{:.3f}".format(min_value))
        min_value_label.setAlignment(qt.Qt.AlignCenter)
        min_value_label.setTextInteractionFlags(qt.Qt.TextSelectableByMouse)
        table_widget.setCellWidget(0, 1, min_value_label)

        max_label = qt.QLabel("max")
        max_label.setAlignment(qt.Qt.AlignCenter)
        max_label.setTextInteractionFlags(qt.Qt.TextSelectableByMouse)
        table_widget.setCellWidget(1, 0, max_label)
        max_value_label = qt.QLabel("{:.3f}".format(max_value))
        max_value_label.setAlignment(qt.Qt.AlignCenter)
        max_value_label.setTextInteractionFlags(qt.Qt.TextSelectableByMouse)
        table_widget.setCellWidget(1, 1, max_value_label)

        mean_label = qt.QLabel("mean")
        mean_label.setAlignment(qt.Qt.AlignCenter)
        mean_label.setTextInteractionFlags(qt.Qt.TextSelectableByMouse)
        table_widget.setCellWidget(2, 0, mean_label)
        mean_value_label = qt.QLabel("{:.3f}".format(mean_value))
        mean_value_label.setAlignment(qt.Qt.AlignCenter)
        mean_value_label.setTextInteractionFlags(qt.Qt.TextSelectableByMouse)
        table_widget.setCellWidget(2, 1, mean_value_label)

        for label_index, label in enumerate(self.all_labels[valve_type]):
            fiducial_label = qt.QLabel(label)
            fiducial_label.setAlignment(qt.Qt.AlignCenter)
            fiducial_label.setTextInteractionFlags(qt.Qt.TextSelectableByMouse)
            table_widget.setCellWidget(label_index + 3, 0, fiducial_label)
            fiducial_value_label = qt.QLabel("{:.3f}".format(landmark_distances[label_index]))
            fiducial_value_label.setAlignment(qt.Qt.AlignCenter)
            fiducial_value_label.setTextInteractionFlags(qt.Qt.TextSelectableByMouse)
            table_widget.setCellWidget(label_index + 3, 1, fiducial_value_label)

        color_widget = slicer.modules.colors.widgetRepresentation()
        color_widget.onDisplayableNodeChanged(self.compare_distance_node)
        color_widget.createColorLegend()
        color_legend = slicer.util.findChildren(color_widget,
                                                name="ColorLegendDisplayNodeWidget")[0].mrmlColorLegendDisplayNode()
        color_legend.SetTitleText("Distance (mm)")
        label_text_property = slicer.util.findChildren(color_widget, name="LabelTextPropertyWidget")[0]
        label_text_property.text = "%.3f"
        legend_size = list(color_legend.GetSize())
        color_legend.SetNumberOfLabels(6)
        for i in range(len(legend_size)):
            legend_size[i] /= 2
        color_legend.SetSize(tuple(legend_size))

    def clear_compare(self):
        if len(self.compare_nodes1) != 0:
            slicer.mrmlScene.RemoveNode(self.compare_nodes1[2])
            slicer.mrmlScene.RemoveNode(self.compare_nodes1[0])
            slicer.mrmlScene.RemoveNode(self.compare_nodes1[1])
            self.compare_nodes1 = []

        if len(self.compare_nodes2) != 0:
            slicer.mrmlScene.RemoveNode(self.compare_nodes2[2])
            slicer.mrmlScene.RemoveNode(self.compare_nodes2[0])
            slicer.mrmlScene.RemoveNode(self.compare_nodes2[1])
            self.compare_nodes2 = []

        if self.compare_landmark_points_fiducials_node1 is not None:
            slicer.mrmlScene.RemoveNode(self.compare_landmark_points_fiducials_node1)
            self.compare_landmark_points_fiducials_node1 = None

        if self.compare_landmark_points_fiducials_node2 is not None:
            slicer.mrmlScene.RemoveNode(self.compare_landmark_points_fiducials_node2)
            self.compare_landmark_points_fiducials_node2 = None

        if self.compare_distance_node is not None:
            slicer.mrmlScene.RemoveNode(self.compare_distance_node)
            self.compare_distance_node = None


    def computeStrainCurvature(self, curve, valve_type, reference_phase, deformed_phase, visualize, resampling, theta0):
        self.clear_strain_curvature()
        slicer.app.processEvents()

        reference_type_phase = "{0} {1}".format(valve_type, reference_phase)
        reference_transform_node_name = "Annulus pose {0} {1}".format(valve_type, reference_phase)
        deformed_type_phase = "{0} {1}".format(valve_type, deformed_phase)
        deformed_transform_node_name = "Annulus pose {0} {1}".format(valve_type, deformed_phase)

        curve_color = {"reference_curve": [1, 1, 0], "deformed_curve": [0.5, 0.5, 0.5]}
        annulus_point_coordinates = []
        landmark_points = []
        if curve == "mean":
            if len(self.mean_nodes) != 0:
                points = self.mean_nodes[reference_type_phase][1].GetPolyData().GetPoints().GetData()
                annulus_point_coordinates.append(vtk_to_numpy(points))
                points = self.mean_nodes[deformed_type_phase][1].GetPolyData().GetPoints().GetData()
                annulus_point_coordinates.append(vtk_to_numpy(points))
            else:
                logging.error("Mean contour need to be computed first")
                return
        else:
            case_index = self.annulus_filenames.index(curve)
            annulus_point_coordinates.append(
                self.all_aligned_annulus_point_coordinates[reference_type_phase][case_index])
            annulus_point_coordinates.append(
                self.all_aligned_annulus_point_coordinates[deformed_type_phase][case_index])

        for point_coordinates in annulus_point_coordinates:
            landmark_points.append(point_coordinates[
                                   range(0, self.number_of_annulus_segments[valve_type]
                                         * self.number_of_points_per_segment,
                                         self.number_of_points_per_segment), :])

        # draw contours and landmarks
        self.reference_nodes, self.reference_landmark_points_fiducials_node = \
            self.draw_contour_and_landmarks(annulus_point_coordinates=annulus_point_coordinates[0],
                                            color=curve_color["reference_curve"],
                                            radius=0.1,
                                            name=valve_type + ' ' + reference_phase + ' reference',
                                            valve_type=valve_type,
                                            transform_node_name=reference_transform_node_name,
                                            landmark_points=landmark_points[0])
        self.reference_nodes[0].GetDisplayNode().SetVisibility(0)
        self.reference_nodes[1].GetDisplayNode().SetVisibility(0)
        self.reference_landmark_points_fiducials_node.GetDisplayNode().SetVisibility(0)

        self.deformed_nodes, self.deformed_landmark_points_fiducials_node = \
            self.draw_contour_and_landmarks(annulus_point_coordinates=annulus_point_coordinates[1],
                                            color=curve_color["deformed_curve"],
                                            radius=0.1,
                                            name=valve_type + ' ' + deformed_phase + ' deformed',
                                            valve_type=valve_type,
                                            transform_node_name=deformed_transform_node_name,
                                            landmark_points=landmark_points[1])
        self.deformed_nodes[1].GetDisplayNode().SetVisibility(0)

        # compute strain and curvature, and replace the deformed tube
        landmark_index = []
        for i in range(0, self.number_of_annulus_segments[valve_type] * self.number_of_points_per_segment,
                       self.number_of_points_per_segment):
            landmark_index.append(i)
        theta0_index = landmark_index[self.all_labels[valve_type].index(theta0)]
        tube_polydata, strain, k_deformed, relative_curvature = self.createResampledTube(
            self.reference_nodes[1].GetPolyData(),
            self.deformed_nodes[1].GetPolyData(),
            landmark_index,
            resampling,
            theta0_index)
        self.deformed_nodes[0].SetAndObservePolyData(tube_polydata)
        display_node = self.deformed_nodes[0].GetDisplayNode()

        display_node.SetActiveScalar(visualize, vtk.vtkAssignAttribute.POINT_DATA)
        display_node.SetAndObserveColorNodeID("vtkMRMLColorTableNodeFileDivergingBlueRed.txt")
        display_node.SetScalarVisibility(True)

        color_widget = slicer.modules.colors.widgetRepresentation()
        color_widget.onDisplayableNodeChanged(self.deformed_nodes[0])
        color_widget.createColorLegend()
        color_legend = slicer.util.findChildren(color_widget,
                                                name="ColorLegendDisplayNodeWidget")[0].mrmlColorLegendDisplayNode()
        label_text_property = slicer.util.findChildren(color_widget, name="LabelTextPropertyWidget")[0]
        if visualize == "strain":
            color_legend.SetTitleText("Strain (%)")
            label_text_property.text = "%.1f"
        elif visualize == "absolute curvature":
            color_legend.SetTitleText("absolute\ncurvature\n(1/mm)")
            label_text_property.text = "%.3f"
        else:
            color_legend.SetTitleText("relative\ncurvature\n(1/mm)")
            label_text_property.text = "%.3f"
        legend_size = list(color_legend.GetSize())
        color_legend.SetNumberOfLabels(6)
        for i in range(len(legend_size)):
            legend_size[i] /= 2
        color_legend.SetSize(tuple(legend_size))

    def clear_strain_curvature(self):
        if len(self.reference_nodes) != 0:
            slicer.mrmlScene.RemoveNode(self.reference_nodes[2])
            slicer.mrmlScene.RemoveNode(self.reference_nodes[0])
            slicer.mrmlScene.RemoveNode(self.reference_nodes[1])
            self.reference_nodes = []

        if len(self.deformed_nodes) != 0:
            slicer.mrmlScene.RemoveNode(self.deformed_nodes[2])
            slicer.mrmlScene.RemoveNode(self.deformed_nodes[0])
            slicer.mrmlScene.RemoveNode(self.deformed_nodes[1])
            self.deformed_nodes = []

        if self.reference_landmark_points_fiducials_node is not None:
            slicer.mrmlScene.RemoveNode(self.reference_landmark_points_fiducials_node)
            self.reference_landmark_points_fiducials_node = None

        if self.deformed_landmark_points_fiducials_node is not None:
            slicer.mrmlScene.RemoveNode(self.deformed_landmark_points_fiducials_node)
            self.deformed_landmark_points_fiducials_node = None
        slicer.modules.colors.widgetRepresentation().deleteColorLegend()

    def createResampledTube(self, reference_polydata, deformed_polydata, landmark_index, resampling, theta0_index):

        reference_points = vtk_to_numpy(reference_polydata.GetPoints().GetData())
        deformed_points = vtk_to_numpy(deformed_polydata.GetPoints().GetData())
        n_points = reference_points.shape[0]
        if resampling == "laplacian":
            deformed_points, strain = self.laplacianReparameterization(reference_points, deformed_points,
                                                                       n_points, landmark_index)
        elif resampling == "theta":
            deformed_points, strain = self.thetaReparameterization(reference_points, deformed_points,
                                                                   n_points, theta0_index)
        else:
            logging.error("Wrong resampling method given!")

        reference_segment_lengths = np.zeros(n_points)
        deformed_segment_lengths = np.zeros(n_points)
        for i in range(-1, n_points - 1):
            reference_segment_lengths[i] = np.linalg.norm(reference_points[i + 1] - reference_points[i])
            deformed_segment_lengths[i] = np.linalg.norm(deformed_points[i + 1] - deformed_points[i])
        deformed_polydata.GetPoints().SetData(numpy_to_vtk(deformed_points))

        strain = (strain - 1) * 100  # convert to true strain and percentage
        vtk_strain_array = numpy_to_vtk(strain, deep=True)
        vtk_strain_array.SetName("strain")
        deformed_polydata.GetPointData().AddArray(vtk_strain_array)

        # compute relative curvature
        k_reference = self.computeAbsoluteCurvature(reference_points, reference_segment_lengths, landmark_index)
        k_deformed = self.computeAbsoluteCurvature(deformed_points, deformed_segment_lengths, landmark_index)
        relative_curvature = k_deformed - k_reference

        # vtk_k_reference_array = numpy_to_vtk(k_reference)
        # vtk_k_reference_array.SetName("absolute curvature")
        # reference_polydata.GetPointData().AddArray(vtk_k_reference_array)

        vtk_k_deformed_array = numpy_to_vtk(k_deformed)
        vtk_k_deformed_array.SetName("absolute curvature")
        deformed_polydata.GetPointData().AddArray(vtk_k_deformed_array)

        vtk_relative_curvature_array = numpy_to_vtk(relative_curvature)
        vtk_relative_curvature_array.SetName("relative curvature")
        deformed_polydata.GetPointData().AddArray(vtk_relative_curvature_array)

        # create lines and new tube
        lines = vtk.vtkCellArray()
        for i in range(n_points - 1):
            line = vtk.vtkLine()
            line.GetPointIds().SetId(0, i)
            line.GetPointIds().SetId(1, i + 1)
            lines.InsertNextCell(line)
        line = vtk.vtkLine()
        line.GetPointIds().SetId(0, n_points - 1)
        line.GetPointIds().SetId(1, 0)
        lines.InsertNextCell(line)
        deformed_polydata.SetLines(lines)
        deformed_polydata.Modified()

        tube = vtk.vtkTubeFilter()
        tube.SetInputData(deformed_polydata)
        tube.SetNumberOfSides(10)
        tube.SetRadius(0.1)
        tube.Update()
        tube_polydata = tube.GetOutput()

        return tube_polydata, strain, k_deformed, relative_curvature

    def laplacianReparameterization(self, reference_points, deformed_points, n_points, landmark_index):
        reference_segment_lengths = np.zeros(n_points)
        deformed_segment_lengths = np.zeros(n_points)
        for i in range(-1, n_points - 1):
            reference_segment_lengths[i] = np.linalg.norm(reference_points[i + 1] - reference_points[i])
            deformed_segment_lengths[i] = np.linalg.norm(deformed_points[i + 1] - deformed_points[i])

        # calculate total segment lengths between landmark points
        n_landmarks = len(landmark_index)
        deformed_landmark_segment_lengths = np.zeros(n_landmarks)
        landmark_index.append(n_points)
        for i in range(n_landmarks):
            start_index = landmark_index[i]
            end_index = landmark_index[i + 1]
            for j in range(start_index, end_index):
                deformed_landmark_segment_lengths[i] += deformed_segment_lengths[j]

        # minimize laplacian energy s.t. displacement constraints
        b_mat = np.eye(n_points)  # laplacian matrix
        for i in range(n_points - 1):
            b_mat[i, i] = -2
            b_mat[i, i - 1] = 1
            b_mat[i, i + 1] = 1
        b_mat[n_points - 1, n_points - 1] = -2
        b_mat[n_points - 1, n_points - 2] = 1
        b_mat[n_points - 1, 0] = 1

        w_mat = np.eye(n_points)  # weight matrix
        for i in range(n_points):
            w_mat[i, i] = reference_segment_lengths[i]

        a_mat = np.zeros((n_landmarks, n_points))  # constraint matrix
        for i in range(n_landmarks):
            for j in range(landmark_index[i], landmark_index[i + 1]):
                a_mat[i, j] = reference_segment_lengths[j]
        k_mat = np.block([[b_mat.transpose() @ w_mat @ b_mat, a_mat.transpose()],
                          [a_mat, np.zeros((n_landmarks, n_landmarks))]])
        f_vec = np.zeros(n_points + n_landmarks)
        for i in range(n_landmarks):
            f_vec[n_points + i] = deformed_landmark_segment_lengths[i]

        x = np.linalg.solve(k_mat, f_vec)
        strain = x[0:n_points]
        landmark_index.pop()

        # re-sample/interpolate deformed curve based on computed strain.
        original_curve_coordinates = np.zeros(n_points)
        resample_curve_coordinates = np.zeros(n_points)
        current_original_coordinate = 0
        current_resample_coordinate = 0
        for i in range(n_points):
            original_curve_coordinates[i] = current_original_coordinate
            resample_curve_coordinates[i] = current_resample_coordinate
            current_original_coordinate += deformed_segment_lengths[i]
            current_resample_coordinate += reference_segment_lengths[i] * strain[i]

        resample_points = np.zeros((n_points, 3))
        resample_points[:, 0] = np.interp(resample_curve_coordinates, original_curve_coordinates, deformed_points[:, 0])
        resample_points[:, 1] = np.interp(resample_curve_coordinates, original_curve_coordinates, deformed_points[:, 1])
        resample_points[:, 2] = np.interp(resample_curve_coordinates, original_curve_coordinates, deformed_points[:, 2])

        return resample_points, strain

    def thetaReparameterization(self, reference_points, deformed_points, n_points, theta0_index):

        def cart2pol(x, y):
            r = np.sqrt(x ** 2 + y ** 2)
            theta = np.arctan2(y, x)
            return r, theta

        # center the shapes
        reference_center = np.mean(reference_points, axis=0)
        deformed_center = np.mean(deformed_points, axis=0)
        centered_reference_points = np.subtract(reference_points, reference_center)
        centered_deformed_points = np.subtract(deformed_points, deformed_center)

        # use SVD to find best fitting plane
        u_reference, s_reference, vh_reference = np.linalg.svd(centered_reference_points)
        u_deformed, s_deformed, vh_deformed = np.linalg.svd(centered_deformed_points)

        # make sure the shapes in the transformed coordinates are not flipped by SVD
        if np.dot(vh_deformed[0, :], vh_reference[0, :]) <= 0:
            vh_deformed[0, :] = -vh_deformed[0, :]
            logging.info("The first principal axis is in the opposite direction of the reference's, flip it back.")
        if np.dot(vh_deformed[1, :], vh_reference[1, :]) <= 0:
            vh_deformed[1, :] = -vh_deformed[1, :]
            logging.info("The second principal axis is in the opposite direction of the reference's, flip it back.")
        if np.dot(vh_deformed[2, :], vh_reference[2, :]) <= 0:
            vh_deformed[2, :] = -vh_deformed[2, :]
            logging.info("The third principal axis is in the opposite direction of the reference's, flip it back.")

        # project the shapes and transform them to the cylindrical coordinates
        xyz_reference_points = centered_reference_points @ vh_reference.T
        xyz_deformed_points = centered_deformed_points @ vh_deformed.T
        r_reference, theta_reference = cart2pol(xyz_reference_points[:, 0], xyz_reference_points[:, 1])
        r_deformed, theta_deformed = cart2pol(xyz_deformed_points[:, 0], xyz_deformed_points[:, 1])

        # shift theta to align to the first landmark point
        theta_reference = theta_reference - theta_reference[theta0_index]
        theta_deformed = theta_deformed - theta_deformed[theta0_index]

        # resample points in the original coordinates
        resample_points = np.zeros((n_points, 3))
        resample_points[:, 0] = np.interp(theta_reference, theta_deformed, deformed_points[:, 0], period=np.pi*2)
        resample_points[:, 1] = np.interp(theta_reference, theta_deformed, deformed_points[:, 1], period=np.pi*2)
        resample_points[:, 2] = np.interp(theta_reference, theta_deformed, deformed_points[:, 2], period=np.pi*2)

        reference_segment_lengths = np.zeros(n_points)
        deformed_segment_lengths = np.zeros(n_points)
        strain = np.zeros(n_points)
        for i in range(-1, n_points - 1):
            reference_segment_lengths[i] = np.linalg.norm(reference_points[i + 1] - reference_points[i])
            deformed_segment_lengths[i] = np.linalg.norm(resample_points[i + 1] - resample_points[i])
            strain[i] = deformed_segment_lengths[i] / reference_segment_lengths[i]

        return resample_points, strain

    def computeAbsoluteCurvature(self, points, segment_length, landmark_index, interval=1):
        n_points = points.shape[0]
        k = np.zeros(n_points)
        for i in range(n_points - 1):
            h1 = 0
            j = i
            while h1 < interval:
                j -= 1
                if j < 0:
                    j += n_points
                h1 += segment_length[j]
            f0 = points[j]

            f1 = points[i]

            h2 = 0
            j = i
            while h2 < interval:
                if j >= n_points:
                    j -= n_points
                h2 += segment_length[j]
                j += 1
            f2 = points[j] if j < n_points else points[j-n_points]

            # compute first and second derivatives
            d1 = -h2 / h1 / (h1 + h2) * f0 - (h1 - h2) / h1 / h2 * f1 + h1 / h2 / (h1 + h2) * f2
            d2 = 2 * (h2 * f0 - (h1 + h2) * f1 + h1 * f2) / h1 / h2 / (h1 + h2)
            k[i] = np.linalg.norm(np.cross(d1, d2)) / (np.linalg.norm(d1) ** 3)

        f0 = points[n_points - 2]
        f1 = points[n_points - 1]
        f2 = points[0]
        h1 = segment_length[n_points - 2]
        h2 = segment_length[n_points - 1]
        d1 = -h2 / h1 / (h1 + h2) * f0 - (h1 - h2) / h1 / h2 * f1 + h1 / h2 / (h1 + h2) * f2
        d2 = 2 * (h2 * f0 - (h1 + h2) * f1 + h1 * f2) / h1 / h2 / (h1 + h2)
        k[n_points - 1] = np.linalg.norm(np.cross(d1, d2)) / (np.linalg.norm(d1) ** 3)

        # smooth landmark and adjacent point due to nature of the piecewise linear input curve.
        for i in landmark_index:
            k1 = k[i+1]
            k2 = k[i-2] if i > 0 else k[n_points - 2]
            k[i] = 2/3 * k1 + 1/3 * k2  # imprecise approximation
            k[i-1] = 1/3 * k1 + 2/3 * k2
        return k


class AnnulusShapeAnalyzerTest(ScriptedLoadableModuleTest):
    """
    This is the test case for your scripted module.
    Uses ScriptedLoadableModuleTest base class, available at:
    https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
    """

    def setUp(self):
        """ Do whatever is needed to reset the state - typically a scene clear will be enough.
        """
        slicer.mrmlScene.Clear()

    def runTest(self):
        """Run as few or as many tests as needed here.
        """
        self.setUp()
        self.test_AnnulusShapeAnalyzer()

    def test_AnnulusShapeAnalyzer(self):
        """ Ideally you should have several levels of tests.  At the lowest level
        tests should exercise the functionality of the logic with different inputs
        (both valid and invalid).  At higher levels your tests should emulate the
        way the user would interact with your code and confirm that it still works
        the way you intended.
        One of the most important features of the tests is that it should alert other
        developers when their changes will have an impact on the behavior of your
        module.  For example, if a developer removes a feature that you depend on,
        your test should break so they know that the feature is needed.
        """

        self.delayDisplay("Starting the Annulus Shape Analyzer Test")

        import SampleData
        downloadedFilePath = SampleData.SampleDataLogic().downloadSample("AnnulusShapeAnalyzer")

        from tempfile import TemporaryDirectory
        with TemporaryDirectory(dir=slicer.app.temporaryPath) as temp_dir:
            from zipfile import ZipFile
            with ZipFile(downloadedFilePath, 'r') as zipObject:
                zipObject.extractall(path=temp_dir)

            print(os.listdir(temp_dir))

            widget = slicer.modules.AnnulusShapeAnalyzerWidget
            logic = widget.logic

            # load annulus contour and calculate mean
            widget.pathLineEdit_loadPopulationFile.currentPath = temp_dir + "/" + "0-1_AnnulusContourPoints.csv"
            widget.onLoadPopulationFile()
            widget.onProcessPopulationFile()
            widget.onCalculateMeanShape()

            # pca
            widget.onEvaluateModels()

            # load demographics and regress w.r.t. selected variable
            widget.pathLineEdit_demographicsFilePath.currentPath = temp_dir + "/" + "Demographics.csv"
            widget.onLoadAssociatedDemographics()
            widget.tableWidget_demographics.findItems("bsa", qt.Qt.MatchExactly)[0].setCheckState(qt.Qt.Checked)
            widget.onPerformRegressionOnSelectedVariables()

            # compare curves
            widget.comboBox_compareCurve2.currentIndex = 3
            widget.onCompareCurves()

            # strain and curvature
            widget.comboBox_strainCurvatureDeformedPhase.currentIndex = 1
            widget.onComputeStrainCurvature()

            # cleanup
            logic.clear()
            widget.onReload()
            slicer.mrmlScene.Clear()

        self.delayDisplay('Test passed')
