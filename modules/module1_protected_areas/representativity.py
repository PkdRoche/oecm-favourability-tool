"""Ecosystem representativity assessment (KMGBF Target 3)."""


def compute_representativity(protected_areas_gdf, ecosystem_map, target_threshold=0.30):
    """
    Compute ecosystem representativity within protected area network.

    Args:
        protected_areas_gdf: GeoDataFrame of protected areas
        ecosystem_map: Raster or vector layer of ecosystem types
        target_threshold: Target protection percentage (default 0.30 = 30%)

    Returns:
        Dictionary mapping ecosystem type to protection percentage
    """
    raise NotImplementedError("Representativity analysis not yet implemented")


def identify_underrepresented_ecosystems(representativity_dict, target_threshold=0.30):
    """
    Identify ecosystem types below representativity target.

    Args:
        representativity_dict: Output from compute_representativity
        target_threshold: Target protection percentage

    Returns:
        List of ecosystem types with gap magnitude
    """
    raise NotImplementedError("Underrepresented ecosystem identification not yet implemented")
