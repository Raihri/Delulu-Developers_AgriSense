from enum import StrEnum


class SoilClass(StrEnum):
    SANDY_LOAM = "sandy_loam"
    LOAM = "loam"
    CLAY = "clay"


class DrainageCondition(StrEnum):
    WELL_DRAINED = "well_drained"
    WATERLOGGED = "waterlogged"


class WaterAvailability(StrEnum):
    IRRIGATION_AVAILABLE = "irrigation_available"
    SURFACE_WATER_AVAILABLE = "surface_water_available"
    RAINFED = "rainfed"
    LIMITED = "limited"


class TargetSeason(StrEnum):
    BORO = "boro"
    RABI = "rabi"
    KHARIF_1 = "kharif_1"
    KHARIF_2 = "kharif_2"
