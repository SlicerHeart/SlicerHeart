"""Table widget content that lists the arrays of meshes and how they are converted."""

import qt
from slicer.i18n import tr as _

from ImportExportSimulationModelLib.Units import SIMULATION_UNITS, simulationUnitByQuantity
from ImportExportSimulationModelLib.MeshArrays import (
    coordinateSystemConversionDescription, formatScale, LOCATION_LABELS,
)


class ArrayInfoTable:
    """Lists the point coordinates and the data arrays of meshes in a table widget, with the unit of
    each array and the factor that its values are multiplied by when they are converted.

    The unit is shown in the unit system of the file. If the units are editable then this is the
    unit system that the values are converted from (import): the unit of each array is only guessed
    from the name of the array, so the user can choose another one. Otherwise it is the unit system
    that the values are converted to (export).
    """

    NAME_COLUMN = 0
    LOCATION_COLUMN = 1
    COMPONENTS_COLUMN = 2
    RANGE_COLUMN = 3
    UNIT_COLUMN = 4
    SCALE_COLUMN = 5

    def __init__(self, tableWidget, scaleColumnLabel, unitsEditable=False) -> None:
        self.tableWidget = tableWidget
        self.unitsEditable = unitsEditable
        # List of MeshArrayInfo, one for each row. The unit that the user chooses is stored in them.
        self.arrayInfos = []
        # Unit system that the values of each array are converted from
        self._fromUnitSystems = []
        self._toUnitSystem = None
        self._flipFirstTwoComponents = False

        tableWidget.columnCount = 6
        tableWidget.setHorizontalHeaderLabels([
            _("Name"), _("Location"), _("Components"), _("Range"), _("Unit"), scaleColumnLabel])
        tableWidget.verticalHeader().visible = False
        tableWidget.horizontalHeader().setSectionResizeMode(qt.QHeaderView.ResizeToContents)
        tableWidget.horizontalHeader().setSectionResizeMode(self.RANGE_COLUMN, qt.QHeaderView.Stretch)
        tableWidget.editTriggers = qt.QAbstractItemView.NoEditTriggers

    def setArrayInfos(self, arrayInfos, fromUnitSystems, toUnitSystem, flipFirstTwoComponents) -> None:
        """Show arrays, and how they are changed by a conversion.

        :param arrayInfos: list of MeshArrayInfo.
        :param fromUnitSystems: unit system that the values are converted from. It can be a list,
            if it is not the same for all the arrays.
        :param toUnitSystem: unit system that the values are converted to.
        :param flipFirstTwoComponents: True if the coordinate system is changed by the conversion.
        """
        self.arrayInfos = list(arrayInfos)
        self.setConversion(fromUnitSystems, toUnitSystem, flipFirstTwoComponents)

    def setConversion(self, fromUnitSystems, toUnitSystem, flipFirstTwoComponents) -> None:
        """Show how the arrays that are in the table are changed by another conversion."""
        if isinstance(fromUnitSystems, str):
            fromUnitSystems = [fromUnitSystems] * len(self.arrayInfos)
        self._fromUnitSystems = list(fromUnitSystems)
        self._toUnitSystem = toUnitSystem
        self._flipFirstTwoComponents = flipFirstTwoComponents

        self.tableWidget.clearContents()
        self.tableWidget.rowCount = len(self.arrayInfos)
        for row in range(len(self.arrayInfos)):
            self._fillRow(row)

    def _fillRow(self, row) -> None:
        arrayInfo = self.arrayInfos[row]
        fromUnitSystem = self._fromUnitSystems[row]

        nameItem = qt.QTableWidgetItem(arrayInfo.name)
        # If the coordinate system changes then the tooltip tells how the array is transformed.
        nameTooltip = arrayInfo.name
        if self._flipFirstTwoComponents:
            nameTooltip += "\n" + coordinateSystemConversionDescription(
                arrayInfo.name, arrayInfo.numberOfComponents, arrayInfo.isFloatingPoint)
        nameItem.setToolTip(nameTooltip)
        self.tableWidget.setItem(row, self.NAME_COLUMN, nameItem)

        self.tableWidget.setItem(row, self.LOCATION_COLUMN,
                                 qt.QTableWidgetItem(LOCATION_LABELS[arrayInfo.location]))
        self.tableWidget.setItem(row, self.COMPONENTS_COLUMN,
                                 qt.QTableWidgetItem(str(arrayInfo.numberOfComponents)))

        rangeItem = qt.QTableWidgetItem(arrayInfo.rangeString())
        rangeTooltip = arrayInfo.rangeString(maximumComponents=arrayInfo.numberOfComponents)
        if arrayInfo.isRangeApproximate:
            rangeTooltip += "\n" + _("Approximate: computed from a sample of the file, the true range can be "
                                     "much wider. Disable 'Approximate scalar ranges' in the Advanced section "
                                     "to compute the exact range.")
        rangeItem.setToolTip(rangeTooltip)
        self.tableWidget.setItem(row, self.RANGE_COLUMN, rangeItem)

        if self.unitsEditable:
            unitComboBox = qt.QComboBox()
            for index, simulationUnit in enumerate(SIMULATION_UNITS):
                unitComboBox.addItem(simulationUnit.unitLabel(fromUnitSystem), simulationUnit.quantity)
                unitComboBox.setItemData(index, simulationUnit.description, qt.Qt.ToolTipRole)
            unitComboBox.currentIndex = unitComboBox.findData(arrayInfo.simulationUnit.quantity)
            unitComboBox.connect("currentIndexChanged(int)", lambda index, row=row: self._onUnitChanged(row))
            self.tableWidget.setCellWidget(row, self.UNIT_COLUMN, unitComboBox)
        else:
            unitItem = qt.QTableWidgetItem(arrayInfo.simulationUnit.unitLabel(self._toUnitSystem))
            unitItem.setToolTip(_("Stored in the model as: {unit}").format(
                unit=arrayInfo.simulationUnit.unitLabel(fromUnitSystem)))
            self.tableWidget.setItem(row, self.UNIT_COLUMN, unitItem)

        self._fillScaleCell(row)

    def _fillScaleCell(self, row) -> None:
        arrayInfo = self.arrayInfos[row]
        fromUnitSystem = self._fromUnitSystems[row]
        scaleItem = qt.QTableWidgetItem(formatScale(arrayInfo.scale(fromUnitSystem, self._toUnitSystem)))
        scaleItem.setToolTip(_("Values are multiplied by this factor to convert them from {fromUnit} to "
                               "{toUnit} (length exponent: {lengthExponent}).").format(
            fromUnit=arrayInfo.simulationUnit.unitLabel(fromUnitSystem),
            toUnit=arrayInfo.simulationUnit.unitLabel(self._toUnitSystem),
            lengthExponent=arrayInfo.simulationUnit.lengthExponent))
        self.tableWidget.setItem(row, self.SCALE_COLUMN, scaleItem)

    def _onUnitChanged(self, row) -> None:
        unitComboBox = self.tableWidget.cellWidget(row, self.UNIT_COLUMN)
        if unitComboBox is None:
            return
        self.arrayInfos[row].simulationUnit = simulationUnitByQuantity(unitComboBox.currentData)
        self._fillScaleCell(row)
