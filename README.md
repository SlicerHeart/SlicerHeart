# SlicerHeart extension for 3D Slicer

SlicerHeart extension contains tools for cardiac image import (3D/4D ultrasound, CT, MRI), quantification, surgical planning, and implant placement planning and assessment.

The extension currently includes the following features (new features are added continuously):
- [Cardiac image import and export](Docs/ImageImportExport.md):
  - DICOM ultrasound image importer plugins: they allow loading Philips Affinity 3D ultrasound images, GE 3D ultrasound images and 2D image sequences, Eigen Artemis 3D ultrasound images, and some Siemens, Samsung, Canon, and Hitachi 3D ultrasound images.
  - [Philips 4D US DICOM patcher](Docs/Philips4dUsDicomPatcher.md): Cartesian 4D echo images exported by Philips QLAB are not valid DICOM files. This module fixes the files and makes them loadable into 3D Slicer.
  - [Reconstruct 4D cine-MRI](Docs/Reconstruct4DCineMRI.md): Reconstruct sequence of Cartesian volumes from a sparse set of cine-MRI frames.
  - Carto Export: export models to to be used in Carto EP mapping systems.
  - TomTec UCD data file importer: allows loading *.UCD.data.zip file as a model sequence. When drag-and-dropping the zip file to the application window, then choose "No" to the question "The selected file is a zip archive, open it and load contents" and then click OK in the displayed "Add data..." window.
- Cardiac image visualization:
  - Echo Volume Render: module for display of 3D/4D cardiac ultrasound images with distance-dependent coloring.
  - Valve View: module for visualization of heart valves: allows reslicing the volume using two rotating orthogonal planes. This feature is mainly for Slicer-4.10, as in Slicer-4.11 and later, this feature is built into Slicer core (enable slice intersections and Ctrl/Cmd + Alt + Left-click-and drag to rotate slice view).
- Quantification:
  - Valve annulus analysis: specify basic heart valve properties and annulus contour.
  - Valve segmentation: module for volumetric segmentation of heart valves.
  - Leaflet analysis: create valve leaflet surface models from volmetric valve segmentation.
  - Valve papillary analysis: allow specify papillary muscles and chords to compute angles and lengths.
  - [Valve quantification](Docs/ValveQuantification.md): automatic computation heart valve annulus, leaflet, and papillary metrics
  - Valve batch export: run valve quantification and export results for a large cohort of data.
- Implant placement planning and assessment:
  - Cardiac Device Simulator: module for evaluating placement of cardiac implants. Shows all cardiac device models (Harmony device, generic cylindrical device, various ASD/VSD devices) and all available analysis tools.
  - [ASD/VSD Device Simulator](Docs/AsdVsdDeviceSimulator.md): cardiac device  simulator for ASD/VSD device placement analysis.
  - TCAV Valve Simulator
  - ValveClip Device Simulator
  - Leaflet Mold Generator: tool for automatic generation of 3D-printable molds for making simulated valves out of silicone.
- Surgical planning:
  - [Baffle planner](Docs/BafflePlanner.md): modeling tool for virtual planning of intracardiac baffle - or any other thin curved surfaces in any clinical specialties (for example, cranial flaps).

# Installation and setup

- Download and install 3D Slicer from http://download.slicer.org/
- Start Slicer, in the Extension manager install SlicerHeart extension (in Cardiac category), click Yes to install all dependencies, click Restart

# Authors

- Authors: Matthew Jolley (CHOP/UPenn), Andras Lasso (PerkLab, Queen's University), Christian Herz (CHOP), Csaba Pinter (Pixel Medical), Anna Ilina (PerkLab, Queen's University), Steve Pieper (Isomics), Adam Rankin (Robarts)<br>
- Contacts:
  - Matthew Jolley, <email>jolleym@email.chop.edu</email>
  - Andras Lasso, <email>lasso@queensu.ca</email>
- License: [BSD 3-Clause License](LICENSE)

# How to cite

For now, until we publish the SlicerHeart platform paper, please cite the following paper when referring to SlicerHeart in your publication:

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
- Department of Anesthesia and Critical Care at The Children’s Hospital of Philadelphia(CHOP)
- The Cora Topolewski Fund at the Children's Hospital of Philadelphia
- CHOP Frontier Grant (Pediatric Valve Center)
- National Heart, Blood, and Lung Institute (NHLBI) (R01 HL153166)
- National Institute of Biomedical Imaging and Bioengineering (NIBIB) (P41 EB015902)
- Cancer Care Ontario with funds provided by the Ontario Ministry of Health and Long-Term Care
- Natural Sciences and Engineering Research Council of Canada
- Big Hearts to Little Hearts
- Children’s Hospital of Philadelphia Cardiac Center Innovation Fund
- National Cancer Institute (NCI) (contract number 19X037Q from Leidos Biomedical Research under Task Order HHSN26100071 from NCI, funding development of NCI [Imaging Data Commons](https://imagingdatacommons.github.io/))
