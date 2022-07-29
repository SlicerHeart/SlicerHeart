GE CardioVascular Ultrasound Image3dAPI loader (GEHC_CARD_US.Image3dFileLoader)
Copyright (c) 2019, GE Healthcare, Ultrasound.

API description: https://github.com/MedicalUltrasound/Image3dAPI

Content:
* bin64 folder: 64bit loader

Usage instructions:
1: Copy content of "bin64" folder to installation folder.
2A: Either: Run "regsvr32 Image3dLoaderGe.dll" to register each loader DLL in Windows registry. This must be done with administrative privileges.
2B: Or: Specify Image3dLoaderGe.dll.manifest as "Additional Manifest Files" into the project using the loader.
3: Create loader object based on "GEHC_CARD_US.Image3dFileLoader" ProgID string in client project.

The loader can be out-of-process activated using the CoCreateInstance CLSCTX_LOCAL_SERVER flag. This makes it compatible with 32bit clients.

Dependencies:
* Visual C++ Redistributable for Visual Studio 2015 Update 3 (x64): https://www.microsoft.com/en-us/download/details.aspx?id=53587
