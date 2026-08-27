# Import Mimics

## Summary

This module imports Materialise **Mimics** (`.mcs`) and **3-matic** (`.mxp`) project files into
3D Slicer: the image volume, surface models (3D objects), curves/wireframes, NURBS surfaces
(e.g. valve annuli), point sets, and patient/study/series metadata. It can load the data into the
scene, convert it to standard files, or batch-convert a whole folder of projects.

The module is experimental and not guaranteed to provide correct results for all input files.
Materialise is not affiliated with the development of this module.

![Import Mimics module](ImportMimics.jpg)

## Supported formats

Both formats store the same kind of named, individually compressed binary blobs; only the
container differs, so most of the importer is shared:

| Format | Product | Container | Typical contents |
|--------|---------|-----------|------------------|
| `.mcs` | Mimics | SQLite database | image volume(s) + segmentation surfaces, NURBS, points |
| `.mxp` | 3-matic (also written by Mimics) | ZIP-like archive with `MT` signatures | surface meshes and curves (post-processing); no image |

## What it extracts

| Content | Source blobs | Slicer output |
|---------|--------------|---------------|
| Image volumes (`.mcs`) | per image block: DICOM headers + per-slice pixel data | scalar volume(s) (or NRRD) |
| Surface models (3D objects) | `Stl{guid}_vertices`/`Stl(N)_vertices` + `..._surfaces` | model node (or PLY) |
| Curves / wireframes | `Stl..._vertices` + `Stl..._curves` | polyline model node (or VTP) |
| Point clouds | `Stl..._vertices` only (no surfaces/curves) | point-cloud model node (or PLY) |
| NURBS surfaces (`.mcs`) | `NURBS_{guid}` | closed markups curve (or `.mrk.json`) |
| Point sets (`.mcs`) | `00007FF...` blobs | markups point list (or `.mrk.json`) |
| Original DICOM series (`.mcs`) | per image block: headers + pixels | `.dcm` files in a `dicom` subfolder |
| Patient / study / series metadata (`.mcs`) | per-block DICOM headers | node attributes + JSON |
| Content inventory | blob names | JSON `contents` |

The image and the models are reconstructed in the same (patient/LPS -> Slicer RAS) coordinate
system, so segmentation surfaces overlay the image correctly.

A project may contain more than one **image block** (for example several reconstructions of the
same study, or a CT and an MR). Every block is imported: a project with a single block keeps the
plain name `image`, while the blocks of a multi-block project are numbered and tagged with their
modality (`image1_CT`, `image2_CT`, ..., `image5_MR`), since the block names in the project
header are encrypted and cannot be recovered.

Converted files are written to a subfolder named after the project (so file names themselves are
generic: `image.nrrd`, `object1.ply`, `curve1.vtp`, `points1.mrk.json`, `metadata.json`, and a
`dicom/` subfolder - with one subfolder per image block when there are several). The exported
`metadata.json` contains: `contents` (counts and ids of surface models, curves, point clouds,
NURBS surfaces and point sets present in the project), `images` (one entry per image block:
modality, manufacturer, patient/study/series identifiers, geometry - rows/columns/slice count,
pixel spacing, slice thickness/spacing, orientation and position; the first entry is also
repeated under `image`), `surfaceModels` (per-model point/triangle counts), `curves`,
`nurbsCurves`, `pointSets`, and `notes` (limitations, e.g. encrypted header or image data that
could not be reconstructed).

> **Patient information.** Mimics projects embed the original DICOM headers, which include
> patient/study identifiers (name, ID, birth date, dates). The **DICOM files** and **Metadata**
> outputs therefore may contain patient information; both are **off by default** and should be
> enabled only when you intend to export protected health information. The image, model, and
> markups outputs contain only geometry (no patient identifiers). 3-matic `.mxp` projects contain
> no image and no DICOM headers.

## Usage

1. Open the **Import Mimics** module (category: *Cardiac*). You can also open a `.mcs` / `.mxp`
   file directly via **File > Add Data** or by dragging it into the application - a registered
   file reader loads it into the scene (nothing is written to disk).
2. In **Inputs**, select a `.mcs` / `.mxp` **file**, or a **folder** to batch-convert every
   `.mcs` / `.mxp` file it contains.
3. Set the options (all in the **Inputs** section):
   - *Load into scene* - load the extracted data into the current scene (does not apply to
     folder input, which is always a batch conversion).
   - *Output folder* - **Same as input folder** (a subfolder named after each project, next to
     the project file), **Do not save converted files** (scene only), or a **Custom folder**.
   - *Content* - which data to extract and save: image volume (nrrd), surface models and
     curves (ply / vtp), NURBS curves and point sets (markups, mrk.json), original **DICOM
     files** (in a `dicom` subfolder), and a **Metadata** JSON file. DICOM files and Metadata
     are off by default (see the patient information note above).
4. Click the action button. Its label reflects the operation:
   - **Load** / **Convert** / **Convert & Load** - single file, into the scene and/or to files.
   - **Batch convert** - folder input; converts every `.mcs` / `.mxp` to files.
   - **Inspect** - neither loading nor saving is selected; logs a summary of the selected
     file/folder to the message box without creating nodes or writing files.

All options are remembered between sessions (stored in the application settings).

## Limitations

- Object names, colors, and analysis measurements live in the encrypted `header.xml` and cannot
  be recovered (both formats). Objects are named generically (`object1`, `curve1`, ...).
- 3-matic `.mxp` projects contain no image volume (only meshes/curves); the image stays in the
  originating Mimics project.
- Analysis entities in `.mxp` (`blob_NNNN`: measurements, coordinate systems, planes) are not
  imported.
- Curves are imported as polyline **model** nodes (not editable markups curves) because they are
  stored as dense sampled points; they are exported as `.vtp` (which, unlike `.ply`, stores
  lines).
- The mesh coordinate scale (`1e-4` mm) and the header/pixel pairing were determined empirically
  from sample files; unusual projects may need adjustment.
- The module is experimental and not guaranteed to provide correct results for all input files.

## Developers

Both file types are containers of named binary blobs. `ImportMimicsLogic.openStore()` sniffs the
file magic and returns a blob store (`_SqliteBlobStore` or `_MxpBlobStore`), each exposing
`.names` (the set of member names) and `.read(name)` (decompressed bytes); all of the geometry
decoding is written against that interface.

A **`.mcs`** file is a **SQLite** database:

- `blobs(blob_id, blob_name, number_of_parts)`
- `blobs_parts(blob_id, blob_part_number, is_blob_compressed, orig_size, blob_part_data)` -
  each part is optionally `zlib`-compressed; concatenate parts in order to get the blob.

A **`.mxp`** file is a **ZIP archive in which the `PK` signatures are replaced with `MT`**
(Materialise). Each member has a standard 30-byte local file header (`MT\x03\x04`, version,
flags, method, crc32, compressed/uncompressed size, name length, extra length) followed by the
name and the raw-DEFLATE (method 8) or stored (method 0) data, and a trailing central directory
(`MT\x01\x02`) plus end-of-central-directory record (`MT\x05\x06`) mirror ZIP.

The members are read from the **central directory**, not by walking the local headers: 3-matic
writes each member with general purpose flag `0x08` (data descriptor), which leaves the sizes in
the local header set to zero and puts the real ones in a `PK\x07\x08` record *after* the data.
Walking the local headers therefore stops at the first member; only the central directory gives
both the sizes and the local header offsets. (Archives that do record their sizes in the local
headers are still read by walking them, as a fallback.)

There is also a plaintext `log_data` member (the project's operation log, which records the
authoring Mimics/3-matic version) and a `preview_256x256` placeholder.

Relevant blobs (shared between the formats unless noted):

- **Image blocks** (`.mcs`) - an image block is a **header blob** followed by one **pixel-data
  blob per slice**. The header blob holds the original DICOM files concatenated (each: 128-byte
  preamble + `DICM` + dataset, optionally after a few bytes of Materialise's own), one per slice
  and **with the pixel data removed**; it provides the geometry (`ImagePositionPatient`,
  `ImageOrientationPatient`, `PixelSpacing`, `Rows`/`Columns`) and the patient/study/series
  information. Pixel blobs are paired with the headers in acquisition order, then the slices are
  sorted spatially along the slice normal.

  A plain Mimics project holds a single block, named `blob_0` (headers) + `blob_1`, `blob_2`,
  ... (pixels). A project exported for **Mimics Viewer** may hold several blocks and names every
  blob with a GUID, so only the *order* of the blobs groups a block together: a header blob
  starts a block and the pixel blobs that follow belong to it (a block may be followed by extra
  blobs, such as a downsampled preview of the block, which the DICOM instance count excludes).
- **Pixel data** (`.mcs`) - each pixel blob starts with a 4-byte `MMFD` magic. The pixels then
  follow either uncompressed (`Rows*Columns*2` bytes of little-endian 16-bit pixels) or, where
  that is smaller, **row-compressed**: a table of `Rows` little-endian `uint16` compressed row
  lengths, followed by the rows. A row is a sequence of 16-bit **big-endian** tokens whose top
  two bits select the token type:
  - `00` / `01` - one pixel, stored as the absolute value in the remaining 14 bits (used wherever
    the difference from the previous pixel does not fit in a signed byte);
  - `10` - a run of `N` pixels (`N` = the remaining 14 bits) follows as `N` bytes, each a signed
    8-bit difference from the preceding pixel;
  - `11` - a column index in the remaining 14 bits. A row starts with two of these: the first and
    the last column it covers.

  So a row costs roughly one byte per pixel; both variants occur within one image block, chosen
  per slice.
- **`Stl{guid}_vertices`** / **`Stl(N)_vertices`** - vertex coordinates as little-endian `int32`
  triplets in **millimeters x 10000** (LPS/patient coordinate system). Two id styles occur:
  `{guid}` and `(integer)`.
- **`Stl..._surfaces`** - triangle vertex indices as little-endian `int32` triplets.
- **`Stl..._curves`** (`.mxp`) - a contour/wireframe as an ordered list of little-endian `int32`
  indices into the object's own `_vertices`. Following the index order yields the polyline; if
  the first and last index coincide the curve is closed. An object may have `_surfaces` and/or
  `_curves` (or, rarely, `_vertices` only - a point cloud).
- **`NURBS_{guid}`** (`.mcs`) - a closed cubic B-spline curve (valve annulus): `N` weighted
  control points as `float64` `(x, y, z, w=1)` in LPS mm, followed by the `float64` knot vector
  (`len = N + degree + 1`, `degree = 3`, unclamped/periodic). Evaluated with de Boor and imported
  as a closed markups curve.
- **`00007FF...`** (`.mcs`) - a point set: `float64` `(x, y, z)` triplets in LPS mm (no header),
  imported as a markups point list.
- **`header.xml`** - project structure (object names, colors, analysis data). Stored
  **encrypted** by Materialise (a block cipher - identical 16-byte plaintext blocks map to
  identical ciphertext blocks); not decoded, so object names and colors are not recovered.
