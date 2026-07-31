import streamlit as st
from utils.display import fmt_list, display_item, format_date_range

def render_locked_summary():
    if not st.session_state.get('locked'):
        return
    
    st.markdown("### 🔒 Scope Parameters (Locked)")
    with st.container(border=True):
        
        # --- TOP ROW (HTML for Size & Perfect Centering) ---
        gap_left, t1, gap_middle, t2, gap_right = st.columns([1.5, 2, 1, 2.25, 2.25]) 
        #t1, t2 = st.columns([1, 1.5]) 
        filters = st.session_state.active_filters
                
        with t1:
            cust_val = fmt_list(filters, 'customers')
            # 🟢 Added negative margin-bottom to pull the line up
            st.markdown(f"""
                <div style="text-align: center; padding: 0.2rem 0 0 0; margin-bottom: -0.5rem; line-height: 1.1;">
                    <span style="font-size: 1.1rem; font-weight: 600; color: gray;">🏢 Customers</span><br>
                    <span style="font-size: 1.6rem; font-weight: bold;">{cust_val}</span>
                </div>
            """, unsafe_allow_html=True)
            
        with t2:
            mkt_val = fmt_list(filters, 'markets')
            st.markdown(f"""
                <div style="text-align: center; padding: 0.2rem 0 0 0; margin-bottom: -0.5rem; line-height: 1.1;">
                    <span style="font-size: 1.1rem; font-weight: 600; color: gray;">🏪 Market</span><br>
                    <span style="font-size: 1.6rem; font-weight: bold;">{mkt_val}</span>
                </div>
            """, unsafe_allow_html=True)
            
        # 🟢 THE TWEAK: Changed the first number in margin from 0.5rem to 1rem
        st.markdown("<hr style='margin: 1rem 0 0.5rem 0; border: none; border-top: 1px solid rgba(128, 128, 128, 0.2);'>", unsafe_allow_html=True)
        
        # --- BOTTOM ROW ---
        r1, r2, r3 = st.columns([1.3, 1, 1])
        
        with r1: # Price Matrix Info
            raw_dates = filters.get('date_range')
            dr_str = format_date_range(raw_dates) if raw_dates else "All Time"
            
            display_item("📅", "Price Matrix Dates", dr_str)
            display_item("👤", "Sourcing Manager", fmt_list(filters, 'sourcing_managers'))
            display_item("📊", "Price Matrix", fmt_list(filters, 'price_matrix'))
            
        with r2: # Supplier & Sitetracker Info
            include = filters.get('suppliers', [])
            excluded = filters.get('excluded_suppliers', [])
            
            # Step 2 Placeholders (Defaults to 'N/A')
            st_dates = filters.get('st_rel_date_range', 'N/A')
            templates = filters.get('project_templates', [])
            temp_str = ", ".join(templates) if templates else "N/A"
            
            display_item("📅", "Planning Dates", st_dates)
            display_item("📝", "Project Templates", temp_str)
        
            if include:
                incld_str = ", ".join(include) if len(include) < 5 else f"{len(include)} Suppliers"
                display_item("🏭", "Included Suppliers", incld_str)
                
            if excluded:
                excl_str = ", ".join(excluded) if len(excluded) < 5 else f"{len(excluded)} items"
                display_item("🚫", "Excluded Supp.", excl_str)

        with r3: # Crew Info
            program = fmt_list(filters, 'programs') if filters.get('programs') else "N/A"
            
            scope = filters.get('selected_crew_scope', "N/A")                
            year = filters.get('crew_target_year', '')
            week = filters.get('crew_target_week', '')
            
            time_context = f" ({year} Wk {week})" if year and week else "N/A"
            
            display_item("📅", "Crew Dates", time_context)
            display_item("👷", "Crew Program", program)
            display_item("🛠️", "Crew Scope", f"{scope}{time_context}")