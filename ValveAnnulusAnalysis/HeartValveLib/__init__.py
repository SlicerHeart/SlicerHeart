import importlib
import importlib.abc
import importlib.machinery
import os
import sys


class _SubmoduleAliasFinder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
  """Resolve bare imports of this package's submodules (``import HeartValves``) to the package
  submodules (``HeartValveLib.HeartValves``).

  The submodules of this package (and other extensions) import each other by their bare names. This
  used to be made possible by appending the package directory to sys.path, which loaded every
  submodule a second time as an unrelated top-level module: module-level state (such as the
  ValveBrowsers / ValveModels caches in HeartValves) then existed twice, and callers got different
  ValveModel objects for the same node depending on which spelling they had imported.

  The finder is appended to the end of sys.meta_path, so it is only consulted when the regular import
  machinery cannot find the module: generic names (util, helpers, Constants) keep resolving to whatever
  they resolved to before.
  """

  def __init__(self, packageName, packageDir):
    self.packageName = packageName
    self.packageDir = packageDir
    self._realSpecs = {}

  def submoduleNames(self):
    return [os.path.splitext(fileName)[0] for fileName in os.listdir(self.packageDir)
            if fileName.endswith(".py") and fileName != "__init__.py"]

  def find_spec(self, fullname, path=None, target=None):
    if "." in fullname or fullname not in self.submoduleNames():
      return None
    return importlib.machinery.ModuleSpec(fullname, self)

  def create_module(self, spec):
    module = importlib.import_module(f"{self.packageName}.{spec.name}")
    # The import machinery replaces __spec__/__loader__ of the returned module with the alias spec;
    # remember the real ones so that exec_module can restore them (importlib.reload relies on them).
    self._realSpecs[spec.name] = (module.__spec__, getattr(module, "__loader__", None))
    return module

  def exec_module(self, module):
    # The module was already executed as a package submodule, just undo the attribute changes.
    for realSpec, realLoader in self._realSpecs.values():
      if realSpec is not None and realSpec.name == module.__name__:
        module.__spec__ = realSpec
        module.__loader__ = realLoader


def _installSubmoduleAliasFinder():
  packageDir = os.path.dirname(os.path.realpath(__file__))
  # The package directory must not be on sys.path, otherwise the regular import machinery finds the
  # submodules there first and loads them a second time as top-level modules.
  sys.path[:] = [path for path in sys.path
                 if not path or os.path.normcase(os.path.realpath(path)) != os.path.normcase(packageDir)]
  for finder in sys.meta_path:
    if type(finder).__name__ == _SubmoduleAliasFinder.__name__ and getattr(finder, "packageName", None) == __name__:
      finder.packageDir = packageDir
      return
  sys.meta_path.append(_SubmoduleAliasFinder(__name__, packageDir))


_installSubmoduleAliasFinder()

from LeafletModel import *
from CoaptationModel import *
from PapillaryModel import *
from ValveModel import *
from ValveBrowser import *
from HeartValves import *
from ValveRoi import *
from Constants import *

# ValveModel and ValveBrowser are both a submodule and a class of the same name. Importing a submodule
# binds the module as package attribute and the star imports above rebind the name to the class, so
# which one callers saw used to depend on import order. In practice it was the module (the first
# HeartValves.getValveModel / getValveBrowser call imports the submodules), so make that deterministic.
# ValveRoi stays the class: ``from HeartValveLib import ValveRoi`` is used to reach ValveRoi.PARAM_*.
ValveModel = sys.modules[f"{__name__}.ValveModel"]
ValveBrowser = sys.modules[f"{__name__}.ValveBrowser"]
