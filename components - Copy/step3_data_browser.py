"""Page 3 – Data Browser: DB schema/counts + Jobs + Suppliers in one view."""
import streamlit as st
import pandas as pd
from utils.mapper import render_strategy_map
from utils.display import color_savings_by_rank

def render_data_browser(orch):
    st.header("Data Browser")

    # ==========================================
    # 0. Database Metadata (Row Counts)
    # ==========================================
    with st.expander("📊 Database Row Counts", expanded=False):
        try:
            # Notice we use orch.session here!
            counts_data = [
                {"Table": "SWA_SITE_PROJECTS", "Total Rows": orch.session.table("SWA_SITE_PROJECTS").count()},
                {"Table": "SWA_SUPPLIERS", "Total Rows": orch.session.table("SWA_SUPPLIERS").count()},
                {"Table": "SWA_JOB_SP_MATRIX", "Total Rows": orch.session.table("SWA_JOB_SP_MATRIX").count()},
                {"Table": "SP_SWA_WAREHOUSE_LOCATION_MASTER", "Total Rows": orch.session.table("ETL_SP_SWA_WAREHOUSE_LOCATION_MASTER").count()}
            ]
            st.dataframe(pd.DataFrame(counts_data), hide_index=True, use_container_width=True)
        except Exception as e:
            st.warning(f"Could not load table metadata: {e}")

    # ==========================================
    # 1a. ASP Warehouse Locations (ETL_SP_SWA_WAREHOUSE_LOCATION_MASTER)
    # ==========================================
    st.subheader("ASP Warehouse Locations")
    wh_df = orch.fetch_dynamic_table("ETL_SP_SWA_WAREHOUSE_LOCATION_MASTER", limit_rows=0)
    
    if wh_df.empty:
        st.info("No warehouse locations found in ETL_SP_SWA_WAREHOUSE_LOCATION_MASTER.")
    else:
        st.dataframe(wh_df, 
                    # Only shows these columns, in this order
                    column_order=["SUPPLIERNAME", "MUSID", "MARKET", "FULLADDRESS", "ADDRESS",
                                  "CITY", "STATE", "ZIP", "LATITUDE", "LONGITUDE", "CONTACTINFORMATION"], 
                    use_container_width=True)

    st.divider()
    
    # ==========================================
    # 1b. Site Projects (SWA_SITE_PROJECTS)
    # ==========================================
    st.subheader("Site Projects")
    
    # We call the method directly from the passed orch object
    projects_df = orch.fetch_dynamic_table("SWA_SITE_PROJECTS", limit_rows=0)
    filter_projects = []
    
    if projects_df.empty:
        st.info("No projects found in SWA_SITE_PROJECTS.")
    else:
        if 'START_DATE' in projects_df.columns:
            min_d = projects_df["START_DATE"].min()
            max_d = projects_df["START_DATE"].max()
            
            c1, c2, c3 = st.columns([1, 1, 1])
            with c1:
                date_from = st.text_input("Start date from", value=str(min_d), key="db_date_from")
            with c2:
                date_to = st.text_input("Start date to", value=str(max_d), key="db_date_to")
            with c3:
                limit = st.number_input("Max rows", 10, 5000, 500, 50, key="db_job_limit")
            
            try:
                mask = (pd.to_datetime(projects_df['START_DATE']) >= pd.to_datetime(date_from)) & \
                       (pd.to_datetime(projects_df['START_DATE']) <= pd.to_datetime(date_to))
                filtered_projects = projects_df.loc[mask].head(int(limit))
                st.dataframe(filtered_projects, 
                             column_order=["PROJECT_ID", "START_DATE", "START_DATE_A", "DURATION_DAYS", 
                                           "PROJECT_TEMPLATE", "SP_MARKET", "SITE_NAME", "SP_ASSIGNED", 
                                           "CUSTOMER", "STREET_ADDRESS", "CITY", "STATE", "ZIP_CODE",
                                           "COUNTY", "COUNTRY", "SITE_LATITUDE", "SITE_LONGITUDE"],
                             use_container_width=True)
            except Exception as e:
                st.warning(f"Date filtering issue: {e}")
                st.dataframe(projects_df.head(int(limit)), use_container_width=True)
        else:
            limit = st.number_input("Max rows", 10, 5000, 500, 50, key="db_job_limit_no_date")
            st.dataframe(projects_df.head(int(limit)),
                         column_order=["PROJECT_ID", "START_DATE", "START_DATE_A", "DURATION_DAYS", 
                                       "PROJECT_TEMPLATE", "SP_MARKET", "SITE_NAME", "SP_ASSIGNED", 
                                       "CUSTOMER", "STREET_ADDRESS", "CITY", "STATE", "ZIP_CODE",
                                       "COUNTY", "COUNTRY", "SITE_LATITUDE", "SITE_LONGITUDE"],
                         use_container_width=True)

    st.divider() 

    # ==========================================
    # 2. Suppliers (SWA_SUPPLIERS)
    # ==========================================
    st.subheader("Suppliers")
    sup_df = orch.fetch_dynamic_table("SWA_SUPPLIERS", limit_rows=0)
    
    if sup_df.empty:
        st.info("No suppliers found in SWA_SUPPLIERS.")
    else:
        st.dataframe(sup_df, use_container_width=True)

    st.divider()

    # ==========================================
    # 3. SP Job Matrix (SWA_JOB_SP_MATRIX)
    # ==========================================
    st.subheader("Job / Supplier Matrix")
    matrix_df = orch.fetch_dynamic_table("SWA_JOB_SP_MATRIX", limit_rows=1000) 
    
    if matrix_df.empty:
        st.info("No matrix data found in SWA_JOB_SP_MATRIX.")

        st.markdown("---")
        
        #  Display the Map
        st.markdown("#### 🗺️ Geographic Bidding Landscape")
        st.info("No job data to map.")
    else:
        st.dataframe(matrix_df, use_container_width=True)

    # ==========================================
    # 4. Map View of Job Matrix
    # ==========================================

        st.markdown("---")
        
        #  Display the Map
        st.markdown("#### 🗺️ Geographic Bidding Landscape")
        
        # Call the map function and pass it the exact same dataframe you just put in the table!
        render_strategy_map(filtered_projects, matrix_df)

        st.markdown("---")
        st.subheader("Solver Table")
        
        solver_df = orch.fetch_dynamic_table("SWA_SOLVER", limit_rows=1000) 
        display_df = solver_df.drop(columns=['CURRENT_ASSIGN_MUSID', 'SP_MUSID', 'QUALITY_SCORE'], errors='ignore')
        
        if display_df.empty:
            st.info("No matrix data found in SWA_SOLVER.")
        else:    
            # Drop the column first, then style the rest
            display_df = display_df.drop(columns=["RECOM_ASSIGN_SP"])
            
            styled = display_df.style.apply(color_savings_by_rank, axis=1).format(
                {"BCR_COST": "${:,.0f}", "SAVING_FR_CURR": "${:,.0f}", "SUPPLIER_COST": "${:,.0f}", 
                 "CURR_ASSIGN_COST": "${:,.0f}", "SP_RANK": "{:.0f}", "DRIVE_MILES": "{:.2f}"}
            )
            st.dataframe(styled)
