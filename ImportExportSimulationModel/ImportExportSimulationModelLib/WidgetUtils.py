"""Parts of a module widget that are not specific to this module: progress display and event filters."""

import os
import time

import qt
import slicer
from slicer.i18n import tr as _

from ImportExportSimulationModelLib.OperationMonitor import OperationCancelledError


class OperationProgress:
    """Runs operations while showing their progress and their log, and lets the user cancel them.

    The progress and the cancel requests are exchanged with the operation through an
    OperationMonitor that the operation uses.
    """

    def __init__(self, monitor, progressBar, cancelButton, logTextEdit, sectionButton=None) -> None:
        """
        :param monitor: OperationMonitor that the operations report their progress to.
        :param progressBar: QProgressBar, shown only while an operation is running.
        :param cancelButton: QPushButton, shown only while an operation is running.
        :param logTextEdit: QPlainTextEdit that the log messages are added to.
        :param sectionButton: collapsible button that contains the widgets above. It is opened
            when an operation is started, so that the Cancel button is visible.
        """
        self.monitor = monitor
        self.progressBar = progressBar
        self.cancelButton = cancelButton
        self.logTextEdit = logTextEdit
        self.sectionButton = sectionButton
        self._operationInProgress = False
        # The log of the previous operation is cleared when the current operation logs its first message
        self._clearLogBeforeNextMessage = False
        self.cancelButton.connect("clicked(bool)", self.cancel)
        self._setProgressVisible(False)

    def disconnect(self) -> None:
        """Release the widgets. The object cannot be used after this."""
        self.cancelButton.disconnect("clicked(bool)", self.cancel)

    def _setProgressVisible(self, visible) -> None:
        self.progressBar.visible = visible
        self.cancelButton.visible = visible

    def _showProgress(self) -> None:
        """Show the progress bar and the Cancel button, also if their section is collapsed or scrolled out."""
        self._setProgressVisible(True)
        if self.sectionButton is not None:
            self.sectionButton.collapsed = False
        slicer.app.processEvents()
        scrollArea = self.cancelButton.parent()
        while scrollArea is not None and not scrollArea.inherits("QScrollArea"):
            scrollArea = scrollArea.parent()
        if scrollArea is not None:
            scrollArea.ensureWidgetVisible(self.cancelButton)

    def run(self, operation, errorMessage, cancelledMessage, clearLog=True, displayDelay=0.0) -> bool:
        """Run an operation, showing its progress, until it is completed or the user cancels it.

        The application processes its events while the operation is running, so that the progress
        bar is updated and the Cancel button can be clicked. All other user input is discarded in
        the meantime, therefore the user cannot change the scene or the settings of the module.

        :param operation: function without arguments. It is cancelled by OperationCancelledError,
            which is raised by the monitor.
        :param errorMessage: shown in a popup with the details of the error if the operation fails.
        :param cancelledMessage: added to the log if the user cancels the operation.
        :param clearLog: if False then the log of the previous operation is kept until the
            operation logs a message, so it is kept if the operation has nothing to do.
        :param displayDelay: the progress bar and the Cancel button are shown only if the
            operation takes longer than this (seconds).
        :return: True if the user cancelled the operation.
        """
        if clearLog:
            self.clearLog()
        self._clearLogBeforeNextMessage = not clearLog
        self.progressBar.value = 0
        self.cancelButton.text = _("Cancel")
        self.cancelButton.enabled = True
        startTime = time.time()
        if displayDelay <= 0.0:
            self._showProgress()

        def onProgress(progress) -> None:
            if not self.cancelButton.visible and time.time() - startTime >= displayDelay:
                self._showProgress()
            if progress is not None:
                self.progressBar.value = int(progress * self.progressBar.maximum)
            slicer.app.processEvents()

        wasCancelled = False
        self._operationInProgress = True
        self.monitor.progressCallback = onProgress
        try:
            with slicer.util.tryWithErrorDisplay(errorMessage):
                # The log can be scrolled during the operation. The error popup is shown after
                # the user input is enabled again.
                userInputBlocker = UserInputBlocker([self.cancelButton, self.logTextEdit])
                slicer.app.installEventFilter(userInputBlocker)
                try:
                    operation()
                except OperationCancelledError:
                    wasCancelled = True
                    self.addLog(cancelledMessage)
                finally:
                    slicer.app.removeEventFilter(userInputBlocker)
        finally:
            self.monitor.progressCallback = None
            self._operationInProgress = False
            self._clearLogBeforeNextMessage = False
            self._setProgressVisible(False)
        return wasCancelled

    def cancel(self) -> None:
        """Ask the running operation to stop. This is what the Cancel button does."""
        self.monitor.cancel()
        # The operation may not stop immediately.
        self.cancelButton.enabled = False
        self.cancelButton.text = _("Cancelling...")

    def clearLog(self) -> None:
        self.logTextEdit.plainText = ""
        slicer.app.processEvents()

    def addLog(self, text) -> None:
        if self._clearLogBeforeNextMessage:
            self._clearLogBeforeNextMessage = False
            self.logTextEdit.plainText = ""
        # Keep showing the latest message, unless the user has scrolled up to read earlier ones.
        scrollBar = self.logTextEdit.verticalScrollBar()
        wasAtEnd = scrollBar.value >= scrollBar.maximum
        self.logTextEdit.appendPlainText(text)
        if wasAtEnd:
            scrollBar.value = scrollBar.maximum
        if self._operationInProgress:
            # The progress bar shows the progress of the step that the latest message is about.
            self.progressBar.value = 0
        slicer.app.processEvents()


class UserInputBlocker(qt.QObject):
    """Discards the user input of the application, except what is sent to the given widgets.

    It is installed on the application while an operation processes the events of the application,
    so that the user can only use the widgets that are safe to use during the operation.
    """

    BLOCKED_EVENT_TYPES = (
        qt.QEvent.MouseButtonPress, qt.QEvent.MouseButtonRelease, qt.QEvent.MouseButtonDblClick,
        qt.QEvent.Wheel, qt.QEvent.KeyPress, qt.QEvent.KeyRelease,
        qt.QEvent.Shortcut, qt.QEvent.ShortcutOverride, qt.QEvent.ContextMenu,
        qt.QEvent.DragEnter, qt.QEvent.DragMove, qt.QEvent.Drop, qt.QEvent.Close)

    def __init__(self, allowedWidgets):
        qt.QObject.__init__(self)
        self.allowedWidgets = allowedWidgets

    def eventFilter(self, obj, event):
        eventType = event.type()
        if eventType not in self.BLOCKED_EVENT_TYPES:
            return False
        if eventType != qt.QEvent.Shortcut:
            if not obj.isWidgetType():
                # A window, it passes on the event to one of its widgets.
                return False
            if any(widget == obj or widget.isAncestorOf(obj) for widget in self.allowedWidgets):
                return False
        # Not accepted, so that for example a window is not closed.
        event.ignore()
        return True


class FileDropEventFilter(qt.QObject):
    """Accepts files with the given extensions dropped on a widget.

    Qt virtual methods (such as dropEvent) cannot be overridden in Python in Slicer, therefore
    drag and drop support is added to an existing widget with this event filter.
    """

    def __init__(self, extensions, onFilesDropped):
        qt.QObject.__init__(self)
        self.extensions = [extension.lower() for extension in extensions]
        self.onFilesDropped = onFilesDropped

    def eventFilter(self, obj, event):
        eventType = event.type()
        if eventType in (qt.QEvent.DragEnter, qt.QEvent.DragMove):
            if not self._filePaths(event):
                return False
            event.acceptProposedAction()
            return True
        if eventType == qt.QEvent.Drop:
            filePaths = self._filePaths(event)
            if not filePaths:
                return False
            event.acceptProposedAction()
            self.onFilesDropped(filePaths)
            return True
        return False

    def _filePaths(self, event):
        mimeData = event.mimeData()
        if not mimeData.hasUrls():
            return []
        filePaths = []
        for url in mimeData.urls():
            filePath = url.toLocalFile()
            if filePath and os.path.splitext(filePath)[1].lower() in self.extensions:
                filePaths.append(filePath)
        return filePaths
