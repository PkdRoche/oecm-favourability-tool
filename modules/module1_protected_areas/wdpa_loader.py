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

    Uses the IUCN_MAX column (most protective IUCN category per feature)
    as the primary classification key, with DESIG as fallback for keyword
    matching when IUCN_MAX is unassigned.

    Args:
        wdpa_gdf: GeoDataFrame of WDPA features
        classification_config: Dictionary from iucn_classification.yaml

    Returns:
        GeoDataFrame with added 'protection_class' column
    """
    import pandas as pd

    classes = classification_config["classes"]

    # Build lookup: iucn_value → class_key
    iucn_lookup = {}
    for class_key, class_cfg in classes.items():
        for cat in class_cfg.get("iucn_cats", []):
            iucn_lookup[cat] = class_key

    # Build list of (class_key, keywords) for DESIG fallback
    desig_rules = [
        (class_key, class_cfg.get("desig_keywords", []))
        for class_key, class_cfg in classes.items()
        if class_cfg.get("desig_keywords")
    ]

    unassigned_cats = set(classes.get("unassigned", {}).get("iucn_cats", []))

    def _classify_row(row):
        # WD-OECM source → dedicated class
        if str(row.get("PARENT_ISO3", "")).upper() == "WD-OECM" or \
                str(row.get("SOURCE", "")).upper() == "WD-OECM":
            return "oecm"

        iucn_val = str(row.get("IUCN_MAX", "")).strip()

        # Direct IUCN_MAX match
        if iucn_val and iucn_val not in unassigned_cats:
            if iucn_val in iucn_lookup:
                return iucn_lookup[iucn_val]

        # DESIG keyword fallback
        desig_val = str(row.get("DESIG", "")).strip()
        if desig_val:
            for class_key, keywords in desig_rules:
                if any(kw.lower() in desig_val.lower() for kw in keywords):
                    return class_key

        return "unassigned"

    wdpa_gdf = wdpa_gdf.copy()
    wdpa_gdf["protection_class"] = wdpa_gdf.apply(_classify_row, axis=1)
    return wdpa_gdf
