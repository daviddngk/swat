import streamlit as st
from datetime import date, timedelta

DEFAULT_FILTERS = {
    "date_range": (date.today() - timedelta(days=365), date.today()),
    "customers": [],
    "suppliers": [],
    "regions": [],
    "markets": [],
    "sourcing_managers": [],
    "price_matrix": []
}

def init_session_state() -> None:
    if "active_filters" not in st.session_state:
        st.session_state.active_filters = DEFAULT_FILTERS.copy()
    if "locked" not in st.session_state:
        st.session_state.locked = False
    if "reset_ctr" not in st.session_state:
        st.session_state.reset_ctr = 0
    if "validation_errors" not in st.session_state:
        st.session_state.validation_errors = []
    if "st_raw" not in st.session_state:
        st.session_state.st_raw = None
    if "crews_raw" not in st.session_state:
        st.session_state.crews_raw = None
    if "step_2_complete" not in st.session_state:
        st.session_state.step_2_complete = False
    if "job_matrix_done" not in st.session_state:
        st.session_state.job_matrix_done = False
    if "solver_table_built"not in st.session_state:
        st.session_state.solver_table_built = False

def reset_filters() -> None:
    # 1. Reset the seleted values
    st.session_state.active_filters = DEFAULT_FILTERS.copy()
    
    # 2. Reset the App State
    st.session_state.locked = False
    st.session_state.step_2_complete = False
    st.session_state.reset_ctr += 1 
    st.session_state.validation_errors = []
    
    # 3. Clear all "Context-Dependent" Data
    # We keep df1_raw (price matrix dataset), but we clear the results.
    st.session_state.df1_filtered = None 
    st.session_state.st_raw = None      
    st.session_state.crews_raw = None     
    
def lock_step1() -> None:
    st.session_state.locked = True

def clear_validation_errors() -> None:
    st.session_state.validation_errors = []

def set_validation_errors(errors: list) -> None:
    st.session_state.validation_errors = errors
