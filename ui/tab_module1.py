"""Streamlit UI for Module 1 — Protection Network Diagnostic."""
import streamlit as st


def render_module1_tab():
    """
    Render Module 1 interface with WDPA loading, coverage stats, and gap analysis.
    """
    raise NotImplementedError("Module 1 tab not yet implemented")


def display_coverage_map(protected_areas_gdf):
    """
    Display interactive Folium map of classified protected areas.

    Args:
        protected_areas_gdf: GeoDataFrame with protection classes
    """
    raise NotImplementedError("Coverage map display not yet implemented")


def display_representativity_chart(representativity_dict):
    """
    Display bar chart of ecosystem representativity vs. target.

    Args:
        representativity_dict: Ecosystem type → protection percentage
    """
    raise NotImplementedError("Representativity chart not yet implemented")
