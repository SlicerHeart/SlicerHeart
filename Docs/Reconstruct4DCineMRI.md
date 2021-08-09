# Reconstruct 4D cine-MRI

## Summary

This module reconstructs a 4D volume (sequence of 3D Cartesian volumes) from a sparse set of cine-MRI frames. Image frames are typically acquired in a rotating frame pattern. See [demo video on YouTube](https://youtu.be/hIxr9OKBvQ8).

[![](https://img.youtube.com/vi/hIxr9OKBvQ8/0.jpg)](https://youtu.be/hIxr9OKBvQ8 "Demo video of volume reconstruction from sparse frame set")

## Usage

### Setup

- Install Slicer
- Start Slicer, install SlicerHeart and SlicerIGSIO extensions from the Extensions Manager
- Restart Slicer

### Reconstruct 4D volume from cine-MRI frames

- Import the cine-MRI acquisition using the DICOM module: switch to DICOM module and drag-and-drop the folder that contains the DICOM files to the application window
- Load the cine-MRI data set by double-clicking on the cine-MRI series in the DICOM browser
- Create an Annotation ROI node: click the down-arrow in the "Create and place" button on the toolbar, choose the "ROI" option at the top, then click in the middle of the region of interest in a slice view, then at a corner of a region of interest in the same slice view.
- Switch to "Reconstruct 4D cine-MRI" module
- Select the loaded cine-MRI sequence as "Input sequence"
- Select the created ROI node as "Input region"
- Optional: Adjust the "Output spacing" to adjust the resolution of the reconstructed volume. Smaller values results in finer details but longer reconstruction time and potentially more unfilled holes in the reconstructed volume.
- Click Apply to reconstruct the volume.
- Click the "Play" button in the toolbar to view the reconstructed volume sequence.

### Reconstruct volume with custom frame grouping

By default, the module automatically determines how to order and group frames to make up volumes. For this, it assumed that:
- ECG-gated images are acquired throughout multiple cardiac cycles. First N frames are acquired in the first frame position/orientation, then N frames are acquired in the second frame position/orientation, etc.
- The "Trigger Time" DICOM field is reset to the starting value when changing position/orientation (and the trigger value is increasing through the cardiac cycle).

If these assumptions are not correct then it is necessary to specify the index of each frame that make up each volume:
- Open "Advanced" section
- Disable "auto-detect"
- Type the list of frame indices (integer values, starting with 0), for each volume that will be reconstructed. Frame indices for an output volume are separated by spaces, indices are in a row for each output volume.

## Information for Developers

The module is implemented as a scripted module. Source code is available at:

https://github.com/SlicerHeart/SlicerHeart/tree/master/Reconstruct4DCineMRI
