import qt


LEAFLET_ORDER = {
  "mitral": ['anterior', 'posterior'],
  "tricuspid": ['anterior', 'posterior', 'septal'],
  "cavc": ['superior', 'right', 'inferior', 'left']
}


VALVE_COMMISSURAL_LANDMARKS = {
  "mitral": ['PMC', 'ALC'],
  "tricuspid": ['ASC', 'PSC', 'APC'],
  "cavc": ['SRC', 'SLC', 'IRC', 'ILC'],
  "lavv": ['ALC', 'PMC', 'SIC']
}


VALVE_QUADRANT_LANDMARKS = {
  "mitral": ['A', 'P', 'PM', 'AL'],
  "tricuspid": ['A', 'P', 'S', 'L'],
  "cavc": ['R', 'L', 'MA', 'MP'],
  "lavv": []
}


class STATE:

  PENDING = 'Pending'
  NOT_RUNNING = 'NotRunning'
  STARTING = 'Starting'
  RUNNING = 'Running'
  COMPLETED = 'Completed'


ProcessError = {
  qt.QProcess.FailedToStart: "FailedToStart",
  qt.QProcess.Crashed: "Crashed",
  qt.QProcess.Timedout: "Timedout",
  qt.QProcess.ReadError: "ReadError",
  qt.QProcess.WriteError: "WriteError",
  qt.QProcess.UnknownError: "UnknownError"
}
ProcessState = {
  qt.QProcess.NotRunning: STATE.NOT_RUNNING,
  qt.QProcess.Starting: STATE.STARTING,
  qt.QProcess.Running: STATE.RUNNING
}