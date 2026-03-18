"""

usage: Slicer --python-script run.py -i {mrb_inputFile} -r {ready_file}

"""

import argparse, sys, os
import slicer


def switchToSimplifiedViewer():
  slicer.util.selectModule('SimplifiedViewer')
  slicer.modules.SimplifiedViewerWidget.setFull3DSlicerInterfaceVisible(False)
  slicer.app.processEvents()


def writeHandShakeFile(ready_file):
  f = open(ready_file, 'w')
  f.write('Slicer is ready\n')
  f.close()
  qt.QTimer.singleShot(5000, lambda: os.remove(ready_file) if os.path.exists(ready_file) else None)


def main(argv):
  parser = argparse.ArgumentParser(description="View MRB in SimplifiedViewer module")
  parser.add_argument("-i", "--input_file", dest="input_file", metavar="PATH", default=None, required=False,
                      help="input mrb file to be loaded")
  parser.add_argument("-r", "--ready_file", dest="ready_file", metavar="PATH", required=True,
                      help="ready file for handshake")

  args = parser.parse_args(argv)
  ready_file = args.ready_file
  inputFile = args.input_file

  try:
    slicer.util.mainWindow().showMaximized()
    if inputFile is not None:
      slicer.util.loadScene(inputFile)
      switchToSimplifiedViewer()
    writeHandShakeFile(ready_file)
  except Exception as exc:
    if inputFile is not None:
      switchToSimplifiedViewer()
    writeHandShakeFile(ready_file)
    slicer.util.errorDisplay(exc)


if __name__ == "__main__":
  main(sys.argv[1:])