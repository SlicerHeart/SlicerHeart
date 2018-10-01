# SlicerHeart extension for 3D Slicer

Modules for importing and visualizing cardiac and other ultrasound data sets.

# Installation and setup
- Download&install "Nightly build" version of 3D Slicer from http://download.slicer.org/
- Start Slicer, in the Extension manager install SlicerHeart extension (in Cardiac category), click Yes to install all dependencies, click Restart

# Importing DICOM files

While DICOM standard specifies how 3D and 4D (3D+t) ultrasound volumes can be stored in standard fields, most ultrasound manufacturers do not follow this standard. Typically, only 2D screenshots or 2D+t screen capture videos are stored in standard fields. 3D information is stored in private fields and proprietary algorithms are needed to intepret them. Most vendors do not make publicly available these proprietary algorithms.

## Philips

Philips machines save 3D/4D ultrasound data in private fields. Method to extract volumetric images from these fields is not publicly disclosed. However, Philips QLAB cardiac analysis software can export images to a DICOM format variant, which stores volumetric images in standard fields, which can be interpreted without proprietary methods. Unfortunately, these DICOM files are not fully DICOM compliant (required fields, such as SOP instance UID, patient name, ID, study instance UID, and series instance UID fields are missing), therefore they need to be fixed up before they can be imported into a DICOM database.

### Import Philips 4D cardiac images:

Get Philips QLAB cardiac analysis software with "Cartesian DICOM export" option. Your Philips representative can help you with this.

Export as Cartesian DICOM

QLAB 10.x
1. Load ultrasound volume into QLAB
1. Right-click, choose Analyze with Q-App, select any 3D Q-App, i.e., 3DQA, 3DQ or MVN (note that you do not have to Analyze, just open with the application).
1. Go in to preference to check the Cartesian export under system and click OK.
1. Click on the image export icon located in the lower left hand corner (icon: film strip with an arrow)
1. Click on "Save as", scroll down to "Cartesian DICOM (3DDCM)"
1. Choose location and click Save

QLAB 9.x
1. Load ultrasound volume into QLAB
2. Click preference
3. Click "Enable Cartesian Export" - enter password that a Philips representative provided

Note: Cartesian export does not work on color 3D datasets.

Load Cartesian DICOM into Slicer

1. Install the SlicerHeart extension and the Sequences extension in Slicer.
1. Use [Philips DICOM patcher module](ModulePhilips4dUsDicomPatcher.md) in Slicer to make the DICOM file standard compliant and/or directly export to a 4D file in NRRD format.

The file in NRRD format can be directly loaded into Slicer by drag-and-dropping to the application window.
The fixed DICOM file can be loaded into Slicer using the DICOM module (first need to be imported into Slicer's database and then it can be loaded into the scene).

# GE

GE machines save 3D/4D ultrasound data in private fields. Method to extract volumetric images from these fields is not publicly disclosed. However, some older versions of GE systems, typically used for obstetrics, used a simple file format (KretzFile) which was reverse-engineered and a publicly available importer was created.

## Loading GE Kretz ultrasound images

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

If the image fails to load then it may be compressed. You can try to load the image into [GE 4D View software](https://1drv.ms/u/s!Arm_AFxB9yqHtbJ9TqQUSLpRhTS39A) (choose "Free 60-day demo version" or "Full version" during install) and save it with "Wavelet compression" set to None.
