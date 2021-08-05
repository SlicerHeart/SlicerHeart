# Baffle planner module

## Summary

Baffle planner module is a modeling tool developed for virtual planning of intracardiac baffle.

The tool can be used for modeling any other thin curved surfaces, such as cranial flaps (see [video tutorial](https://youtu.be/AigTwMYRI1Y)).

![](https://ars.els-cdn.com/content/image/1-s2.0-S0003497521004574-gr2_lrg.jpg)

## Usage

- Specify curved surface patch (Baffle):
  - In Create Baffle model section, select "Create a new Markups Closed Curve" for "Input Curve."
  - Click the arrow button next to "Contour Points" and click in viewers to place to form the outline of Baffle.
  - Choose "Create new Model" for "Baffle Model." The surface patch will appear in 3D views.
  - Click the arrow button next to "Surface Points." and place points on Baffle surface to modify the model's shape. Points can be moved after placement to adjust the shape.
- Create flattened surface patch (Baffle surface mapped to a plane with minimal distortion)
  - Create new Model for "Flattened Model."
  - Click the arrow button next to "Fixed Points," and place fixed landmark points on the Baffle surface. These points will be useful for aligning the generated flattened surface with the Baffle surface.
  - Click "Flatten" button to create flattened model. The model will appear near the (0,0,0) position, which may be far from the Baffle surface position.
  - Save the flattened image into a printable PNG file by specifying a filename (for example, `c:\Users\Public\Documents\flattened.png`) for "Flattened image file" and clicking "Save" button.

## References

Chad Vigil, et al. "Modeling Tool for Rapid Virtual Planning of the Intracardiac Baffle in Double-Outlet Right Ventricle,
The Annals of Thoracic Surgery", 2021, https://doi.org/10.1016/j.athoracsur.2021.02.058
