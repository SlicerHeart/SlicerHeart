# EA Map Reader

## Summary

This module can import of data from various 3D electroanatomic mapping systems.
The software is experimental. Users are advised to check the results in 3D Slicer against the original map on the workstation after importing.

## Usage

### Export data from the Electroanatomic Mapping System

#### NavX

1.	Load study
2.	Display data of interest (LAT/bipolar/unipolar)
3.	File -> Export
4.	Chose Export "Contact Mapping Model" option in the File: Export dialog.
(DxLandmarkGeo – surface points/connectivity/voltage of EP voltage map model.)
5.	Save as .xml file
a.	Note: This saves one electrical dataset (e.g. LAT or bipolar or unipolar) per exported map. Also, the data set is always named “MapData”, therefore the nature of the electrical data should be noted in the filename.
6.	The resulting .xml file is ready to be imported into Slicer using EAMapReader

#### CARTO3

Note: Due to a known software bug in Carto 3 version 6 the HD coloring feature needs to be temporarily disabled at the time of map export for the export feature to work as intended. Maps can still be acquired with HD coloring active.

1.	If HD coloring is active, disable it. Biosense Webster field technicians can provide guidance on how to disable and enable this feature.
2.	On the start-up screen, select “Review Study”. Open study for review
3.	Select Study -> Export Study Data… from the menu
4.  Close study review
5.	Back in the start-up screen, select “System”
6.	In the “System tools” menu, select the Export Data… button
7.	Select the correct patient. After the prior export (step 3), there should be a file called “Export_Study_[some numbers].zip” with today’s date and “RawData” in the “Type” column
8.	Select this file for export  (by clicking the arrow to the right of the file list), select the export target at the bottom of the screen, and hit export. You have to chose a password for the export.
9.	The actual study data .zip file is exported inside another (encrypted) .zip file which needs to be unpacked first. So open the .zip file with any zip extractor using the password you chose in step 8. Inside this password-protected "container" zip file there should be the actual study zip (named “Export_Study_[some numbers].zip”). Extract this file out of the container, using the password you chose.
10.	This (unencrypted) .zip file which you just took out of the export container is ready for import using EAMapReader
11. Re-enable HD coloring as necessary

#### RHYTHMIA

Close study and backup to external drive (no special export needed).
This backup consists of a folder containing (among others) several files called Study_yyyy_mm_dd_hh-mm.000, .001, .002 and so on, each up to 1 GB in size.
These files comprise the entire archived study.
Keep all .000 - .00n files in the same folder and chose the .000 for import (the others will be found accordingly by the importer, as long as the filenames match).

### Import of data into 3D Slicer

1. Raise the EAMapReader module (Modules drop down menu -> Cardiac Electrophysiology -> EAMapReader)
2. Click the button for the respective mapping system. An example data set for CARTO 3 is available [here](https://github.com/SlicerHeart/SlicerHeart/releases/download/TestingData/Carto3_EA_map.zip).
3. Choose the file exported from the mapping system

## Funding acknowledgement

The development of this software tool was in part funded through a research fellowship grant by the the Deutsche Forschungsgemeinschaft (DFG, German Research Foundation) – project no. 380200397 (to Stephan Hohmann).

## Citation
If you use EAMapReader in your own research please cite the following publication: Hohmann S, Henkenberens C, Zormpas C, Christiansen H, Bauersachs J, Duncker D, Veltmann C. A novel open-source software based high-precision workflow for target definition in cardiac radioablation. J Cardiovasc Electrophysiol. (2020) doi:10.1111/jce.14660
