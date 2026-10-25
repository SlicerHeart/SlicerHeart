"""Export 4D flow DICOM data sets as test cases in 3D Slicer native file formats, and regenerate their outputs.

The output folder is a data set of test cases (format version 4, see tests/clinical/README.md of slicerheart_4dflow):
manifest.json, inputs/<case>/ (what the processing starts from) and outputs/<case>/ (everything computed from the inputs).
The case ID is the name of the patient folder.

Export: each patient folder of the input folder (anonymized DICOM files, for example Patient0004/<study>/<series>/*.dcm)
is imported into a temporary DICOM database, the flow field is created with the default processing of test cases
(Import4DFlowLogic.applyDefaultTestCaseProcessing: Laplacian 4D phase unwrapping, quadratic background fit; the
unwrapping method can be changed with --unwrap), and written by Import4DFlowLogic.exportTestCase and
Analyze4DFlowLogic.writeTestCaseFlows:
- inputs/<case>/acquisition/: acquisition description, magnitude and raw velocity
- inputs/<case>/annotations/: lumen .seg.nrrd, measurement planes .mrk.json and their description (generated
  automatically if the case has none yet)
- outputs/<case>/: processing description, corrected velocity, wrap counts, PC-MRA, plane flows and quality report

Regenerating the outputs (--regenerate-outputs, no DICOM import): the outputs of each case are deleted and computed again
from its inputs, with the default processing of test cases (not the processing recorded in the old outputs), for example
after an algorithm change or after editing the annotations. The inputs are not changed, except that with --regenerate-lumen
the automatic lumen segmentations that are not reviewed are replaced by the current automatic method first (the planes are
kept, so that results stay comparable; --overwrite-annotations also replaces the planes and reviewed lumens).

The test cases can then be used without DICOM import: by slicerheart_4dflow (slicer_io.load_case, clinical tests) and in
Slicer (Import4DFlowLogic.loadTestCase, "Load test case..." button in Import 4D Flow).

The automatically generated lumen segmentation and planes are meant to be reviewed and edited: load the case in Slicer,
edit the lumen segment or the planes, save them (File / Save data, the files are overwritten), and record the review in
annotations.json ("reviewed": true, "method": "automatic, manually edited" if edited). Existing annotations are kept when
the cases are exported again (unless --overwrite-annotations is used).

Usage (Slicer Python console, or the Slicer web server exec API):

    import Export4DFlowTestCases
    Export4DFlowTestCases.exportTestCases(r"D:/Data/4Dflow/_circle_comparison_anonymized_",
                                          r"D:/Data/4Dflow/_test_cases_anonymized_")

or from the command line:

    Slicer --no-main-window --python-script Export4DFlowTestCases.py --input <DICOM folder> --output <data set folder>
        [--patients Patient0004 ...] [--overwrite] [--overwrite-annotations] [--log <file.json>]
    Slicer --no-main-window --python-script Export4DFlowTestCases.py --output <data set folder> --regenerate-outputs
        [--regenerate-lumen] [--patients Patient0004 ...] [--log <file.json>]

The status of each case is printed when it is done, and logged; with --log it is also written into a JSON file (keep it
outside the data set folder, for example in .test-reports).
"""

import argparse
import json
import logging
import os
import shutil
import sys
import tempfile
import time
import traceback

import slicer

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if THIS_DIR not in sys.path:
    sys.path.insert(0, THIS_DIR)

NUMBER_OF_SERIES = 4  # magnitude and three velocity components


def seriesFolders(patientDirectory):
    """Folders below the patient folder that contain DICOM files."""
    folders = []
    for root, _, files in os.walk(patientDirectory):
        if any(f.lower().endswith(".dcm") for f in files):
            folders.append(root)
    return sorted(folders)


def patientsBeingWritten(inputDirectory):
    """Patients that the anonymizer is still writing (they are in a worker staging folder)."""
    busy = set()
    for name in os.listdir(inputDirectory):
        staging = os.path.join(inputDirectory, name, "temp_organized_input")
        if name.startswith("worker_") and os.path.isdir(staging):
            busy.update(os.listdir(staging))
    return busy


def findPatients(inputDirectory, patients=None):
    """Patient folders that are complete (all series present and not being written). Returns (complete, skipped messages)."""
    busy = patientsBeingWritten(inputDirectory)
    complete, skipped = [], []
    for name in sorted(os.listdir(inputDirectory)):
        path = os.path.join(inputDirectory, name)
        if not os.path.isdir(path) or name.startswith("worker_"):
            continue
        if patients and name not in patients:
            continue
        if name in busy:
            skipped.append(f"{name}: being written by the anonymizer")
            continue
        folders = seriesFolders(path)
        if len(folders) < NUMBER_OF_SERIES:
            skipped.append(f"{name}: {len(folders)} of {NUMBER_OF_SERIES} series")
            continue
        complete.append(name)
    return complete, skipped


DEFAULT_UNWRAP_MODE = "Laplacian4DUnwrap"


def loadFlowField(patientDirectory, databaseDirectory, unwrapMode=DEFAULT_UNWRAP_MODE):
    """Import the DICOM files of a patient and create the flow field with the default processing (phase unwrapping
    method unwrapMode, a name of Import4DFlow.UnwrapModeEnum). Returns (flow field node, DICOM metadata)."""
    from DICOMLib import DICOMUtils
    import FlowTestingUtils
    import Import4DFlow
    logic = Import4DFlow.Import4DFlowLogic()
    with DICOMUtils.TemporaryDICOMDatabase(databaseDirectory) as db:
        DICOMUtils.importDicom(patientDirectory, db)
        FlowTestingUtils.loadDicomSeriesAsVolumeSequences()
        volumeNodeSets = logic.findVolumeNodeSets()
        if len(volumeNodeSets) != 1:
            raise RuntimeError(f"Expected one 4D flow image set, found {len(volumeNodeSets)}")
        volumeNodeSet = list(volumeNodeSets.values())[0]
        flowFieldNode = logic.createFlowFieldFromComponentVolumes(volumeNodeSet["componentVolumeNodes"],
            volumeNodeSet["componentVolumeNodesInvertToRasDirection"], volumeNodeSet["magnitudeVolumeNode"])
        # DICOM metadata is read while the database is available
        metadata = logic._dicomMetadata(flowFieldNode)
    logic.applyDefaultTestCaseProcessing(flowFieldNode, unwrapMode)
    return flowFieldNode, metadata


def writeLog(logPath, inputDirectory, summary):
    """Write the summary of a run (status of each case) into a JSON file, if logPath is specified.
    The log is not written into the test case folder: it describes a run, not the data."""
    if not logPath:
        return
    os.makedirs(os.path.dirname(os.path.abspath(logPath)), exist_ok=True)
    with open(logPath, "w", encoding="utf-8") as file:
        json.dump({"input": os.path.basename(os.path.normpath(inputDirectory)) if inputDirectory else None,
                   "slicer": slicer.app.applicationVersion, "time": time.strftime("%Y-%m-%d %H:%M:%S"), "cases": summary},
                  file, indent=2)


def report(summary, name, status):
    summary[name] = status
    logging.info(f"{name}: {status}")
    print(f"{time.strftime('%H:%M:%S')} {name}: {status}", flush=True)  # progress while the export runs


def regenerateOutputs(datasetDirectory, patients=None, regenerateLumen=False, overwriteAnnotations=False, unwrapMode=DEFAULT_UNWRAP_MODE):
    """Delete the outputs of each case of the data set and compute them again from its inputs (see module documentation).
    Returns a summary dictionary {case: status}."""
    import Import4DFlow
    import Analyze4DFlow
    importLogic = Import4DFlow.Import4DFlowLogic()
    analyzeLogic = Analyze4DFlow.Analyze4DFlowLogic()
    from Import4DFlowLib import FlowLibraryBridge
    slicer_io = FlowLibraryBridge.ensureLibrary().slicer_io
    summary = {}
    for name in slicer_io.dataset_cases(datasetDirectory):
        if patients and name not in patients:
            continue
        startTime = time.time()
        try:
            slicer.mrmlScene.Clear(0)
            outputDirectory = str(slicer_io.case_directories(datasetDirectory, name)[1])
            shutil.rmtree(outputDirectory, ignore_errors=True)
            loaded = importLogic.loadTestCase(datasetDirectory, name, useOutputs=False, unwrapMode=unwrapMode)
            flowFieldNode = loaded["flowFieldNode"]
            status = "outputs regenerated"
            if regenerateLumen:
                lumenDescription = loaded["annotations"].get("lumen", {})
                automatic = lumenDescription.get("method") == "automatic" and not lumenDescription.get("reviewed")
                if automatic or overwriteAnnotations:
                    importLogic.writeTestCaseLumen(datasetDirectory, name, flowFieldNode, overwriteLumen=True)
                    status = "lumen and outputs regenerated"
                else:
                    status = "outputs regenerated (lumen kept: placed or reviewed by a person)"
            importLogic.writeTestCaseOutputs(flowFieldNode, datasetDirectory, name)
            analyzeLogic.writeTestCaseFlows(datasetDirectory, name, flowFieldNode, overwritePlanes=overwriteAnnotations)
            status += f" ({time.time() - startTime:.0f} s)"
            warnings = json.loads(importLogic._getSequenceFromProxyNode(flowFieldNode).GetAttribute("SlicerHeart.phaseUnwrappingWarnings") or "[]")
            if warnings:
                status += " WARNING: " + " ".join(warnings)
            report(summary, name, status)
        except Exception:
            report(summary, name, "FAILED: " + traceback.format_exc())
        finally:
            slicer.mrmlScene.Clear(0)
    return summary


def exportTestCases(inputDirectory, outputDirectory, patients=None, overwrite=False, overwriteAnnotations=False,
                    unwrapMode=DEFAULT_UNWRAP_MODE, logPath=None):
    """Export the patients of inputDirectory (DICOM) as test cases into the data set outputDirectory (see module
    documentation). Returns a summary dictionary {patient: status}, which is also logged and written to logPath (JSON), if
    specified."""
    import Import4DFlow
    import Analyze4DFlow
    importLogic = Import4DFlow.Import4DFlowLogic()
    analyzeLogic = Analyze4DFlow.Analyze4DFlowLogic()
    os.makedirs(outputDirectory, exist_ok=True)
    summary = {}
    complete, skipped = findPatients(inputDirectory, patients)
    for message in skipped:
        summary[message.split(":")[0]] = "skipped: " + message.split(": ", 1)[1]
    for name in complete:
        if os.path.isfile(importLogic.testCasePath(outputDirectory, name, "acquisition")) and not overwrite:
            summary[name] = "skipped: already exported (use overwrite to export again)"
            continue
        startTime = time.time()
        databaseDirectory = tempfile.mkdtemp(prefix="SlicerHeart4DFlowExport")  # in TEMP
        try:
            slicer.mrmlScene.Clear(0)
            flowFieldNode, metadata = loadFlowField(os.path.join(inputDirectory, name), databaseDirectory, unwrapMode)
            importLogic.exportTestCase(flowFieldNode, outputDirectory, name, metadata=metadata, overwriteLumen=overwriteAnnotations)
            analyzeLogic.writeTestCaseFlows(outputDirectory, name, flowFieldNode, overwritePlanes=overwriteAnnotations)
            status = f"exported ({time.time() - startTime:.0f} s)"
            warnings = json.loads(importLogic._getSequenceFromProxyNode(flowFieldNode).GetAttribute("SlicerHeart.phaseUnwrappingWarnings") or "[]")
            if warnings:
                status += " WARNING: " + " ".join(warnings)
            report(summary, name, status)
        except Exception:
            report(summary, name, "FAILED: " + traceback.format_exc())
        finally:
            slicer.mrmlScene.Clear(0)
            shutil.rmtree(databaseDirectory, ignore_errors=True)
    writeLog(logPath, inputDirectory, summary)
    return summary


def main(argv):
    parser = argparse.ArgumentParser(description="Export 4D flow DICOM data sets as test cases in 3D Slicer native file formats,"
                                     " or regenerate the outputs of the test cases.")
    parser.add_argument("--input", help="Folder with one subfolder of anonymized DICOM files per patient (for exporting)")
    parser.add_argument("--output", required=True, help="Folder of the data set of test cases")
    parser.add_argument("--patients", nargs="*", help="Patient folder names (case IDs) to process (default: all)")
    parser.add_argument("--overwrite", action="store_true", help="Export cases again (the lumen and planes are kept)")
    parser.add_argument("--overwrite-annotations", action="store_true", help="Also replace the lumen and planes (discards edits)")
    parser.add_argument("--regenerate-outputs", action="store_true", help="Compute the outputs of the existing cases again from"
                        " their inputs (no DICOM import)")
    parser.add_argument("--regenerate-lumen", action="store_true", help="With --regenerate-outputs: also replace automatic lumen"
                        " segmentations (that are not reviewed) by the current automatic method")
    parser.add_argument("--unwrap", default=DEFAULT_UNWRAP_MODE, help="Phase unwrapping method (name of Import4DFlow.UnwrapModeEnum,"
                        " for example TemporalUnwrap or Laplacian4DUnwrap)")
    parser.add_argument("--log", help="Write the status of each case into this JSON file (for example in .test-reports;"
                        " not in the data set folder, which holds only test data)")
    args = parser.parse_args(argv)
    if args.regenerate_outputs:
        summary = regenerateOutputs(args.output, args.patients, args.regenerate_lumen, args.overwrite_annotations, args.unwrap)
        writeLog(args.log, None, summary)
    else:
        if not args.input:
            parser.error("--input is required for exporting (or use --regenerate-outputs)")
        summary = exportTestCases(args.input, args.output, args.patients, args.overwrite, args.overwrite_annotations, args.unwrap, args.log)
    for name, status in summary.items():
        print(f"{name}: {status}")
    return 0 if not any(status.startswith("FAILED") for status in summary.values()) else 1


if __name__ == "__main__":
    exitCode = 1
    try:
        exitCode = main(sys.argv[1:])
    except Exception:
        traceback.print_exc()
    finally:
        slicer.app.exit(exitCode)
