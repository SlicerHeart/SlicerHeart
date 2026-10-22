"""
HeartValveTestLib: shared, GUI-free infrastructure for the SlicerHeart heart valve sequence tests.

This package is *not* a Slicer module. Test modules (ValveBrowserTest, Converter4DSequencesTest, ...)
add this package's parent directory to ``sys.path`` and import from it.

Modules:
  base       - SlicerHeartTestCase: per-test fresh scene, isolated per-method runner
  scene      - synthetic volume sequences, node census, MRB round trip, sample data access
  asserts    - assertion helpers mixed into SlicerHeartTestCase
  newformat  - NewFormatValveFactory: build valves through the branch (sequence) API
  legacy     - LegacySceneBuilder: build old-format (one HeartValve node per phase) scenes
"""

from .base import SlicerHeartTestCase, SkipTest  # noqa: F401
from . import scene, asserts  # noqa: F401
