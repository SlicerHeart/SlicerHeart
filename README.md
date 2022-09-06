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

If you utilized SlicerHeart, please cite the following paper when referring to SlicerHeart in your publication:

https://www.frontiersin.org/articles/10.3389/fcvm.2022.886549/full


<pre>
AUTHOR=Lasso Andras, Herz Christian, Nam Hannah, Cianciulli Alana, Pieper Steve, Drouin Simon, Pinter Csaba, St-Onge Samuelle, Vigil Chad, Ching Stephen, Sunderland Kyle, Fichtinger Gabor, Kikinis Ron, Jolley Matthew A.
	 
TITLE=SlicerHeart: An open-source computing platform for cardiac image analysis and modeling  
	
JOURNAL=Frontiers in Cardiovascular Medicine     
	
VOLUME=9      
	
YEAR=2022   
		
URL=https://www.frontiersin.org/articles/10.3389/fcvm.2022.886549     
	  
DOI=10.3389/fcvm.2022.886549    
	
ISSN=2297-055X   

ABSTRACT=Cardiovascular disease is a significant cause of morbidity and mortality in the developed world. 3D imaging of the heart's structure is critical to the understanding and treatment of cardiovascular disease. However, open-source tools for image analysis of cardiac images, particularly 3D echocardiographic (3DE) data, are limited. We describe the rationale, development, implementation, and application of SlicerHeart, a cardiac-focused toolkit for image analysis built upon 3D Slicer, an open-source image computing platform. We designed and implemented multiple Python scripted modules within 3D Slicer to import, register, and view 3DE data, including new code to volume render and crop 3DE. In addition, we developed dedicated workflows for the modeling and quantitative analysis of multi-modality image-derived heart models, including heart valves. Finally, we created and integrated new functionality to facilitate the planning of cardiac interventions and surgery. We demonstrate application of SlicerHeart to a diverse range of cardiovascular modeling and simulation including volume rendering of 3DE images, mitral valve modeling, transcatheter device modeling, and planning of complex surgical intervention such as cardiac baffle creation. SlicerHeart is an evolving open-source image processing platform based on 3D Slicer initiated to support the investigation and treatment of congenital heart disease. The technology in SlicerHeart provides a robust foundation for 3D image-based investigation in cardiovascular medicine.
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
