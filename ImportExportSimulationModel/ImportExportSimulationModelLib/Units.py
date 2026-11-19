"""Unit systems and the physical quantities of simulation data arrays."""

import re

from slicer.i18n import tr as _


#
# Unit systems
#

# Unit systems that meshes can be read from and written to. Mass (g) and time (s) units are the
# same in all supported systems, only the length unit differs, therefore a single number - the
# length of one length unit expressed in mm - fully defines the conversion between two systems
# (see unitSystemConversionFactor).
UNIT_SYSTEMS = {
    "cgs": {"name": "CGS (cm-g-s)", "lengthUnitInMm": 10.0},
    "mmgs": {"name": "mm-g-s", "lengthUnitInMm": 1.0},
}

# Unit system that models are stored in in the scene. Slicer works in mm, therefore imported
# meshes are always converted to this system.
SCENE_UNIT_SYSTEM = "mmgs"

# Coordinate system that models are stored in in the scene.
SCENE_COORDINATE_SYSTEM = "RAS"

COORDINATE_SYSTEMS = ["RAS", "LPS"]


class SimulationUnit:
    """Unit of a mesh coordinate set or data array, in each supported unit system.

    `lengthExponent` is the power of the length unit in the quantity: 0 if the quantity is not
    spatial (e.g., 1/s), 1 if length appears in the numerator (e.g., cm/s), -1 if length appears
    in the denominator (e.g., g/(cm*s)), -2 if length^2 appears in the denominator, etc.
    Because the mass and time units are the same in all supported systems, this exponent is all
    that is needed to convert a value between the systems.
    """

    def __init__(self, quantity, lengthExponent, units, description=""):
        self.quantity = quantity
        self.lengthExponent = lengthExponent
        # unit system name -> unit string. An unrecognized unit (read from a model that was not
        # created by this module) is represented by a single entry that is used in every system.
        self.units = units
        self.description = description

    def unit(self, unitSystem):
        """Unit string in the given unit system, e.g., 'cm/s'. Empty string for dimensionless."""
        if unitSystem in self.units:
            return self.units[unitSystem]
        # Unrecognized unit: it is not known how to express it in other unit systems.
        return next(iter(self.units.values()))

    def unitLabel(self, unitSystem):
        """Unit string for display, where dimensionless quantities are explicitly labeled."""
        return self.unit(unitSystem) or _("(none)")


# Quantities that a mesh coordinate set or data array may represent. Only one entry is needed for
# quantities that share the same unit (e.g., pressure, traction, wall shear stress, and stress),
# because the unit and the length exponent are all that the conversion depends on.
SIMULATION_UNITS = [
    SimulationUnit("dimensionless", 0, {"cgs": "", "mmgs": ""},
                   _("Dimensionless quantity or identifier (not scaled)")),
    SimulationUnit("length", 1, {"cgs": "cm", "mmgs": "mm"},
                   _("Length: coordinate, displacement, thickness, distance, radius")),
    SimulationUnit("velocity", 1, {"cgs": "cm/s", "mmgs": "mm/s"},
                   _("Velocity, speed")),
    SimulationUnit("acceleration", 1, {"cgs": "cm/s2", "mmgs": "mm/s2"},
                   _("Acceleration")),
    SimulationUnit("area", 2, {"cgs": "cm2", "mmgs": "mm2"},
                   _("Area")),
    SimulationUnit("volume", 3, {"cgs": "cm3", "mmgs": "mm3"},
                   _("Volume")),
    SimulationUnit("flowRate", 3, {"cgs": "cm3/s", "mmgs": "mm3/s"},
                   _("Flow rate")),
    SimulationUnit("pressure", -1, {"cgs": "dyn/cm2", "mmgs": "g/(mm*s2)"},
                   _("Pressure, traction, wall shear stress, stress, elastic modulus")),
    SimulationUnit("density", -3, {"cgs": "g/cm3", "mmgs": "g/mm3"},
                   _("Mass density")),
    SimulationUnit("dynamicViscosity", -1, {"cgs": "g/(cm*s)", "mmgs": "g/(mm*s)"},
                   _("Dynamic viscosity")),
    SimulationUnit("kinematicViscosity", 2, {"cgs": "cm2/s", "mmgs": "mm2/s"},
                   _("Kinematic viscosity, diffusion coefficient")),
    SimulationUnit("force", 1, {"cgs": "dyn", "mmgs": "g*mm/s2"},
                   _("Force")),
    SimulationUnit("resistance", -4, {"cgs": "dyn*s/cm5", "mmgs": "g/(mm4*s)"},
                   _("Flow resistance")),
    SimulationUnit("compliance", 4, {"cgs": "cm5/dyn", "mmgs": "mm4*s2/g"},
                   _("Compliance, capacitance")),
    SimulationUnit("mass", 0, {"cgs": "g", "mmgs": "g"},
                   _("Mass")),
    SimulationUnit("time", 0, {"cgs": "s", "mmgs": "s"},
                   _("Time")),
    SimulationUnit("frequency", 0, {"cgs": "1/s", "mmgs": "1/s"},
                   _("Rate: frequency, vorticity, strain rate, divergence")),
]

DIMENSIONLESS_QUANTITY = "dimensionless"
LENGTH_QUANTITY = "length"

# Quantity guessed for an array based on its name. Each rule lists the words that identify a
# quantity; a rule matches if one of its words occurs as a whole word anywhere in the array
# name, which ignores any prefix and any suffix ('Stress_xx' and 'mean_stress' are both a
# stress) and avoids matching a word that only happens to be a part of another one ('ratio'
# inside 'acceleration', for example). A rule word that contains an underscore matches a
# sequence of words, e.g. 'wall_shear_stress' matches 'WallShearStress' and 'wall_shear_stress'.
# The first matching rule wins, so more specific rules must come first.
ARRAY_NAME_QUANTITY_RULES = [
    (r"(ids?|region|domain|zone|label|marker|flag|mask|partition|proc)", DIMENSIONLESS_QUANTITY),
    (r"(strain|jacobian|fraction|ratio|index|criterion|coefficient|number)", DIMENSIONLESS_QUANTITY),
    (r"(wss|wall_shear|wall_shear_stress)", "pressure"),
    (r"(traction)", "pressure"),
    (r"(stress|pressure|pres|modulus|elastance|stiffness)", "pressure"),
    (r"(velocity|veloc|vel|speed)", "velocity"),
    (r"(acceleration|accel)", "acceleration"),
    (r"(displacement|disp|coordinate|coordinates|position|centroid|thickness|radius|diameter"
     r"|distance|length|perimeter|circumference)", LENGTH_QUANTITY),
    (r"(density|rho)", "density"),
    (r"(kinematic_viscosity|diffusivity|diffusion)", "kinematicViscosity"),
    (r"(viscosity|mu)", "dynamicViscosity"),
    (r"(flow|flow_rate|flowrate|discharge|q)", "flowRate"),
    (r"(resistance)", "resistance"),
    (r"(compliance|capacitance)", "compliance"),
    (r"(force|reaction)", "force"),
    (r"(volume)", "volume"),
    (r"(area)", "area"),
    (r"(vorticity|divergence|rate|strain_rate|frequency)", "frequency"),
    (r"(time|times|timestep|dt|period|duration)", "time"),
    (r"(mass)", "mass"),
]


def normalizedArrayName(name):
    """Array name with the words separated by single underscores, in lower case.

    'GlobalNodeID' -> 'global_node_id', 'vWSS' -> 'v_wss', 'Q-Criterion' -> 'q_criterion'.
    This makes it possible to match whole words in the array names, whatever naming convention
    the simulation software uses.
    """
    # Split camel case names ('NodeID' -> 'Node_ID', 'WSSValue' -> 'WSS_Value').
    normalized = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name)
    normalized = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", "_", normalized)
    # Any other separator (space, hyphen, dot, ...) becomes an underscore.
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", normalized)
    return normalized.strip("_").lower()


def simulationUnitByQuantity(quantity):
    """Return the SimulationUnit with the given quantity name, or the dimensionless unit."""
    for simulationUnit in SIMULATION_UNITS:
        if simulationUnit.quantity == quantity:
            return simulationUnit
    return SIMULATION_UNITS[0]


def simulationUnitByUnitString(unitString):
    """Return the SimulationUnit that uses the given unit string in any unit system, or None."""
    if not unitString:
        return SIMULATION_UNITS[0]
    for simulationUnit in SIMULATION_UNITS:
        if unitString in simulationUnit.units.values():
            return simulationUnit
    return None


def guessSimulationUnit(arrayName, isFloatingPoint=True):
    """Guess the quantity that an array contains, from its name.

    Prefixes and suffixes are ignored: the name is split into words (see normalizedArrayName)
    and a rule matches if its word - or sequence of words - occurs anywhere in the name. So the
    quantity is recognized wherever it is in the name, whatever the simulation software puts
    before or after it:

      Stress, Stress_xx, Stress_yz, solid_Stress_1  -> pressure
      Strain_xz, PrincipalStrain_1, VonMisesStrain  -> dimensionless (strain)
      average_pressure, vinplane_traction           -> pressure

    Integer arrays are always considered dimensionless: they store identifiers, labels, or
    counts, which must not be scaled.
    """
    if not isFloatingPoint:
        return SIMULATION_UNITS[0]
    normalized = normalizedArrayName(arrayName)
    for pattern, quantity in ARRAY_NAME_QUANTITY_RULES:
        # A rule matches only whole words, so a prefix or a suffix that merely contains the
        # letters of a rule word does not match it.
        if re.search(r"(^|_)" + pattern + r"($|_)", normalized):
            return simulationUnitByQuantity(quantity)
    return SIMULATION_UNITS[0]


def unitSystemConversionFactor(lengthExponent, fromUnitSystem, toUnitSystem):
    """Factor that a value with the given length exponent must be multiplied by to convert it
    from one unit system to another.

    For example, converting a velocity (length exponent 1) from CGS to mm-g-s gives 10
    (1 cm/s = 10 mm/s), converting a pressure (length exponent -1) gives 0.1
    (1 dyn/cm2 = 1 g/(cm*s2) = 0.1 g/(mm*s2)).
    """
    if lengthExponent == 0 or fromUnitSystem == toUnitSystem:
        return 1.0
    fromLengthInMm = UNIT_SYSTEMS[fromUnitSystem]["lengthUnitInMm"]
    toLengthInMm = UNIT_SYSTEMS[toUnitSystem]["lengthUnitInMm"]
    return float(fromLengthInMm / toLengthInMm) ** lengthExponent


def quantityWithLengthExponent(lengthExponent):
    """Name of a quantity that has the given length exponent, dimensionless if there is none.

    It can be used for converting the values of an array that has a unit that is not known.
    """
    for simulationUnit in SIMULATION_UNITS:
        if simulationUnit.lengthExponent == lengthExponent:
            return simulationUnit.quantity
    return DIMENSIONLESS_QUANTITY
