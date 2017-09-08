# SlicerHeart extension for 3D Slicer

Modules for importing and visualizing cardiac and other ultrasound data sets.

# Installation and setup:
- Download&install "Nightly build" version of 3D Slicer from http://download.slicer.org/
- Start Slicer, in the Extension manager install SlicerHeart extension (in Cardiac category), click Yes to install all dependencies, click Restart

# Loading GE Kretz ultrasound images

Load data from DICOM folder:
- Drag-and-drop your image folder to the Slicer application window
- In the popup window click OK (to load directory into DICOM database)
- Click Copy (to make a local copy of the folder into the Slicer database) or Add link (to not copy data files, data will not be available if the original folder is removed)
- Wait for the import operation to complete, click OK
- In the DICOM browser window, select data to load and click Load button
- Click OK to accept warnings (the warning is displayed because the importer is still experimental and the images may be slightly distorted)
- Wait for loading to complete (may take a few minutes)

Load data from .vol or .v00 file:
- Drag-and-drop the file to the Slicer application window
- Click OK to load the data
- Wait for loading to complete (may take a few minutes)
