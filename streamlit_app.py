import streamlit as st
from snowflake.snowpark.context import get_active_session
from state import init_session_state
from data_orchestration import DataOrchestrator
from components.step1_filters import render_step1
from components.locked_summary import render_locked_summary
from components.step2_projects import render_step2
from components.step3_data_browser import render_data_browser
from components.step4_sms_weights import render_sms_and_weights
from components.step5_solve_results import render_solve_results

st.set_page_config(page_title="SWA Optimizer", layout="wide")

PAGES = [
    "Scope & Filters",
    "Data Browser",
    "Supplier SMS & Weights",
    "Solve & Results",
]

@st.cache_resource
def get_orchestrator():       
    # Use below, if executing from Snowflake environment
    session = get_active_session()
    # session.sql("ALTER SESSION SET QUOTED_IDENTIFIERS_IGNORE_CASE = FALSE").collect()    
    return DataOrchestrator(session)
    
def run_app():
    init_session_state()

    st.title("🏗️ SWA Scope & Optimization Tool")

    # 1. Determine completion status
    # This flag is updated inside render_step2
    is_unlocked = st.session_state.get("step_2_complete", False)
    
    # 2. Dynamic Sidebar Filter
    if is_unlocked:
        nav_options = PAGES
    else:
        nav_options = ["Scope & Filters"]
        st.sidebar.warning("🔒 **Solver Locked**")
        st.sidebar.caption("Complete Step 2 to unlock navigation.")

    page = st.sidebar.radio("Navigate", nav_options)
    orch = get_orchestrator()
    
    if page == "Scope & Filters":
        try:
            if "df1_raw" not in st.session_state:
                with st.spinner("Loading initial data..."):
                    st.session_state.df1_raw = orch.fetch_price_matrix()
        except Exception as e:
            st.error(f"⚠️ Critical Error loading initial data: {e}")
            return
            
        render_locked_summary()
        render_step1(orch)
        render_step2(orch) # Flag 'step_2_complete' is set here
 
    elif page == "Data Browser":
        render_data_browser(orch)

    elif page == "Supplier SMS & Weights":
        render_sms_and_weights(orch)

    elif page == "Solve & Results":
        render_solve_results(orch)
        
if __name__ == "__main__":
    run_app()