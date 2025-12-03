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
  - Leaflet analysis: create valve leaflet surface models from volumetric valve segmentation.
  - Valve papillary analysis: allow specify papillary muscles and chords to compute angles and lengths.
  - [Valve quantification](Docs/ValveQuantification.md): automatic computation heart valve annulus, leaflet, and papillary metrics
  - Valve batch export: run valve quantification and export results for a large cohort of data.
  - [Orifice area](Docs/OrificeArea.md): measure cross-sectional area of openings in a model, for example to quantify regurgitant orifice area.
  - [Annulus Shape Analyzer](Docs/AnnulusShapeAnalyzer.md): make population-wise observations on dynamic annular shape.
  - [Fluoro Flow Calculator](Docs/FluoroFlowCalculator.md): measuring Qp-split using readily available fluoroscopy sequences.
- Implant placement planning and assessment:
  - [Virtual Cath Lab](Docs/VirtualCathLab.md): Simulates C-arm angio suite, including 3D model of the C-arm, table, patient and generation of fluoroscopy images. Images can be either static (generated from 3D CT) or dynamic (generated from 4DCT). The module can also display cardiac devices (stents, occluders, clips, etc. provided by the Cardiac Device Simulator module) and virtual contrast filling (from image segmentation).
  - Cardiac Device Simulator: module for evaluating placement of cardiac implants. Shows all cardiac device models (Harmony device, generic cylindrical device, various ASD/VSD devices) and all available analysis tools.
  - [ASD/VSD Device Simulator](Docs/AsdVsdDeviceSimulator.md): cardiac device  simulator for ASD/VSD device placement analysis.
  - TCAV Valve Simulator
  - ValveClip Device Simulator
  - Leaflet Mold Generator: tool for automatic generation of 3D-printable molds for making simulated valves out of silicone.
- Surgical planning:
  - [Baffle planner](Docs/BafflePlanner.md): modeling tool for virtual planning of intracardiac baffle - or any other thin curved surfaces in any clinical specialties (for example, cranial flaps).
- Electrophysiology:
  - [EA Map Reader](Docs/EAMapReader.md): read electroanatomical maps from NavX, Carto3, or Rhythmia mapping systems

# Installation and setup

- Download and install 3D Slicer from http://download.slicer.org/
- Start Slicer, in the Extension manager install SlicerHeart extension (in Cardiac category), click Yes to install all dependencies, click Restart

If you have any questions about installing or using SlicerHeart modules please [post it on the Slicer forum](https://discourse.slicer.org/new-topic?category=support&tags=slicerheart).

# Authors

- Authors: Matthew Jolley (CHOP/UPenn), Andras Lasso (PerkLab, Queen's University), Christian Herz (CHOP), Csaba Pinter (Pixel Medical), Anna Ilina (PerkLab, Queen's University), Steve Pieper (Isomics), Adam Rankin (Robarts)<br>
- Contacts:
  - Matthew Jolley, <email>jolleym@email.chop.edu</email>
  - Andras Lasso, <email>lasso@queensu.ca</email>
- License: [BSD 3-Clause License](LICENSE)

# How to cite

If you utilized SlicerHeart, please cite the following paper when referring to SlicerHeart in your publication:

**Lasso, A., Herz, C., Nam, H., Cianciulli, A., Pieper, S., Drouin, S., Pinter, C., St-Onge, S., Vigil, C., Ching, S., Sunderland, K., Fichtinger, G., Kikinis, R., & Jolley, M. A. (2022). "SlicerHeart: An open-source computing platform for cardiac image analysis and modeling." Frontiers in Cardiovascular Medicine, 9. https://doi.org/10.3389/fcvm.2022.886549**

- Full-text pdf: https://www.frontiersin.org/articles/10.3389/fcvm.2022.886549/pdf
- URL: https://www.frontiersin.org/articles/10.3389/fcvm.2022.886549
- DOI: 10.3389/fcvm.2022.886549
- ISSN: 2297-055X
- bibtex:

<pre>
@ARTICLE{Lasso2022,
  title     = "{SlicerHeart}: An open-source computing platform for cardiac
               image analysis and modeling",
  author    = "Lasso, Andras and Herz, Christian and Nam, Hannah and
               Cianciulli, Alana and Pieper, Steve and Drouin, Simon and
               Pinter, Csaba and St-Onge, Samuelle and Vigil, Chad and Ching,
               Stephen and Sunderland, Kyle and Fichtinger, Gabor and Kikinis,
               Ron and Jolley, Matthew A",
  journal   = "Frontiers in Cardiovascular Medicine",
  publisher = "Frontiers Media SA",
  volume    =  9,
  month     =  sep,
  year      =  2022,
  copyright = "https://creativecommons.org/licenses/by/4.0/"
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
