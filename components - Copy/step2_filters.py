import streamlit as st
import pandas as pd
import datetime
from utils.display import fmt_list
from utils.session_tables import build_temp_tables
from utils.display import calculate_relative_date
from callbacks import perform_step2_reset

def clear_step2_errors():
    st.session_state.validation_errors = []
    
def render_step2(orch):
    if not st.session_state.locked:
        return
        
    s2_expanded = not st.session_state.get("step_2_complete", False)
    filters = st.session_state.active_filters
    
    # Data Retrieval (Cached)
    if st.session_state.get("st_raw") is None:
        with st.status("🏗️ Pulling Project Master Data...", expanded=False):
            st.session_state.st_raw = orch.fetch_st_data()
    
    #Sitetracker dataframe
    st_df = st.session_state.st_raw    
    
    if st_df is None or st_df.empty:
        st.warning("No projects found for this Customer/Market criteria.")
        return
    
    # Calculate the min/max safely (Pandas handles the NaNs internally now)
    raw_min = st_df["CONSTRUCTION START (F)"].min()
    raw_max = st_df["CONSTRUCTION START (F)"].max()

    # Convert the result to a date object for the UI/Selectors
    # We use a guard (if pd.notnull) just in case the entire column is empty
    min_date = raw_min.date() if pd.notnull(raw_min) else None
    max_date = raw_max.date() if pd.notnull(raw_max) else None    
        
    if min_date is None:
        st.error("🚨 No valid construction dates found in the source data. Please check the Sitetracker records.")
        return        
        
    if st.session_state.get("crews_raw") is None:
        with st.status("💪 Pulling Initial Crew Data...", expanded=False):
            st.session_state.crews_raw = orch.fetch_crew_data()
    
    # Dynamic Year logic for CREWS 
    now = datetime.datetime.now()
    current_year = now.year
    # Year Selection (+- 5/10 years)
    years = list(range(current_year - 5, current_year + 10))
    # Find index of current year to set as default
    default_year_index = years.index(current_year) if current_year in years else 0
    # Set week defaults based on current week (from system)
    current_week = datetime.datetime.now().isocalendar()[1]
    
    crew_df = st.session_state.crews_raw
        
    # 🟢 Initialize widget states if they don't exist yet
    if "s2_date_range" not in st.session_state:
        # Default to a 90-day window from the earliest available date
        default_start = datetime.datetime.now().date()
        default_end = default_start + datetime.timedelta(days=90)
        st.session_state["s2_date_range"] = (default_start, default_end)
    
    st.subheader("🏗️ STEP 2: Project Template & Crew Scope")
    
    with st.container(border=True):
        # --- SECTION A: SITETRACKER PROJECTS ---
        st.markdown("#### 📅 1. Sitetracker Project Template")
        with st.container(border=True):
            st.markdown(f"**Execution Timeline** (Baseline Data Range: {min_date} to {max_date})")
            
            # Simplified layout
            col_date, col_empty = st.columns([1.5, 2.5])
            
            with col_date:
                req_range = st.date_input(
                    "Date Range", 
                    key="s2_date_range",
                    label_visibility="collapsed" # Keeping your formatting
                )

            # 🟢 DATE VALIDATION GUARD
            # Streamlit returns a tuple of length 1 if the user hasn't clicked the end date yet.
            if isinstance(req_range, tuple) and len(req_range) == 2:
                d_start, d_end = req_range
                p_start, p_end = pd.to_datetime(d_start), pd.to_datetime(d_end)
                
                # Filter by Date Range safely
                st_filtered = st_df[(st_df["CONSTRUCTION START (F)"] >= p_start) & (st_df["CONSTRUCTION START (F)"] <= p_end)]
            else:
                # If they haven't picked the second date, empty the dataframe so the UI gracefully waits
                st_filtered = pd.DataFrame(columns=st_df.columns)
            
            # Populate options from the FILTERED dataframe (added a safety check for empty df)
            template_options = sorted(st_filtered["PROJECT TEMPLATE NAME"].dropna().unique().tolist()) if not st_filtered.empty else []
            
            sel_templates = st.multiselect("Project Templates", options=template_options, key="project_templates")
            
            # Final Projects DF based on templates chosen from the date-filtered list
            final_projects_df = st_filtered[st_filtered["PROJECT TEMPLATE NAME"].isin(sel_templates)] if sel_templates else st_filtered

        st.markdown("<br>", unsafe_allow_html=True)

        # --- SECTION B: CREW SCOPE ---
        st.markdown("#### 👷 2. Crews Scope")
                   
        if crew_df is None or crew_df.empty:
            st.warning("⚠️ Crew data is currently empty. Checking connection...")
            
        with st.container(border=True):
            c1, c2, c3, c4 = st.columns([1, 1, 2, 2])
            
            with c1:
                sel_year = st.selectbox("Year", options=years, index=default_year_index, key="sel_year")
            
            with c2:
                # Week Selection (1-52)
                sel_week = st.selectbox("Week", options=list(range(1, 53)), index=current_week, key="sel_week")
            
            # DEFENSIVE FILTERING: Cast the UI integers to strings to perfectly match the cleaned DataFrame
            time_filtered_crew = crew_df[
                (crew_df["YEAR"] == str(sel_year)) & 
                (crew_df["WEEK"] == str(sel_week))
            ]
            
            # --- TEMPORARY DEBUG ---
            if time_filtered_crew.empty:
                # This will help you see if YEAR is a string or int in the DF
                actual_year_type = type(crew_df["YEAR"].iloc[0]) if not crew_df.empty else "N/A"
                st.error(f"❌ Zero rows found for Year {sel_year} ({type(sel_year)}) vs DF ({actual_year_type}).  Choose another time period.")
            else:
                st.caption(f"✅ Found {len(time_filtered_crew)} rows for Year {sel_year}, Week {sel_week}") 
                with st.expander("Crews Found: Crew Scope", expanded=False):
                    st.dataframe(time_filtered_crew)
            # ----------------------
            
            with c3:
                # Programs available in this specific Year/Week
                prog_options = sorted(time_filtered_crew["PROGRAM"].dropna().unique().tolist())
                sel_program = st.selectbox("Program", options=["All"] + prog_options, key="sel_program")
                
            with c4:
                # 🟢 FURTHER REACTION: If a program is selected (other than 'All'), filter again
                if sel_program != "All":
                    scope_subset = time_filtered_crew[time_filtered_crew["PROGRAM"] == sel_program]
                else:
                    scope_subset = time_filtered_crew

                scope_options = sorted([s for s in scope_subset["CREW SCOPE"].unique() if pd.notnull(s) and str(s).strip() != ""])
                sel_c_scope = st.selectbox("Crew Scope", options=[None] + scope_options, key="single_crew_scope")

                # 🟢 FINAL FILTERED DATAFRAME for metrics/staging
                if sel_c_scope:
                    final_crew_df = scope_subset[scope_subset["CREW SCOPE"] == sel_c_scope]
                else:
                    final_crew_df = pd.DataFrame()

        # --- VALIDATION & ACTION ---
        current_errors = []
        
        # 🟢 Ensure both dates are picked
        if not isinstance(req_range, tuple) or len(req_range) != 2:
            current_errors.append("a complete Start and End Date")
            
        if not sel_templates:
            current_errors.append("at least one Project Template")
            
        if not sel_c_scope:
            current_errors.append("a Crew Scope")

        #Calculate Effective Capacity
        # We sum (CREWS * CONFIDENCE) across the filtered dataframe
        if final_crew_df.empty:
            effective_crews = 0.0
        else:
            # 🟢 SAFELY MULTIPLY: Extract the series and calculate
            c_count = final_crew_df["CREWS"]
            c_conf = final_crew_df["CONFIDENCE"]
            
            # 💡 TIP: If database stores 80% as '80' instead of '0.8', 
            # uncomment the next line to prevent hyper-inflated capacity!
            # c_conf = c_conf / 100.0  
            
            effective_crews = (c_count * c_conf).sum()

        # ... (Metrics and Finalize Button Row) ...
        global_debug_container = st.container()
        
        bl, b_final, b_reset, gap, m1, m2, m3, br = st.columns([0.4, 2.2, 2.2, 0.7, 1.5, 1.5, 1.5, 0.5])
        
        with b_reset:
            st.markdown("<div style='padding-top: 1.2rem;'></div>", unsafe_allow_html=True)
            # 🟢 The 'on_click' triggers the function BEFORE the app reruns!
            # Note: Do not put () after perform_step2_reset
            st.button("🔄 Reset Step 2", use_container_width=True, on_click=perform_step2_reset, args=[current_week-1])

        with b_final:
            st.markdown("<div style='padding-top: 1.2rem;'></div>", unsafe_allow_html=True)
            if st.button("🏁 Finalize Scope", type="primary", use_container_width=True):
                if current_errors:
                    st.session_state.validation_errors = current_errors
                else:
                    st.markdown("<div style='padding-top: 1.2rem;'></div>", unsafe_allow_html=True)
            
                    st.session_state.validation_errors = []
        
                    # Update these keys to match your UI variables
                    st.session_state.active_filters["project_templates"] = sel_templates 
                    st.session_state.active_filters["selected_crew_scope"] = sel_c_scope 
        
                    # Save the Year and Week of crews for easy reference
                    st.session_state.active_filters["crew_target_year"] = sel_year
                    st.session_state.active_filters["crew_target_week"] = sel_week
        
                    # Storing the relative date range of projects for reference
                    st.session_state.active_filters["st_rel_date_range"] = req_range
                            
                    # Saving the filtered DataFrames for the next step
                    st.session_state.active_filters["final_projects_df"] = final_projects_df
                    st.session_state.active_filters["final_crew_df"] = final_crew_df
        
                    st.session_state.step_2_complete = True
        
                    build_temp_tables(orch, global_debug_container)
                    st.rerun()
        
        with m1:
            st.metric("Projects", f"{len(final_projects_df):,}")
        with m2:
            st.metric("Templates", final_projects_df["PROJECT TEMPLATE NAME"].nunique())
        with m3:
            # Using the new calculated effective capacity
            st.metric("Effective Crews", f"{effective_crews:,.1f}")
                                     
        # --- MOVE DEBUG STUFF HERE (Outside the columns) ---

    if st.session_state.get("step_2_complete"):
        st.divider()

        # =====================================================================
        # 🕵️ GLOBAL DEBUG ZONE (Renders full-width at the bottom of the app)
        # =====================================================================
        if "final_site_projects" in st.session_state and "final_job_matrix" in st.session_state:
                    
            debug_projects = st.session_state["final_site_projects"]            
            debug_matrix = st.session_state["final_job_matrix"]

            #st.write("Project Data Columns:", debug_projects.columns.tolist())
            #st.write("Matrix Data Columns:", debug_matrix.columns.tolist())
            
            st.markdown("---")
            with st.expander("🕵️ DEBUG: The Merge Matchmaker (Full Width)", expanded=False):
                st.markdown("**Project ID / Site ID Comparison:**")
                        
                col_m1, col_m2 = st.columns(2)
                with col_m1:
                    st.write("Sitetracker IDs:", sorted([x for x in debug_projects['PROJECT_ID'].unique() if x is not None], reverse=True))
                with col_m2:
                    st.write("BOM IDs:", sorted([x for x in debug_matrix['PROJECT_ID'].unique() if x is not None], reverse=True))
                            
                st.markdown("**Supplier Name Comparison:**")
                col_m3, col_m4 = st.columns(2)
                with col_m3:
                    st.write("Sitetracker Suppliers:", sorted([x for x in debug_projects['SP_ASSIGNED'].unique() if x is not None], reverse=True)[:15])
                with col_m4:
                    st.write("BOM Suppliers:", sorted([x for x in debug_matrix['SP_NAME'].unique() if x is not None], reverse=True)[:15])
    
        #Now that we have the Data Viewer, we don't need these
        #st.subheader("🛠️ Technical Preview (Snowflake Temp Tables)")
                
        #orch.preview_table("SWA_SITE_PROJECTS")
        #orch.preview_table("SWA_SUPPLIERS")
        #orch.preview_table("SWA_JOB_SP_MATRIX")
        
    # 3. VALIDATION MESSAGE (Below the row)
    if st.session_state.get("validation_errors"):
        st.error(f"⚠️ **Action Required:** Please select {', '.join(st.session_state.validation_errors)}.")

     