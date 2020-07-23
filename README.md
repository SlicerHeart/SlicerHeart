# SlicerHeart extension for 3D Slicer

SlicerHeart extension contains tools for cardiac image import (3D/4D ultrasound, CT, MRI), quantification, and implant placement planning and assessment.

The extension currently includes the following features (new features are added continuously):
- DICOM image importer plugins
  - Fixing and importing of Philips 4D ultrasound images: Cartesian DICOM images exported by Philips QLAB are not valid DICOM files. This module fixes the files and makes them loadable into 3D Slicer.
  - Importing of Philips Affinity 3D images.
  - Importing of GE 3D images and 2D image sequences.
  - Importing of Eigen Artemis images.
- TomTec UCD data file importer: allows loading *.UCD.data.zip file as a model sequence. When drag-and-dropping the zip file to the application window, then choose "No" to the question "The selected file is a zip archive, open it and load contents" and then click OK in the displayed "Add data..." window.
- Cardiac Device Simulator: module for evaluating placement of cardiac implants. Shows all cardiac device models (Harmony device, generic cylindrical device, various ASD/VSD devices) and all available analysis tools.
- ASD/VSD Device Simulator: simplified cardiac device simulator specifically for ASD/VSD device placement analysis. Implements features described in: "Simulation of Transcatheter Atrial and Ventricular Septal Defect Device Closure Within Three-Dimensional Echocardiography–Derived Heart Models on Screen and in Virtual Reality", Journal of the American Society of Echocardiography, https://doi.org/10.1016/j.echo.2020.01.011.
- Valve View: module for visualization of heart valves: allows reslicing the volume using two rotating orthogonal planes. This feature is mainly for Slicer-4.10, as in Slicer-4.11 and later, this feature is built into Slicer core (enable slice intersections and Ctrl/Cmd + Alt + Left-click-and drag to rotate slice view).

# Installation and setup

- Download and install 3D Slicer from http://download.slicer.org/
- Start Slicer, in the Extension manager install SlicerHeart extension (in Cardiac category), click Yes to install all dependencies, click Restart

# Importing DICOM files

While DICOM standard specifies how 3D and 4D (3D+t) ultrasound volumes can be stored in standard fields, most ultrasound manufacturers do not follow this standard. Typically, only 2D screenshots or 2D+t screen capture videos are stored in standard fields. 3D information is stored in private fields and proprietary algorithms are needed to interpret them.

## Open Image3D API

[Image3D API](https://github.com/MedicalUltrasound/Image3dAPI) can be used to read 3D ultrasound images from GE, Canon, Hitachi, Siemens, and Philips scanners. This API is only avaialble on Windows and a reader library must be obtained from the scanner's manufacturer and installed on the system (by registering the reader by running `regsvr32 (loaderlibraryname).dll` as an administrator). This API can provide access to all kinds of image data and ECG signal. File can be read by renaming it so that it ends with `.3dus` and drag-and-dropping to the Slicer application window. GE 3D ultrasound images can be also loaded using the DICOM module (then the files do not have to be renamed).

Additional vendor-specific file reading options are described below.

## Philips

### Import Philips 4D cardiac images:

Philips machines save 3D/4D ultrasound data in private fields. Method to extract volumetric images from these fields is not publicly disclosed. However, Philips QLAB cardiac analysis software can export images to a DICOM format variant, which stores volumetric images in standard fields, which can be interpreted without proprietary methods. Unfortunately, these DICOM files are not fully DICOM compliant (required fields, such as SOP instance UID, patient name, ID, study instance UID, and series instance UID fields are missing), therefore they need to be fixed up before they can be imported into a DICOM database.

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

### Import Philips Affinity 3D images:

Philips Affinity systems can export acquired 3D ultrasound volumes in DICOM format, but slice spacing is not stored in private DICOM fields (see more information [here](https://discourse.slicer.org/t/problem-importing-a-volumen-with-a-phillips-affinity-50/5065/8)). If SlicerHeart extension is installed and data is loaded using DICOM module (as described below) then Slicer will retrieve this information from these private fields and the volume will be loaded correctly.

To export 3D volumes from your ultrasound system to DICOM, enable 3D export in application settings.

Load data from DICOM folder:
- Drag-and-drop your image folder to the Slicer application window
- In the popup window click OK (to load directory into DICOM database)
- Click Copy (to make a local copy of the folder into the Slicer database) or Add link (to not copy data files, data will not be available if the original folder is removed)
- Wait for the import operation to complete, click OK
- In the DICOM browser window, select data to load and click Load button
- Wait for loading to complete (may take a few minutes)

## GE

GE machines save 3D/4D ultrasound data in private fields. They can be decoded using Image3dAPI DLL obtained from GE. Some older versions of GE systems, typically used for obstetrics, used a simple file format (KretzFile) which was reverse-engineered and a publicly available importer was created and made available in SlicerHeart.

### Loading various 3D/4D ultrasound images using Image3dAPI

Obtain Image3dAPI package from GE, unzip its content to a folder, and run `regsvr32 Image3dLoaderGe.dll` command as an administrator to install it. After that, GE 3D/4D ultrasound files can be loaded using DICOM module (alternatively, individual 3D/4D ultrasound file can be loaded by renaming it to end with `.3dus` and drag-and-drop to the Slicer application window, and click OK).

### Loading GE Kretz ultrasound images

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

### Loading ultrasound GE moviegroup DICOM files

Ultrasound image sequences can be loaded from DICOM files that store data in GE moviegroup DICOM tags. A current limitation that no scan conversion is performed but raw scanlines are displayed in a rectangular shape. For linear probes, correct image size and aspect ratio can be restored for images that are acquired with linear probes by applying scaling using a linear transform (in Transforms module).

Load data from DICOM folder:
- Drag-and-drop your image folder to the Slicer application window
- In the popup window click OK (to load directory into DICOM database)
- Click Copy (to make a local copy of the folder into the Slicer database) or Add link (to not copy data files, data will not be available if the original folder is removed)
- Wait for the import operation to complete, click OK
- In the DICOM browser window, select data to load and click Load button
- Click OK to accept warnings (the warning is displayed because the importer is still experimental and the images may be slightly distorted)

## Samsung

Some Samsung ultrasound machines store 3D ultrasound images in proprietary .mvl files. Exact format of these files are not reverse-engineered yet, but since image data is stored uncompressed, [RawImageGuess extension](https://github.com/acetylsalicyl/SlicerRawImageGuess) can be used to read these files with some manual tuning as described in this [forum topic](https://discourse.slicer.org/t/could-not-load-ultrasound-from-mvl-medison-file-format/3928/22?u=lassoan).

## Eigen Artemis

Eigen Artemis is using Ultrasound Multi-frame Image IOD, which does not encode image geometry information. Below is the commentary of David Clunie (@dclunie) on Eigen Artemis approach to data encoding.

>  the reason there is no geometry information is that the US image is just an instance of the (ancient) Ultrasound Multi-frame Image IOD [1], and not an Enhanced US Volume IOD [2].
>
>Remember that the original US image storage SOP Classes were defined in the era of video capture, and further, it was (and still is) common to include multiple types of data in the same screen (frame) (not necessarily with the same geometry).
>
>FYI, any 2D spatial information, if there is any (and it isn't often) should be in Region Calibration [3], not in Pixel Spacing, etc., and there is no (standard) way to communicate geometric orientation or position between frames (or relative to any 3D frame of reference).
>
>The use of the ancient SOP Class is also the reason why dciodvfy does not complain much, since there is not much to complain about.
>
>It would obviously be far preferable (for us) if the submitter did created an Enhanced US Volume instance, but then probably nobody would be able to display it, so in a clinical product they would have to be able to create both, depending on what the user could cope with. They could stuff the Enhanced US Volume attributes (esp. the spatial macros) in the old SOP Class (as a Standard Extended SOP Class), which would probably be a good compromise.
>
>References
>
>http://dicom.nema.org/medical/dicom/current/output/chtml/part03/sect_A.7.html
>
>http://dicom.nema.org/medical/dicom/current/output/chtml/part03/sect_A.59.html
>
>http://dicom.nema.org/medical/dicom/current/output/chtml/part03/sect_C.8.5.5.html

Instructions on reconstructing 3D volume using manufacturer-specific conventions were provided
by Rajesh Venkataraman from Eigen on Feb 10, 2020 and are listed below. Those instructions are implemented
in the Eigen Artemis 3D US plugin of SlicerHeart.

> please take the PixelAspectRatio tag divide by 1000 and that would be your isotropic resolution for display in all 3 dimensions.
>
> Image Patient Orientation would be [1 0 0; 0 1 0] for each frame
>
>The origin of the volume is the center of the 3D cube and the span would be
>
> * For X: `[-0.5*Rows*PixelAspectRatio[0]/1000, -0.5*Rows*PixelAspectRatio[0]/1000 ]`
> * For Y: `[-0.5*Columns*PixelAspectRatio[0]/1000, -0.5*Columns*PixelAspectRatio[0]/1000 ]``
> * For Z: `[-0.5*NumberOfSlices*PixelAspectRatio[0]/1000, -0.5* NumberOfSlices *PixelAspectRatio[0]/1000 ]``

# Authors

- Authors: Matthew Jolley (CHOP), Andras Lasso (PerkLab), Christian Herz (CHOP), Anna Ilina (PerkLab), Steve Pieper (Isomics), Adam Rankin (Robarts)<br>
- Contacts:
  - Matthew Jolley, <email>jolleym@email.chop.edu</email>
  - Andras Lasso, <email>lasso@queensu.ca</email>
- License: [Slicer license](http://www.slicer.org/pages/LicenseText) (non-restrictive, BSD-type license)

# How to cite

Please cite the following paper when referring to SlicerHeart in your publication:

Scanlan AB, Nguyen AV, Ilina A, Lasso A, Cripe L, Jegatheeswaran A, Silvestro E, McGowan FX, Mascio CE, Fuller S, Spray TL, Cohen MS, Fichtinger G, Jolley MA,
["Comparison of 3D Echocardiogram-Derived 3D Printed Valve Models to Molded Models for Simulated Repair of Pediatric Atrioventricular Valves"](http://perk.cs.queensu.ca/sites/perkd7.cs.queensu.ca/files/Scanlan2017.pdf),
Pediatr Cardiol. 2018 Mar; 39(3):538-547. [doi: 10.1007/s00246-017-1785-4](https://www.ncbi.nlm.nih.gov/pubmed/29181795).

<pre>
@Article{Scanlan2018,
  author =        {Scanlan, Adam B. and Nguyen, Alex V. and Ilina, Anna and Lasso, Andras and Cripe, Linnea and Jegatheeswaran, Anusha and Silvestro, Elizabeth and McGowan, Francis X. and Mascio, Christopher E. and Fuller, Stephanie and Spray, Thomas L. and Cohen, Meryl S. and Fichtinger, Gabor and Jolley, Matthew A.},
  title =         {Comparison of 3D Echocardiogram-Derived 3D Printed Valve Models to Molded Models for Simulated Repair of Pediatric Atrioventricular Valves},
  journal =       {Pediatric Cardiology},
  year =          {2018},
  volume =        {39},
  number =        {3},
  pages =         {538},
  month =         mar,
  abstract =      {Mastering the technical skills required to perform pediatric cardiac valve surgery is challenging in part due to limited opportunity for practice. Transformation of 3D echocardiographic (echo) images of congenitally abnormal heart valves to realistic physical models could allow patient-specific simulation of surgical valve repair. We compared materials, processes, and costs for 3D printing and molding of patient-specific models for visualization and surgical simulation of congenitally abnormal heart valves. Pediatric atrioventricular valves (mitral, tricuspid, and common atrioventricular valve) were modeled from transthoracic 3D echo images using semi-automated methods implemented as custom modules in 3D Slicer. Valve models were then both 3D printed in soft materials and molded in silicone using 3D printed “negative” molds. Using pre-defined assessment criteria, valve models were evaluated by congenital cardiac surgeons to determine suitability for simulation. Surgeon assessment indicated that the molded valves had superior material properties for the purposes of simulation compared to directly printed valves (p < 0.01). Patient-specific, 3D echo-derived molded valves are a step toward realistic simulation of complex valve repairs but require more time and labor to create than directly printed models. Patient-specific simulation of valve repair in children using such models may be useful for surgical training and simulation of complex congenital cases.},
  date =          {2018-03-01},
  doi =           {10.1007/s00246-017-1785-4},
  issn =          {1432-1971},
  publisher =     {Springer},
  url =           {http://dx.doi.org/10.1007/s00246-017-1785-4}
}
</pre>

# Acknowledgments

This work was partially supported by:
- Department of Anesthesia and Critical Care at The Children’s Hospital of Philadelphia
- National Institute of Biomedical Imaging and Bioengineering (NIBIB) (P41 EB015902)
- Cancer Care Ontario with funds provided by the Ontario Ministry of Health and Long-Term Care
- Natural Sciences and Engineering Research Council of Canada
- Big Hearts to Little Hearts
- Children’s Hospital of Philadelphia Cardiac Center Innovation Fund
- National Cancer Institute (NCI) (contract number 19X037Q from Leidos Biomedical Research under Task Order HHSN26100071 from NCI, funding development of NCI [Imaging Data Commons](https://imagingdatacommons.github.io/))
