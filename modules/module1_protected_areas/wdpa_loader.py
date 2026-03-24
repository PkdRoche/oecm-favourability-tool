"""WDPA data acquisition and loading functionality."""


def load_wdpa_data(country_iso3, api_token=None, local_path=None):
    """
    Load WDPA protected areas data for a given territory.

    Args:
        country_iso3: ISO3 country code
        api_token: WDPA API authentication token
        local_path: Path to local WDPA file if API unavailable

    Returns:
        GeoDataFrame of protected areas
    """
    raise NotImplementedError("WDPA loader not yet implemented")


def classify_protected_areas(wdpa_gdf, classification_config):
    """
    Classify WDPA features according to IUCN classification scheme.

    Args:
        wdpa_gdf: GeoDataFrame of WDPA features
        classification_config: Dictionary from iucn_classification.yaml

    Returns:
        GeoDataFrame with added 'protection_class' column
    """
    raise NotImplementedError("IUCN classification not yet implemented")
