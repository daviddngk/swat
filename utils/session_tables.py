import streamlit as st
import pandas as pd
import numpy as np

def build_temp_tables(orch, target_container=None):
    if not st.session_state.get('step_2_complete'):
        return
    
    if target_container:
        with target_container:
            st.markdown("---")
            with st.status("🛠️ Building Optimization Universe...", expanded=True) as status:
                st.write("Writing Projects...")
                # CRITICAL: Ensure write_site_projects doesn't have an st.expander inside it!
                final_projects_df = orch.write_site_projects()
                
                if final_projects_df is None or final_projects_df.empty:
                    st.error("🚨 Pipeline Halted: Projects failed to build.")
                    status.update(label="❌ Build Failed", state="error")
                    return False
                    
                st.write("Writing Suppliers...")
                orch.write_suppliers(projects_df=final_projects_df)
                
                st.write("Generating Job Matrix...")
                st.session_state["job_matrix_done"] = orch.write_job_sp_matrix()

                with st.spinner("Generating Solver Table..."):
                    if st.session_state.get("job_matrix_done"):
                        st.session_state["solver_table_built"] = orch.write_solver_table()
                    else:
                        st.warning("Waiting on Job Matrix to complete...")
                    
                status.update(label="✅ Tables Ready!", state="complete", expanded=False)
                return True

def calculate_octile_road_miles(lat1, lon1, lat2, lon2):
    """
    Estimates road distance between two points using the octile distance
    approximation. Works with pandas Series or numpy arrays.

    The octile heuristic accounts for diagonal movement (like road grids)
    by weighting the dominant axis more heavily, then applying a calibration
    factor to better reflect real road distances vs. straight-line distance.
    """
    # 1. Convert decimal degrees to approximate miles per degree
    #    (lat degrees are fixed; lon degrees shrink toward the poles)
    avg_lat = np.radians((np.array(lat1) + np.array(lat2)) / 2.0)
    miles_per_lat_deg = 69.0
    miles_per_lon_deg = 69.0 * np.cos(avg_lat)

    # 2. Delta in miles along each axis
    dx = np.abs(np.array(lon2) - np.array(lon1)) * miles_per_lon_deg
    dy = np.abs(np.array(lat2) - np.array(lat1)) * miles_per_lat_deg

    # 3. Octile distance formula
    #    Moves diagonally where possible (cost √2 ≈ 1.4142), then straight.
    #    octile = (dx + dy) - (2 - √2) * min(dx, dy)
    octile = (dx + dy) - (2 - np.sqrt(2)) * np.minimum(dx, dy)

    # 4. Road calibration factor
    #    Real road distances average ~1.2–1.4x straight-line (the "detour index").
    #    1.3 is a common empirical middle ground for US road networks.
    road_factor = 1.3

    return octile * road_factor