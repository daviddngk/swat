import streamlit as st
import pandas as pd
import datetime
from state import reset_filters, lock_step1, clear_validation_errors, set_validation_errors

REQUIRED_FIELDS = ["customers", "markets", "price_matrix"]

###
### Resets the state, widgets, and filters specific to Step 1
###
def handle_reset() -> None:
    reset_filters()

###
### Validates and sets up all state, widgets, and filters
###   needed to move from Step 1 to Step 2
###
def handle_proceed(orch) -> None:
    clear_validation_errors()
    
    filters = st.session_state.active_filters
    errors = []
    
    # Validation Logic
    date_range = filters.get("date_range", ())
    if len(date_range) != 2:
        errors.append("Date Range (both start and end)")
    
    for field in REQUIRED_FIELDS:
        if not filters.get(field):
            # Formats 'sourcing_managers' to 'Sourcing Managers'
            errors.append(field.replace("_", " ").title())
    
    if errors:
        set_validation_errors(errors)
        return # 🛑 Stop here if there are errors

    # Finalize the Price Matrix Data (Step 1 Results)
    processed_df = pd.DataFrame() 
    
    pandas_filters = {
        "CUSTOMER": filters.get("customers", []),
        "MARKET": filters.get("markets", []),
        "REGION" : filters.get("regions", []),
        "PROJECT NAME" : filters.get("price_matrix", []),
        "SUPPLIER" : filters.get("suppliers", [])
    }
    
    if st.session_state.get("df1_raw") is not None:
        processed_df = orch.apply_dynamic_filters(
            st.session_state.df1_raw, 
            pandas_filters
        )
    # This forces Step 2 to re-fetch based on the NEW Customer/Market
        st.session_state.st_raw = None
        st.session_state.crews_raw = None # Clear crews too
        st.session_state.active_filters["BOM_df"] = None # Clear BOM data
        
    # Save the finalized slice for the UI to use later
    st.session_state["df1_filtered"] = processed_df
    
    # Clear Global Debug Zones
    if "debug_matrix_df" in st.session_state:
        del st.session_state["debug_matrix_df"]
    if "debug_actuals_df" in st.session_state:
        del st.session_state["debug_actuals_df"]
        
    # Lock and Transition
    lock_step1()

###
### Calls procedure in State.py to clear errors and states for Step 1.
###
def clear_errors() -> None:
    clear_validation_errors()

###
### Resets the state, widgets, and filters specific to Step 2.
###
def perform_step2_reset(def_week):
    """Resets the state, widgets, and filters specific to Step 2."""
    
    current_year = datetime.datetime.now().year
    
    # 1. Reset Flow States
    st.session_state["step_2_complete"] = False
    st.session_state["validation_errors"] = []
        
    # 🟢 Notice: st_raw and crews_raw are NOT cleared here. 
    # They stay in cache so the UI bounces back instantly.
    
    # 2. OVERWRITE WIDGET KEYS
    # This explicitly commands the frontend to empty/reset the boxes
    st.session_state["project_templates"] = []      # Empty multiselect
    st.session_state["single_crew_scope"] = None    # Empty selectbox
    st.session_state["sel_program"] = "All"
    st.session_state["sel_week"] = def_week
    st.session_state["sel_year"] = current_year     # Fixed: Real year, not 0
    st.session_state["solver_table_built"] = False
    
    # 3. Reset the Date Range widget
    default_start = datetime.datetime.now().date()
    default_end = default_start + datetime.timedelta(days=90)
    st.session_state["s2_date_range"] = (default_start, default_end)
            
    # 4. Wipe Step 2 data from active_filters (It is safe to use 'del' on regular dicts)
    filter_keys = [
        "project_templates", "selected_crew_scope", "st_project_window", 
        "crew_target_year", "crew_target_week", "effective_crew_capacity", 
        "final_projects_df", "final_crew_df", "st_rel_date_range"
    ]
    if "active_filters" in st.session_state:
        for k in filter_keys:
            if k in st.session_state.active_filters:
                del st.session_state.active_filters[k]
                
    # 5. Clear Global Debug Zones
    if "debug_matrix_df" in st.session_state:
        del st.session_state["debug_matrix_df"]
    if "debug_actuals_df" in st.session_state:
        del st.session_state["debug_actuals_df"]