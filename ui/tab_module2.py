"""Streamlit UI for Module 2 — OECM Favourability Analysis."""
import streamlit as st


def render_module2_tab():
    """
    Render Module 2 interface with criteria upload, MCE execution, and results display.
    """
    raise NotImplementedError("Module 2 tab not yet implemented")


def display_favourability_map(favourability_array):
    """
    Display interactive map of favourability index.

    Args:
        favourability_array: xarray DataArray with favourability scores
    """
    raise NotImplementedError("Favourability map display not yet implemented")


def display_sensitivity_analysis(criteria_dict, weights_config):
    """
    Display sensitivity analysis showing impact of weight variations.

    Args:
        criteria_dict: Input criterion layers
        weights_config: Current MCE weights
    """
    raise NotImplementedError("Sensitivity analysis display not yet implemented")
