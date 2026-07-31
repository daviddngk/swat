import colorsys
import pandas as pd
import pydeck as pdk
import streamlit as st

def prep_map_data(matrix_df):
    """Dynamically generates a color palette for the suppliers in the matrix."""
    unique_suppliers = matrix_df['SP_NAME'].dropna().unique().tolist()
    
    supplier_colors = {}
    n_sp = len(unique_suppliers)
    
    for i, sp in enumerate(unique_suppliers):
        r, g, b = colorsys.hsv_to_rgb(i / max(n_sp, 1), 0.85, 0.9)
        supplier_colors[sp] = [int(r * 255), int(g * 255), int(b * 255), 200]
        
    matrix_df['WH_COLOR'] = matrix_df['SP_NAME'].apply(
        lambda sp: supplier_colors.get(sp) if pd.notnull(sp) else [255, 255, 255, 150]
    )
    
    return matrix_df

def render_strategy_map(projects_df, matrix_df):
    """Builds the 3D interactive PyDeck map showing all eligible bids/routes."""
    if projects_df.empty or matrix_df.empty:
        st.info("ℹ️ Missing data. Cannot render map.")
        return

    # 1. Prepare copies to avoid mutating session state
    p_df = projects_df.copy()
    m_df = matrix_df.copy()

    # Handle potential column naming differences in the projects dataframe
    if 'PROJECT ID' in p_df.columns and 'PROJECT_ID' not in p_df.columns:
        p_df = p_df.rename(columns={'PROJECT ID': 'PROJECT_ID'})

    # 2. Force coordinate columns to floats
    for col in ['SITE_LATITUDE', 'SITE_LONGITUDE']:
        if col in p_df.columns:
            p_df[col] = pd.to_numeric(p_df[col], errors='coerce')
            
    for col in ['WH_LATITUDE', 'WH_LONGITUDE']:
        if col in m_df.columns:
            m_df[col] = pd.to_numeric(m_df[col], errors='coerce')

    # 3. Merge the site coordinates into the matrix data
    map_df = pd.merge(
        m_df,
        p_df[['PROJECT_ID', 'SITE_LATITUDE', 'SITE_LONGITUDE']],
        on='PROJECT_ID',
        how='inner'
    )

    # 4. Apply dynamic colors and drop rows missing core site coords
    map_df = prep_map_data(map_df)
    map_df = map_df.dropna(subset=['SITE_LATITUDE', 'SITE_LONGITUDE'])
    
    if map_df.empty:
        st.info("ℹ️ No valid coordinate combinations available to map.")
        return

    # 5. THE SITES LAYER 
    sites_df = map_df.drop_duplicates(subset=['PROJECT_ID', 'SITE_LATITUDE', 'SITE_LONGITUDE']).copy()
    
    sites_layer = pdk.Layer(
        "ScatterplotLayer",
        data=sites_df,
        get_position="[SITE_LONGITUDE, SITE_LATITUDE]",
        get_color=[255, 255, 255, 200], 
        get_radius=1500, 
        pickable=True,
        stroked=True,
        get_line_color=[0, 0, 0, 200], 
        line_width_min_pixels=1
    )
    
    # 6. THE WAREHOUSE LAYER 
    assigned_mask = map_df['WH_LATITUDE'].notna() & (map_df['WH_LATITUDE'] != 0.0)
    wh_df = map_df[assigned_mask].drop_duplicates(subset=['MUSID', 'WH_LATITUDE', 'WH_LONGITUDE']).copy()
    
    wh_layer = pdk.Layer(
        "ScatterplotLayer",
        data=wh_df,
        get_position="[WH_LONGITUDE, WH_LATITUDE]",
        get_color="WH_COLOR", 
        get_radius=4500, 
        pickable=True,
        stroked=True,
        get_line_color=[255, 255, 255, 255], 
        line_width_min_pixels=3
    )
    
    # 7. THE STRATEGY ARCS 
    arc_layer = pdk.Layer(
        "ArcLayer",
        data=map_df[assigned_mask],
        get_source_position="[SITE_LONGITUDE, SITE_LATITUDE]",
        get_target_position="[WH_LONGITUDE, WH_LATITUDE]",
        get_source_color=[255, 255, 255, 50], 
        get_target_color="WH_COLOR",          
        get_width=2,
        pickable=True 
    )

    # 8. CAMERA
    view_state = pdk.ViewState(
        latitude=map_df['SITE_LATITUDE'].mean(),
        longitude=map_df['SITE_LONGITUDE'].mean(),
        zoom=5.5,
        pitch=45 
    )
    
    # 9. TOOLTIPS
    tooltip = {
        "html": "<b>Project:</b> {PROJECT_ID} <br/>"
                "<b>Market:</b> {SP_MARKET} <br/>"
                "<b>Eligible SP:</b> {SP_NAME} <br/>"
                "<b>Drive Distance:</b> {DRIVE_DISTANCE} miles",
        "style": {
            "backgroundColor": "#222222",
            "color": "white",
            "fontFamily": "sans-serif"
        }
    }

    # 10. RENDER
    st.pydeck_chart(pdk.Deck(
        layers=[arc_layer, sites_layer, wh_layer], 
        initial_view_state=view_state,
        tooltip=tooltip,
        map_style="dark" 
    ))