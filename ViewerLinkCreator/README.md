# Viewer Link Creator

Generate a link to share a Slicer scene with users of a web viewer application.

> [!NOTE]
> The current implementation is set up for [Omnissa Horizon](https://www.omnissa.com/products/horizon-8/) with a published viewer application (e.g., Slicer launched into the [Simplified Viewer](../SimplifiedViewer/README.md)). When a user opens the shared link, Horizon launches the published application and passes the arguments parsed from the URL to it.

## Usage

- Go to `ViewerLinkCreator` module
- Set the parameters:
  - `Base URL`: Horizon portal address
  - `App`: name of the published application to launch
  - `User name` (optional): user name to pre-fill at login
  - `File name` (optional): path of the scene file (`.mrb` or `.mrml`) to load in the viewer. The path must be accessible from the machine that runs the published application.
- Click `Update` to generate the link, or `Copy to clipboard` to generate it and copy it to the clipboard (Windows only)

The generated link has the following format:

```
<Base URL>?userName=<User name>&applicationId=<App>&args=<File name>
```

The `args` value is passed to the published application as a command-line argument. For example, the [Slicer Startup Accelerator](../Utilities/SlicerStartupAccelerator) `run.bat` script starts Slicer, loads the specified scene, and switches to the Simplified Viewer.
