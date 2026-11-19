"""Progress reporting and cancelling of long operations."""

import time

import vtk

from slicer.i18n import tr as _


class OperationCancelledError(Exception):
    """Raised by an import or export that was cancelled."""


class OperationMonitor:
    """Lets a long operation report its progress and be cancelled while it is running.

    The operation calls check() between its steps and runs its VTK algorithms with update().
    Both call progressCallback, which can show the progress, process the events of the
    application, and call cancel() if the user asked for it. The operation then stops by
    raising OperationCancelledError.
    """

    def __init__(self):
        # Called with the progress of the current step (0.0-1.0), or None if it is not known.
        self.progressCallback = None
        # Minimum time between two calls of the callback, in seconds. Progress may be reported
        # many thousand times a second, processing the application events each time would be slow.
        self.callbackInterval = 0.1
        self._cancelRequested = False
        self._lastCallbackTime = 0.0

    def reset(self) -> None:
        """Forget a cancel request that no operation has stopped for."""
        self._cancelRequested = False
        self._lastCallbackTime = 0.0

    def cancel(self) -> None:
        """Ask the running operation to stop as soon as it can."""
        self._cancelRequested = True

    def _isCancelRequested(self, progress=None):
        if (not self._cancelRequested and self.progressCallback is not None
                and time.time() - self._lastCallbackTime >= self.callbackInterval):
            self.progressCallback(progress)
            self._lastCallbackTime = time.time()
        return self._cancelRequested

    def check(self, progress=None) -> None:
        """Report the progress of the current step, and stop the operation if it was cancelled."""
        if self._isCancelRequested(progress):
            # The request has been fulfilled, it must not stop the next operation as well.
            self._cancelRequested = False
            raise OperationCancelledError(_("The operation was cancelled."))

    def update(self, algorithm, update=None):
        """Run a VTK algorithm, so that it can be cancelled while it is running.

        An algorithm can only be cancelled while it is running if it reports its progress, because
        that is the only time when the application can process a click on a cancel button.
        Otherwise, the operation stops when the algorithm has finished.

        :param update: function that runs the algorithm, by default the Update method of it.
        :return: what the update function returned.
        """
        def onProgress(caller, event):
            # An exception cannot be raised through the algorithm, it is asked to stop instead.
            if self._isCancelRequested(caller.GetProgress()):
                caller.SetAbortExecute(True)

        observerTag = algorithm.AddObserver(vtk.vtkCommand.ProgressEvent, onProgress)
        try:
            result = update() if update is not None else algorithm.Update()
        finally:
            algorithm.RemoveObserver(observerTag)
        self.check()
        return result
