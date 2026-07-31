import streamlit as st
from callbacks import clear_errors
from utils.display import calculate_relative_date
from callbacks import handle_reset, handle_proceed

def render_smart_filter(col_obj, df, orch, key_name: str, display_name: str, multi: bool = True) -> None:
    with col_obj:
        # Use a generic prefix to handle both widget types
        filter_key = f"filter_{key_name}_{st.session_state.reset_ctr}"
        
        # Sync widget state to active_filters
        if filter_key in st.session_state:
            val = st.session_state[filter_key]
            # Crucial: Always store as a list so the Orchestrator's 
            # filtering logic remains consistent
            st.session_state.active_filters[key_name] = val if isinstance(val, list) else ([val] if val else [])

        # Get available options based on other active filters
        opts = orch.get_smart_options(df, st.session_state.active_filters, key_name)
        
        # Ensure current selections stay in the list even if they'd be filtered out
        current_selection = st.session_state.active_filters.get(key_name, [])
        display_opts = sorted(list(set(opts + current_selection)))

        if multi:
            st.multiselect(
                display_name,
                options=display_opts,
                default=current_selection,
                disabled=st.session_state.locked,
                key=filter_key,
                on_change=clear_errors,
                label_visibility="visible"
            )
        else:
            # For single select, we handle the "None" or "All" case
            # We add an empty string or 'Select...' if no selection exists
            select_options = [""] + display_opts
            
            # Find the index of the current selection for the selectbox
            current_val = current_selection[0] if current_selection else ""
            try:
                idx = select_options.index(current_val)
            except ValueError:
                idx = 0

            st.selectbox(
                display_name,
                options=select_options,
                index=idx,
                disabled=st.session_state.locked,
                key=filter_key,
                on_change=clear_errors,
                label_visibility="visible"
            )

def render_step1(orch):
    df1 = st.session_state.df1_raw
    
    with st.expander(" 🔍 **Price Matrix Scope**", expanded=not st.session_state.locked):        
        
        st.markdown("🗓 Choose Price Matrix Time Period")
        t_col1, t_col2, t_col3, date_col, t_col4 = st.columns([0.75, 0.75, 1, 2.5, 3.5], gap="small")
            
        with t_col1:
            direction = st.selectbox(
            "Direction", # Descriptive label
            ["Last", "Next"], 
            index=0, 
            disabled=st.session_state.locked,
            key="dir_select",
            label_visibility="collapsed" # 👈 This hides it visually
            )
        with t_col2:
            count = st.selectbox(
                "Count", 
                list(range(1, 13)), 
                index=2, 
                disabled=st.session_state.locked,
                key="count_select",
                label_visibility="collapsed" # 👈 Hides the label
            )
        with t_col3:
            grain = st.selectbox(
                "Grain", 
                ["Months", "Quarters"], 
                index=0, 
                disabled=st.session_state.locked,
                key="grain_select",
                label_visibility="collapsed" # 👈 Hides the label
            )
                
        # Calculate the range immediately
        calculated_range = calculate_relative_date(direction, count, grain)
        # Call the utility to update state
        st.session_state.active_filters["date_range"] = calculated_range          
                
        with date_col:
            st.date_input(
                label="Price Matrix Date Range",
                value=calculated_range,
                disabled=True,
                label_visibility="collapsed"
            )            
        
        c1, c2, c3 = st.columns(3, gap="large")
        
        # Fill in the interrelated filters 
        render_smart_filter(c1, df1, orch, "customers", "🏢 Customer", multi=False)
        render_smart_filter(c1, df1, orch, "sourcing_managers", "👤 Sourcing Managers")
        render_smart_filter(c2, df1, orch, "regions", "🌎 Regions")
        render_smart_filter(c2, df1, orch, "markets", "🏪 Markets")
        render_smart_filter(c3, df1, orch, "price_matrix", "📊 Price Matrix", multi=False)
        
        st.markdown("---")
        
        # The UI Sandbox
        # Create a copy of active_filters that ignores the manual supplier checkboxes.
        # This forces the orchestrator to return the full list of valid suppliers for the selected regions/markets.
        ui_filters = {k: v for k, v in st.session_state.active_filters.items() if k not in ["suppliers", "excluded_suppliers"]}
        
        # Feed the sandbox filters to the orchestrator instead of the real ones
        temp_df = orch.apply_final_filters(df1, ui_filters)

        st.markdown("#### 🏭 Suppliers in Scope")
        
        # Get the raw list of valid suppliers based on the current dropdowns
        raw_supplier_list = temp_df[['SUPPLIER']].drop_duplicates().sort_values('SUPPLIER')
        
        # Create a unique "signature" of these specific suppliers
        sig = "|".join(raw_supplier_list['SUPPLIER'].tolist())
        
        # 🟢 Initialize the base dataframe ONLY when the upstream dropdowns change
        if "step1_supplier_df" not in st.session_state or st.session_state.get("step1_supplier_sig") != sig:
            current_excluded = st.session_state.active_filters.get("excluded_suppliers", [])
            raw_supplier_list['Include'] = ~raw_supplier_list['SUPPLIER'].isin(current_excluded)
            
            st.session_state["step1_supplier_df"] = raw_supplier_list
            st.session_state["step1_supplier_sig"] = sig
            
        edited_suppliers = st.data_editor(
            st.session_state["step1_supplier_df"],  # 👈 Feed it the UNALTERED base state!
            column_config={
                "Include": st.column_config.CheckboxColumn(
                    "Include in Scope", 
                    width="small",  
                    help="Uncheck to exclude from analysis"
                ),
                "SUPPLIER": st.column_config.TextColumn(
                    "Supplier Name", 
                    disabled=True,
                    width="large"   
                )
            },
            hide_index=True,
            use_container_width=True, 
            key=f"supp_editor_{st.session_state.reset_ctr}"
        )

        # Update the downstream filters for Step 2 and beyond using the output
        st.session_state.active_filters["excluded_suppliers"] = edited_suppliers[edited_suppliers['Include'] == False]['SUPPLIER'].tolist()
        st.session_state.active_filters["suppliers"] = edited_suppliers[edited_suppliers['Include'] == True]['SUPPLIER'].tolist()
        
        st.markdown("<br>", unsafe_allow_html=True) 
        
        # Validate that we have the min filters required.
        if st.session_state.get("validation_errors"):
            st.error(f"⚠️ **Missing Required Parameters:** {', '.join(st.session_state.validation_errors)}. Please fill these to proceed.")

        # Calculate supplier counts
        total_suppliers = len(raw_supplier_list)
        excluded_count = len(st.session_state.active_filters.get("excluded_suppliers", []))
        included_count = total_suppliers - excluded_count

        spacer_left, col_btn1, col_btn2, mid_spacer, metric_col, spacer_right = st.columns([0.4, 2.2, 2.2, 3, 2, 0.2], gap="medium")

        with col_btn1:
            st.markdown("<div style='padding-top: 1.2rem;'></div>", unsafe_allow_html=True)
            st.button(
                "🛜 Proceed to ST Scope", 
                type="primary", 
                use_container_width=True, 
                disabled=st.session_state.locked, 
                on_click=handle_proceed, args=(orch,))
            
        with col_btn2:
            st.markdown("<div style='padding-top: 1.2rem;'></div>", unsafe_allow_html=True)
            st.button(
                "🗑️ Reset All Filters", 
                type="secondary", 
                use_container_width=True, 
                on_click=handle_reset)

        with metric_col:
            st.metric(
                label="Suppliers in Scope", 
                value=included_count, 
                delta=f"-{excluded_count} excluded" if excluded_count > 0 else None,
                delta_color="inverse" 
            )