"""Streamlit sidebar components for parameter configuration."""
import streamlit as st
import yaml
from pathlib import Path
from shapely.geometry import box
from modules.utils.nuts2_loader import (
    load_nuts2,
    get_countries,
    get_nuts2_for_country,
    get_nuts2_geometry
)


def load_config_defaults():
    """
    Load default parameter values from config/criteria_defaults.yaml.

    Returns
    -------
    dict
        Configuration dictionary with inter-group weights, intra-group weights,
        aggregation settings, and thresholds.
    """
    config_path = Path(__file__).parent.parent / "config" / "criteria_defaults.yaml"

    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        return config
    except FileNotFoundError:
        st.error(f"Configuration file not found: {config_path}")
        return {}


def load_settings():
    """
    Load general settings from config/settings.yaml.

    Returns
    -------
    dict
        Settings dictionary with CRS, resolution, paths, etc.
    """
    settings_path = Path(__file__).parent.parent / "config" / "settings.yaml"

    try:
        with open(settings_path, 'r', encoding='utf-8') as f:
            settings = yaml.safe_load(f)
        return settings
    except FileNotFoundError:
        st.warning(f"Settings file not found: {settings_path}")
        return {}


def render_sidebar():
    """
    Render sidebar with global parameters and file upload controls.

    Returns
    -------
    dict
        Dictionary of user-configured parameters including:
        - study_area_nuts_id: NUTS2 region ID or 'CUSTOM' (str)
        - study_area_name: Region name or custom bbox description (str)
        - study_area_geometry: Shapely geometry in EPSG:3035 (BaseGeometry)
        - threshold_pressure: eliminatory pressure threshold (float)
        - method: aggregation method ('geometric' or 'owa')
        - alpha: OWA orness parameter (float)
        - W_A, W_B, W_C: inter-group weights (float)
        - w_condition, w_regulating_es, w_pressure: Group A intra-weights (float)
        - w_cultural_es: Group B weight (float, always 1.0)
        - w_provisioning_es, w_landuse_compatible: Group C intra-weights (float)
        - gap_bonus: optional gap analysis bonus (float)
    """
    # Load defaults
    config = load_config_defaults()
    settings = load_settings()

    st.sidebar.title("OECM Favourability Tool")
    st.sidebar.markdown("---")

    # ===================================================================
    # Section 1: Study area (NUTS2 selector)
    # ===================================================================
    st.sidebar.header("1. Study Area")

    # Initialize study area variables
    study_area_nuts_id = None
    study_area_name = None
    study_area_geometry = None
    selected_country = None

    # Try to load NUTS2 boundaries
    nuts2_load_failed = False
    nuts2_gdf = None

    try:
        nuts2_gdf = load_nuts2(year=2021, scale="20M")
    except Exception as e:
        nuts2_load_failed = True
        st.sidebar.warning(
            f"Could not load NUTS2 boundaries from Eurostat: {e}\n\n"
            "Falling back to manual bounding box input."
        )

    if not nuts2_load_failed and nuts2_gdf is not None:
        # Two-step selector: Country → NUTS2 Region
        countries = get_countries(nuts2_gdf)

        # Default to France if available
        default_country_idx = countries.index("FR") if "FR" in countries else 0

        selected_country = st.sidebar.selectbox(
            "Country",
            options=countries,
            index=default_country_idx,
            help="Select country (2-letter ISO code)"
        )

        # Filter NUTS2 regions for selected country
        nuts2_regions = get_nuts2_for_country(nuts2_gdf, selected_country)

        # Create display options: "Region Name (NUTS_ID)"
        region_options = [
            f"{row.NUTS_NAME} ({row.NUTS_ID})"
            for _, row in nuts2_regions.iterrows()
        ]

        # Extract NUTS_IDs for lookup
        region_nuts_ids = nuts2_regions['NUTS_ID'].tolist()

        if len(region_options) > 0:
            selected_region_idx = st.sidebar.selectbox(
                "NUTS2 Region",
                options=range(len(region_options)),
                format_func=lambda i: region_options[i],
                help="Select NUTS2 administrative region"
            )

            # Retrieve selected NUTS_ID and geometry
            study_area_nuts_id = region_nuts_ids[selected_region_idx]
            study_area_name = nuts2_regions.iloc[selected_region_idx]['NUTS_NAME']
            study_area_geometry = get_nuts2_geometry(nuts2_gdf, study_area_nuts_id)

            # Display region details
            if study_area_geometry is not None:
                area_km2 = study_area_geometry.area / 1_000_000  # EPSG:3035 is in meters
                st.sidebar.caption(
                    f"**{study_area_nuts_id}** — {area_km2:,.0f} km²"
                )
        else:
            st.sidebar.error(f"No NUTS2 regions found for country {selected_country}")

    else:
        # Fallback: manual bounding box input
        st.sidebar.info("Enter bounding box coordinates in EPSG:3035 (meters)")

        col1, col2 = st.sidebar.columns(2)
        with col1:
            xmin = st.number_input("X min", value=2500000.0, step=1000.0)
            ymin = st.number_input("Y min", value=1500000.0, step=1000.0)
        with col2:
            xmax = st.number_input("X max", value=3500000.0, step=1000.0)
            ymax = st.number_input("Y max", value=2500000.0, step=1000.0)

        # Create bounding box geometry
        study_area_geometry = box(xmin, ymin, xmax, ymax)
        study_area_name = f"Custom bbox ({xmin:.0f}, {ymin:.0f}, {xmax:.0f}, {ymax:.0f})"
        study_area_nuts_id = "CUSTOM"

        area_km2 = study_area_geometry.area / 1_000_000
        st.sidebar.caption(f"Area: {area_km2:,.0f} km²")

    # Display settings
    if settings:
        resolution_m = settings.get('resolution_m', 100)
        crs = settings.get('crs', 'EPSG:3035')
        st.sidebar.info(f"Target resolution: {resolution_m} m\nCRS: {crs}")

    st.sidebar.markdown("---")

    # ===================================================================
    # Section 2: Group D eliminatory thresholds
    # ===================================================================
    st.sidebar.header("2. Eliminatory Thresholds (Group D)")

    default_pressure = config.get('eliminatory', {}).get('max_anthropogenic_pressure', 150.0)

    threshold_pressure = st.sidebar.slider(
        "Max anthropogenic pressure (hab/km²)",
        min_value=0.0,
        max_value=500.0,
        value=default_pressure,
        step=10.0,
        help="Pixels above this threshold are excluded from OECM analysis"
    )

    st.sidebar.info(
        "Incompatible land use classes (urban, industrial) are defined in "
        "config/land_use_compatibility.yaml"
    )

    st.sidebar.markdown("---")

    # ===================================================================
    # Section 3: Aggregation method
    # ===================================================================
    st.sidebar.header("3. Aggregation Method")

    default_method = config.get('aggregation', {}).get('default_method', 'geometric')
    method_display = st.sidebar.selectbox(
        "MCE aggregation method",
        options=["Weighted geometric mean", "Yager OWA"],
        index=0 if default_method == 'geometric' else 1,
        help="Weighted geometric mean: strictly non-compensatory. "
             "Yager OWA: adjustable compensation via alpha parameter."
    )

    method = 'geometric' if method_display == "Weighted geometric mean" else 'owa'

    # Alpha slider (only visible for OWA)
    default_alpha = config.get('aggregation', {}).get('default_alpha', 0.25)
    alpha = default_alpha

    if method == 'owa':
        alpha = st.sidebar.slider(
            "OWA orness parameter (α)",
            min_value=0.0,
            max_value=1.0,
            value=default_alpha,
            step=0.05,
            help=(
                "α = 0.0: AND logic (all criteria required)\n"
                "α = 0.5: Balanced compensation\n"
                "α = 1.0: OR logic (one criterion sufficient)"
            )
        )

        # Display interpretation label
        if alpha <= 0.15:
            alpha_label = "Strict AND — all criteria required"
        elif alpha <= 0.4:
            alpha_label = "Near AND — strong non-compensation"
        elif alpha <= 0.6:
            alpha_label = "Balanced"
        elif alpha <= 0.85:
            alpha_label = "Near OR — high compensation"
        else:
            alpha_label = "Permissive OR — one criterion sufficient"

        st.sidebar.caption(f"Current setting: {alpha_label}")

    st.sidebar.markdown("---")

    # ===================================================================
    # Section 4: Inter-group weights (W_A, W_B, W_C)
    # ===================================================================
    st.sidebar.header("4. Inter-Group Weights")
    st.sidebar.caption("Relative importance of each functional group")

    defaults_inter = config.get('inter_group_weights', {})

    W_A = st.sidebar.slider(
        "W_A — Ecological integrity",
        min_value=0.0,
        max_value=1.0,
        value=defaults_inter.get('W_A', 0.50),
        step=0.05,
        help="Group A: ecosystem condition, regulating ES, low pressure"
    )

    W_B = st.sidebar.slider(
        "W_B — Co-benefits / social compatibility",
        min_value=0.0,
        max_value=1.0,
        value=defaults_inter.get('W_B', 0.15),
        step=0.05,
        help="Group B: cultural ecosystem services"
    )

    W_C = st.sidebar.slider(
        "W_C — Production / use function",
        min_value=0.0,
        max_value=1.0,
        value=defaults_inter.get('W_C', 0.35),
        step=0.05,
        help="Group C: provisioning ES, compatible land use"
    )

    # Display sum with warning if not equal to 1.0
    weight_sum = W_A + W_B + W_C

    if abs(weight_sum - 1.0) < 0.001:
        st.sidebar.success(f"Σ = {weight_sum:.3f} ✓")
    else:
        st.sidebar.error(f"Σ = {weight_sum:.3f} ≠ 1.0")
        st.sidebar.warning("Inter-group weights must sum to 1.0. Use the normalise button below.")

    # Normalise button
    if st.sidebar.button("Normalise inter-group weights"):
        if weight_sum > 0:
            W_A = W_A / weight_sum
            W_B = W_B / weight_sum
            W_C = W_C / weight_sum
            st.sidebar.success("Weights normalised to sum = 1.0")
            # Store normalised values in session state
            st.session_state['W_A_normalised'] = W_A
            st.session_state['W_B_normalised'] = W_B
            st.session_state['W_C_normalised'] = W_C
            st.rerun()

    # Use normalised values if available
    if 'W_A_normalised' in st.session_state:
        W_A = st.session_state['W_A_normalised']
        W_B = st.session_state['W_B_normalised']
        W_C = st.session_state['W_C_normalised']
        # Clear after use
        del st.session_state['W_A_normalised']
        del st.session_state['W_B_normalised']
        del st.session_state['W_C_normalised']

    st.sidebar.markdown("---")

    # ===================================================================
    # Section 5: Intra-group weights (expandable)
    # ===================================================================
    with st.sidebar.expander("5. Intra-Group Weights (Advanced)"):
        st.markdown("### Group A — Ecological integrity")

        defaults_a = config.get('group_a_weights', {})

        w_condition = st.slider(
            "Ecosystem condition",
            min_value=0.0,
            max_value=1.0,
            value=defaults_a.get('ecosystem_condition', 0.45),
            step=0.05,
            key='w_condition'
        )

        w_regulating_es = st.slider(
            "Regulating ES capacity",
            min_value=0.0,
            max_value=1.0,
            value=defaults_a.get('regulating_es', 0.35),
            step=0.05,
            key='w_regulating_es'
        )

        w_pressure = st.slider(
            "Low anthropogenic pressure",
            min_value=0.0,
            max_value=1.0,
            value=defaults_a.get('low_pressure', 0.20),
            step=0.05,
            key='w_pressure'
        )

        sum_a = w_condition + w_regulating_es + w_pressure

        if abs(sum_a - 1.0) < 0.001:
            st.success(f"Group A: Σ = {sum_a:.3f} ✓")
        else:
            st.error(f"Group A: Σ = {sum_a:.3f} ≠ 1.0")

        if st.button("Normalise Group A weights"):
            if sum_a > 0:
                w_condition = w_condition / sum_a
                w_regulating_es = w_regulating_es / sum_a
                w_pressure = w_pressure / sum_a
                st.success("Group A weights normalised")
                st.session_state['group_a_normalised'] = {
                    'w_condition': w_condition,
                    'w_regulating_es': w_regulating_es,
                    'w_pressure': w_pressure
                }
                st.rerun()

        # Use normalised values if available
        if 'group_a_normalised' in st.session_state:
            w_condition = st.session_state['group_a_normalised']['w_condition']
            w_regulating_es = st.session_state['group_a_normalised']['w_regulating_es']
            w_pressure = st.session_state['group_a_normalised']['w_pressure']
            del st.session_state['group_a_normalised']

        st.markdown("---")
        st.markdown("### Group B — Co-benefits")

        w_cultural_es = 1.0
        st.info(f"Cultural ES capacity: {w_cultural_es:.2f} (single criterion)")

        st.markdown("---")
        st.markdown("### Group C — Production function")

        defaults_c = config.get('group_c_weights', {})

        w_provisioning_es = st.slider(
            "Provisioning ES capacity",
            min_value=0.0,
            max_value=1.0,
            value=defaults_c.get('provisioning_es', 0.60),
            step=0.05,
            key='w_provisioning_es'
        )

        w_landuse_compatible = st.slider(
            "Compatible land use",
            min_value=0.0,
            max_value=1.0,
            value=defaults_c.get('compatible_landuse', 0.40),
            step=0.05,
            key='w_landuse_compatible'
        )

        sum_c = w_provisioning_es + w_landuse_compatible

        if abs(sum_c - 1.0) < 0.001:
            st.success(f"Group C: Σ = {sum_c:.3f} ✓")
        else:
            st.error(f"Group C: Σ = {sum_c:.3f} ≠ 1.0")

        if st.button("Normalise Group C weights"):
            if sum_c > 0:
                w_provisioning_es = w_provisioning_es / sum_c
                w_landuse_compatible = w_landuse_compatible / sum_c
                st.success("Group C weights normalised")
                st.session_state['group_c_normalised'] = {
                    'w_provisioning_es': w_provisioning_es,
                    'w_landuse_compatible': w_landuse_compatible
                }
                st.rerun()

        # Use normalised values if available
        if 'group_c_normalised' in st.session_state:
            w_provisioning_es = st.session_state['group_c_normalised']['w_provisioning_es']
            w_landuse_compatible = st.session_state['group_c_normalised']['w_landuse_compatible']
            del st.session_state['group_c_normalised']

    st.sidebar.markdown("---")

    # ===================================================================
    # Section 6: Gap analysis bonus
    # ===================================================================
    st.sidebar.header("6. Gap Analysis Bonus (Optional)")

    default_gap_bonus_max = config.get('eliminatory', {}).get('gap_bonus_max', 0.20)

    gap_bonus = st.sidebar.slider(
        "Gap priority bonus",
        min_value=0.0,
        max_value=default_gap_bonus_max,
        value=0.0,
        step=0.01,
        help=(
            "Optional positive weighting for areas identified as gaps "
            "in Module 1 analysis. 0.0 = no bonus."
        )
    )

    st.sidebar.markdown("---")

    # ===================================================================
    # Section 7: Module 1 weight suggestions
    # ===================================================================
    st.sidebar.header("7. Module 1 Weight Suggestions")

    # Check if Module 1 has been run and produced weight suggestions
    has_suggestions = 'proposed_group_a_weights' in st.session_state

    if has_suggestions:
        st.sidebar.info(
            "Module 1 gap analysis has proposed weights for Group A criteria "
            "based on ecosystem representativity deficits."
        )

        if st.sidebar.button(
            "Apply Module 1 weight suggestions",
            help=(
                "Applies gap-filling logic: criteria corresponding to under-represented "
                "ecosystem types receive higher weights. Only affects Group A intra-weights."
            )
        ):
            proposed = st.session_state['proposed_group_a_weights']

            # Validate handoff before applying
            try:
                from modules.module1_protected_areas.handoff import (
                    validate_weight_handoff,
                    format_weights_for_mce
                )

                config_path = Path(__file__).parent.parent / "config" / "criteria_defaults.yaml"
                validate_weight_handoff(proposed, str(config_path))
                formatted_weights = format_weights_for_mce(proposed)

                # Update Group A weights
                st.session_state['group_a_applied'] = {
                    'w_condition': formatted_weights.get('ecosystem_condition', w_condition),
                    'w_regulating_es': formatted_weights.get('regulating_es', w_regulating_es),
                    'w_pressure': formatted_weights.get('low_pressure', w_pressure)
                }

                st.sidebar.success("Module 1 weights validated and applied to Group A!")
                st.rerun()

            except ValueError as e:
                st.sidebar.error(f"Weight validation failed: {e}")
            except Exception as e:
                st.sidebar.error(f"Unexpected error applying weights: {e}")
    else:
        st.sidebar.info(
            "Run Module 1 gap analysis first to receive weight suggestions "
            "based on ecosystem representativity."
        )

    # Use applied weights if available
    if 'group_a_applied' in st.session_state:
        w_condition = st.session_state['group_a_applied']['w_condition']
        w_regulating_es = st.session_state['group_a_applied']['w_regulating_es']
        w_pressure = st.session_state['group_a_applied']['w_pressure']
        del st.session_state['group_a_applied']

    # ===================================================================
    # Return all parameters
    # ===================================================================
    return {
        'study_area_nuts_id': study_area_nuts_id,
        'study_area_name': study_area_name,
        'study_area_geometry': study_area_geometry,
        'threshold_pressure': threshold_pressure,
        'method': method,
        'alpha': alpha,
        'W_A': W_A,
        'W_B': W_B,
        'W_C': W_C,
        'w_condition': w_condition,
        'w_regulating_es': w_regulating_es,
        'w_pressure': w_pressure,
        'w_cultural_es': w_cultural_es,
        'w_provisioning_es': w_provisioning_es,
        'w_landuse_compatible': w_landuse_compatible,
        'gap_bonus': gap_bonus,
    }
