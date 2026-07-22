# Import Mimics

## Summary

This module imports Materialise **Mimics** project files (`.mcs`) into 3D Slicer: the image
volume, surface models (3D objects), NURBS surfaces (e.g. valve annuli), point sets, and
patient/study/series metadata. It can load the data into the scene, convert it to standard
files, or batch-convert a whole folder of projects.

The module is experimental and not guaranteed to provide correct results for all input files.
Materialise is not affiliated with the development of this module.

![Import Mimics module](ImportMimics.jpg)

## What it extracts

| Content | Source in the `.mcs` file | Slicer output |
|---------|---------------------------|---------------|
| Image volume | `blob_0` (DICOM headers) + `blob_N` (pixel data) | scalar volume (or NRRD) |
| Surface models (3D objects) | `Stl{guid}_vertices` / `Stl{guid}_surfaces` | model node (or PLY) |
| NURBS surfaces (e.g. valve annuli) | `NURBS_{guid}` | closed markups curve (or `.mrk.json`) |
| Point sets | `00007FF...` blobs | markups point list (or `.mrk.json`) |
| Original DICOM series | `blob_0` headers + `blob_N` pixels | `.dcm` files in a `dicom` subfolder |
| Patient / study / series metadata | DICOM headers in `blob_0` | node attributes + JSON |
| Content inventory | blob names | JSON `contents` |

The image and the models are reconstructed in the same (patient/LPS -> Slicer RAS) coordinate
system, so segmentation surfaces overlay the image correctly.

Converted files are written to a subfolder named after the project (so file names themselves are
generic: `image.nrrd`, `object1.ply`, `curve1.mrk.json`, `points1.mrk.json`, `metadata.json`, and
a `dicom/` subfolder). The exported `metadata.json` contains: `contents` (counts and GUIDs of surface models,
NURBS surfaces, point sets and image previews present in the project), `image` (modality,
manufacturer, patient/study/series identifiers, geometry - rows/columns/slice count, pixel
spacing, slice thickness/spacing, orientation and position), `surfaceModels` (per-model
point/triangle counts), `nurbsCurves`, `pointSets`, and `notes` (limitations, e.g. encrypted
header or image data that could not be reconstructed).

> **Patient information.** Mimics projects embed the original DICOM headers, which include
> patient/study identifiers (name, ID, birth date, dates). The **DICOM files** and **Metadata**
> outputs therefore may contain patient information; both are **off by default** and should be
> enabled only when you intend to export protected health information. The image, model, and
> markups outputs contain only geometry (no patient identifiers).

## Usage

1. Open the **Import Mimics** module (category: *Cardiac*). You can also open a `.mcs` file
   directly via **File > Add Data** or by dragging it into the application - a registered file
   reader loads it into the scene (nothing is written to disk).
2. In **Inputs**, select a `.mcs` **file**, or a **folder** to batch-convert every `.mcs` file
   it contains.
3. Set the options (all in the **Inputs** section):
   - *Load into scene* - load the extracted data into the current scene (does not apply to
     folder input, which is always a batch conversion).
   - *Output folder* - **Same as input folder** (a subfolder named after each project, next to
     the `.mcs` file), **Do not save converted files** (scene only), or a **Custom folder**.
   - *Content* - which data to extract and save: image volume (nrrd), surface
     models (ply), NURBS curves and point sets (markups, mrk.json), original **DICOM files** (in
     a `dicom` subfolder), and a **Metadata** JSON file. DICOM files and Metadata are off by
     default (see the patient information note above).
4. Click the action button. Its label reflects the operation:
   - **Load** / **Convert** / **Convert & Load** - single file, into the scene and/or to files.
   - **Batch convert** - folder input; converts every `.mcs` to files.
   - **Inspect** - neither loading nor saving is selected; logs a summary of the selected
     file/folder to the message box without creating nodes or writing files.

All options are remembered between sessions (stored in the application settings).

## Limitations

- Object names, colors, and analysis measurements live in the encrypted `header.xml` and cannot
  be recovered.
- The mesh coordinate scale (`1e-4` mm) and the header/pixel pairing were determined empirically
  from sample files; unusual projects may need adjustment.
- Some projects store pixel data in a compressed/variant layout that is not decoded; in that
  case the surface models, curves, points and metadata are still imported, but not the image.
- The module is experimental and not guaranteed to provide correct results for all input files.

## Developers

A `.mcs` file is a **SQLite** database with a simple blob container:

- `blobs(blob_id, blob_name, number_of_parts)`
- `blobs_parts(blob_id, blob_part_number, is_blob_compressed, orig_size, blob_part_data)` -
  each part is optionally `zlib`-compressed; concatenate parts in order to get the blob.

Relevant blobs:

- **`blob_0`** - the original DICOM files concatenated (each: 128-byte preamble + `DICM` +
  dataset), one per slice, **with the pixel data removed**. Provides geometry
  (`ImagePositionPatient`, `ImageOrientationPatient`, `PixelSpacing`, `Rows`/`Columns`) and
  patient/study/series information.
- **`blob_1`, `blob_2`, ...** - per-slice pixel data. Each starts with a 4-byte `MMFD` magic
  followed by `Rows*Columns*2` bytes of little-endian 16-bit pixels. Paired with the DICOM
  headers in acquisition order; slices are then sorted spatially along the slice normal.
- **`Stl{guid}_vertices`** - vertex coordinates as little-endian `int32` triplets in
  **millimeters x 10000** (LPS/patient coordinate system).
- **`Stl{guid}_surfaces`** - triangle vertex indices as little-endian `int32` triplets.
- **`NURBS_{guid}`** - a closed cubic B-spline curve (valve annulus): `N` weighted control
  points as `float64` `(x, y, z, w=1)` in LPS mm, followed by the `float64` knot vector
  (`len = N + degree + 1`, `degree = 3`, unclamped/periodic). Evaluated with de Boor and
  imported as a closed markups curve.
- **`00007FF...`** - a point set: `float64` `(x, y, z)` triplets in LPS mm (no header), imported
  as a markups point list.
- **`header.xml`** - project structure (object names, colors, analysis data). Stored
  **encrypted** by Mimics (zlib-compressed ciphertext); not decoded, so object names and colors
  are not recovered - objects are named `object1`, `curve1`, `points1`, ...
