import streamlit as st
import pandas as pd
import numpy as np
import re
from utils.session_tables import calculate_octile_road_miles
from snowflake.snowpark import Session
from snowflake.snowpark.exceptions import SnowparkSQLException
from utils.testing_utils import DevSimTools

class DataOrchestrator:
    def __init__(_self, session):
        _self.session = session
        _self.filters = {} 
        _self.column_map = {
            "customers": "CUSTOMER", "regions": "REGION", 
            "sourcing_managers": "SOURCING MANAGER NAME", "markets": "MARKET", 
            "price_matrix": "PROJECT NAME", "suppliers": "SUPPLIER"
        }
                    
        # Initialize temp tables
        _self.create_site_projects_temp_table()
        _self.create_suppliers_temp_table()
        _self.create_jobMatrix_temp_table()
        
    def sync_filters(_self, new_filters):
        _self.filters = new_filters

    def apply_drive_distances(self, matrix_df, projects_df, suppliers_df):       
        if matrix_df.empty or projects_df.empty or suppliers_df.empty:
            return matrix_df

        # 1. Base Coordinates
        site_coords = projects_df.copy()
        if 'PROJECT ID' in site_coords.columns and 'PROJECT_ID' not in site_coords.columns:
            site_coords = site_coords.rename(columns={'PROJECT ID': 'PROJECT_ID'})
            
        site_coords = site_coords[['PROJECT_ID', 'LOCATION LATITUDE', 'LOCATION LONGITUDE']]
        site_coords = site_coords.rename(columns={'LOCATION LATITUDE': 'SITE_LAT', 'LOCATION LONGITUDE': 'SITE_LON'})
        
        # Supplier Coordinates (Including Location Details for Step 3 UI)
        wh_coords = suppliers_df[['MUSID', 'WH_ADDRESS', 'WH_LATITUDE', 'WH_LONGITUDE']].copy()

        # 2. Add a unique ID to track the original matrix rows
        matrix_df['TEMP_ROW_ID'] = matrix_df.index 

        # 3. Merge Sites
        merged_df = matrix_df.merge(site_coords, on='PROJECT_ID', how='left')
        
        # 4. Merge Warehouses (Explosion)
        exploded_df = merged_df.merge(wh_coords, on='MUSID', how='left')

        # 5. Clean coordinates for math
        for col in ['SITE_LAT', 'SITE_LON', 'WH_LATITUDE', 'WH_LONGITUDE']:
            exploded_df[col] = pd.to_numeric(exploded_df[col], errors='coerce').fillna(0.0)

        # 6. 🟢 NEW VECTORIZED MATH: Octile Road Distance
        exploded_df['DRIVE_DISTANCE'] = calculate_octile_road_miles(
            exploded_df['WH_LATITUDE'], exploded_df['WH_LONGITUDE'], 
            exploded_df['SITE_LAT'], exploded_df['SITE_LON']
        )
        
        mask_missing = (exploded_df['WH_LATITUDE'] == 0.0) | (exploded_df['SITE_LAT'] == 0.0)
        exploded_df.loc[mask_missing, 'DRIVE_DISTANCE'] = np.nan

        # 7. Find the index of the minimum distance for each original row
        best_idx = exploded_df.groupby('TEMP_ROW_ID')['DRIVE_DISTANCE'].idxmin()
        best_rows_df = exploded_df.loc[best_idx.dropna()].copy()
        
        # 8. Map the winning distances AND location details back to the matrix
        # Drop the columns from the base matrix if they already exist, 
        #   so the merge doesn't create _x and _y suffixes.
        cols_to_drop = [c for c in ['DRIVE_DISTANCE', 'WH_ADDRESS', 'WH_LATITUDE', 'WH_LONGITUDE'] if c in matrix_df.columns]
        matrix_clean_for_merge = matrix_df.drop(columns=cols_to_drop)
        
        final_matrix = matrix_df.merge(
            best_rows_df[['TEMP_ROW_ID', 'DRIVE_DISTANCE', 'WH_ADDRESS', 'WH_LATITUDE', 'WH_LONGITUDE']], 
            on='TEMP_ROW_ID', 
            how='left'
        )

        # 9. Cleanup the safety net
        final_matrix = final_matrix.drop(columns=['TEMP_ROW_ID'])
        
        return final_matrix
    
    # --- DDL SECTION (Table Creation) ---
     
    def create_site_projects_temp_table(_self) -> bool:
        """
        Creates a session-scoped temporary table to hold the finalized scope
        for the optimization engine. Automatically drops when the session ends.
        """
        # Define the DDL query with exact Snowflake data types
        ddl_query = """
        CREATE OR REPLACE TRANSIENT TABLE SWA_SITE_PROJECTS (
            PROJECT_ID VARCHAR PRIMARY KEY,
            START_DATE DATE,
            START_DATE_A DATE,
            DURATION_DAYS NUMBER,
            PROJECT_TEMPLATE VARCHAR,
            SP_MARKET VARCHAR,
            SITE_NAME VARCHAR,
            SP_ASSIGNED VARCHAR,
            SP_MUSID_ASSIGNED VARCHAR,
            CUSTOMER VARCHAR,
            STREET_ADDRESS VARCHAR,
            CITY VARCHAR,
            STATE VARCHAR,
            ZIP_CODE VARCHAR,
            COUNTY VARCHAR,
            COUNTRY VARCHAR,
            SITE_LATITUDE FLOAT,
            SITE_LONGITUDE FLOAT
        )
        """
        
        try:
            # Execute the query. We use .collect() instead of .to_pandas() 
            # because DDL commands don't return a dataframe.
            _self.session.sql(ddl_query).collect()
            
            # Optional: Log success or print to Streamlit during development
            #st.success("✅ Temporary table 'site_projects' initialized.")
            return True
            
        except Exception as e:
            st.error(f"🚨 Create site_projects temp table: {e}")
            return False


    ### Convert creation of temp table to stored proc and call from here
    def create_suppliers_temp_table(_self) -> bool:
        """
        Creates a session-scoped temporary table to hold the finalized scope
        for the optimization engine. Automatically drops when the session ends.
        """
        # Define the DDL query with exact Snowflake data types
        ddl_query = """
        CREATE OR REPLACE TRANSIENT TABLE SWA_SUPPLIERS (
            MUSID VARCHAR PRIMARY KEY,
            SP_NAME VARCHAR, 
            SP_MARKET VARCHAR,
            CUSTOMER VARCHAR,
            CREW_CAPACITY FLOAT,
            CREW_SCOPE VARCHAR,
            ALLOCATION_COMPLIANCE FLOAT,
            WH_ADDRESS VARCHAR,
            WH_LATITUDE FLOAT,
            WH_LONGITUDE FLOAT,
            ASSIGNED_SITE_COUNT FLOAT,
            ALLOCATION_QTR VARCHAR,
            CURRENT_MS FLOAT,
            SMS_PCT FLOAT,
            WEEK NUMBER,
            YEAR NUMBER
        )
        """
        
        try:
            # Execute the query. We use .collect() instead of .to_pandas() 
            # because DDL commands don't return a dataframe.
            _self.session.sql(ddl_query).collect()
            
            # Optional: Log success or print to Streamlit during development
            #st.success("✅ Temporary table 'suppliers' initialized.")
            return True
            
        except Exception as e:
            st.error(f"🚨 Create suppliers temp table: {e}")
            return False
  
    def create_jobMatrix_temp_table(_self) -> bool:
        """
        Creates a session-scoped temporary table to hold the finalized scope
        for the optimization engine. Automatically drops when the session ends.
        """
        # Define the DDL query with exact Snowflake data types
        ddl_query = """
         CREATE OR REPLACE TRANSIENT TABLE SWA_JOB_SP_MATRIX (
             PROJECT_ID VARCHAR,
             MUSID VARCHAR,
             SP_NAME VARCHAR,
             SP_MARKET VARCHAR,
             CUSTOMER VARCHAR,
             BCR_COST FLOAT,    -- Comes from Price Matrix
             SP_COST FLOAT,      -- Calculated from BOM data
             DRIVE_DISTANCE FLOAT,
             QUALITY_SCORE FLOAT
        )
        """
        
        try:
            # Execute the query. We use .collect() instead of .to_pandas() 
            # because DDL commands don't return a dataframe.
            _self.session.sql(ddl_query).collect()
            
            # Optional: Log success or print to Streamlit during development
            #st.success("✅ Temporary table 'job_sp_matrix' initialized.")
            return True
            
        except Exception as e:
            st.error(f"🚨 Failed to create job matrix temp table: {e}")
            return False
 
    def create_swa_solver_temp_table(_self) -> bool:
        """
        Creates a session-scoped temporary table to hold the finalized scope
        for the optimization engine. Automatically drops when the session ends.
        """
        # Define the DDL query with exact Snowflake data types
        ddl_query = """
        CREATE OR REPLACE TRANSIENT TABLE SWA_SOLVER (
            PROJECT_ID VARCHAR,
            CUSTOMER_SITE_NAME VARCHAR,
            CX_START_DATE DATE,
            CURRENT_ASSIGN_SP VARCHAR,
            CURRENT_ASSIGN_MUSID NUMBER,
            SUPPLIER VARCHAR,
            SP_MUSID VARCHAR,
            BCR_COST FLOAT,
            CURR_ASSIGN_COST FLOAT,
            SUPPLIER_COST FLOAT,
            SAVING_FR_CURR FLOAT,
            SP_RANK NUMBER,
            DRIVE_DISTANCE FLOAT,
            RECOM_ASSIGN_SP BOOLEAN DEFAULT FALSE,
            FINAL_ASSIGN_SP BOOLEAN DEFAULT FALSE
        )
        """
        
        try:
            # Execute the query. We use .collect() instead of .to_pandas() 
            # because DDL commands don't return a dataframe.
            _self.session.sql(ddl_query).collect()
            
            # Optional: Log success or print to Streamlit during development
            #st.success("✅ Temporary table 'swa_solver' initialized.")
            return True
            
        except Exception as e:
            st.error(f"🚨 Create swa_solver temp table: {e}")
            return False
            
    def get_smart_options(_self, df, current_filters, target_key):
        temp_df = df.copy()
        
        for filter_key, values in list(current_filters.items()):
            # 1. Skip the target key or None values
            if filter_key == target_key or values is None:
                continue
                
            # 2. Shield against DataFrames BEFORE checking for "All"
            if isinstance(values, pd.DataFrame):
                continue
                
            # 3. Skip "All" (This is now perfectly safe because DataFrames are gone)
            if values == "All":
                continue
            
            # 4. Skip numbers and booleans (fix for the years/weeks)
            if isinstance(values, (int, float, bool)):
                continue
                
            # 5. Skip empty lists/strings
            if len(values) == 0:
                continue
                
            # Handle the Date Range (Special Case)
            if filter_key == "date_range" and len(values) == 2:
                start, end = values
                temp_df = temp_df[(temp_df["LOAD_DATE"] >= start) & (temp_df["LOAD_DATE"] <= end)]
            
            # Handle Standard Column Filters
            elif filter_key in _self.column_map:
                col = _self.column_map[filter_key]
                 
                if col in temp_df.columns:
                    temp_df = temp_df[temp_df[col].isin(values)]
        
        # Final safety check for the target key
        target_col = _self.column_map.get(target_key)
        if not target_col or target_col not in temp_df.columns:
            return []
            
        return sorted(temp_df[target_col].unique().tolist())
    
    def apply_final_filters(_self, df, filters):
        temp_df = df.copy()
        dr = filters.get("date_range")
        if dr and len(dr) == 2:
            temp_df = temp_df[(temp_df['LOAD_DATE'] >= dr[0]) & (temp_df['LOAD_DATE'] <= dr[1])]
        for key, col in _self.column_map.items():
            if filters.get(key):
                temp_df = temp_df[temp_df[col].isin(filters[key])]
        return temp_df
    
    def apply_dynamic_filters(_self, raw_df, filter_dict):
        """
        Takes a raw Pandas DataFrame and a dictionary of column-to-list mappings.
        Returns a dynamically filtered DataFrame.
        """
        # 🛡️ GUARD: If there's no data, just return it safely
        if raw_df is None or raw_df.empty:
            return raw_df
            
        # Create a safe copy
        filtered_df = raw_df.copy()
        
        # Apply filters dynamically
        for column_name, selected_items in filter_dict.items():
            if selected_items and len(selected_items) > 0:
                filtered_df = filtered_df[filtered_df[column_name].isin(selected_items)]
                
        return filtered_df
 
    # --- FETCH SECTION (Data Retrieval) ---
    
    @st.cache_data(ttl=600)
    def fetch_price_matrix(_self):
        query = """
            SELECT "MARKET", "SUPPLIER", "ROUND", "CUSTOMER", "MUSID", --"REGION",
                    "PROJECT NAME", "CATEGORY", DATE("LOAD DATE TIME") as LOAD_DATE,
                    TRY_CAST("VALUE" AS FLOAT) as VALUE, "ROC", "BCR", "SOURCING MANAGER NAME"
            FROM NTW_DM_USR.VW_SP_SUPPLIER_SCORECARD_PRICE_MATRIX
            WHERE "LOAD DATE TIME" IS NOT NULL
            ORDER BY "LOAD DATE TIME" DESC
        """
            
        df = _self.session.sql(query).to_pandas()
        for col in _self.column_map.values():
            if col in df.columns:
                df[col] = df[col].fillna('N/A').astype(str)
                
        df['LOAD_DATE'] = pd.to_datetime(df['LOAD_DATE']).dt.date  
        
        return df
    
    ## Sitetracker Data
    @st.cache_data(ttl=600)
    def fetch_st_data(_self):
        filters = st.session_state.active_filters
        
        # 1. Clean the incoming filter data (Force Upper + Strip)
        # Sitetracker data is almost always UPPERCASE in the warehouse
        cust_val = str(filters["customers"][0]).strip().upper()
        
        # Markets: ['North Texas', 'South Texas'] -> "'NORTH TEXAS', 'SOUTH TEXAS'"
        market_list = [str(m).strip().upper() for m in filters["markets"]]
        formatted_market = ", ".join([f"'{m}'" for m in market_list])

        # --- NEST-SAFE EMERGENCY DIAGNOSTIC ---
        st.info("🕵️ DATABASE VS UI AUDIT (Running...)")
        # Use a container or just direct writes to avoid the nesting error
        with st.container():
            # 1. Show what the UI is sending
            st.write(f"**UI Customer:** `{filters['customers'][0]}`")
            st.write(f"**UI Markets:** `{filters['markets']}`")
        
            # 2. Query the database for what is ACTUALLY in those columns
            # We use a very loose query here to see the "Ground Truth"
            test_sql = f"""
                SELECT DISTINCT CUSTOMER, "SP MARKET" 
                FROM NTW_DM_USR.O22200_PV_ST_PROJECT_MASTER
                WHERE UPPER(TRIM(CUSTOMER)) = '{str(filters['customers'][0]).strip().upper()}'
                LIMIT 20
            """
            try:
                db_check = _self.session.sql(test_sql).to_pandas()
                if db_check.empty:
                    st.warning("🚨 The Database returned 0 rows for that Customer name. Is the Customer name correct in the DB?")
                else:
                    st.write("**Top 20 combinations found in the Database for this Customer:**")
                    st.dataframe(db_check, use_container_width=True)
            except Exception as e:
                st.error(f"Diagnostic Query Failed: {e}")
        # --------------------------------------       
        base_query = f"""
            SELECT 
                "PROJECT ID", "PROJECT TEMPLATE NAME", "SP MARKET", "P/C/S", 
                "CUST FCST WEEK CONSTRUCTION START", "CX CYCLE TIME ESTIMATE", "CONSTRUCTION START (A)",
                "CONSTRUCTION START (F)", CUSTOMER, "SITE NAME", "SITE RECORD ID",
                "CUSTOMER SITE ID", "CUSTOMER SITE NAME", "STREET ADDRESS", "ANTENNA AND LINE INSTALLATION START (F)",
                "STREET ADDRESS 2", CITY, STATE, "ZIP CODE", COUNTY, COUNTRY, 
                "LOCATION LATITUDE", "LOCATION LONGITUDE", "CUSTOMER PROJECT ID", "SP-CIVIL SUPPLIER NUMBER", 
                "SP-ANTENNA & LINE INSTALL"
            FROM NTW_DM_USR.O22200_PV_ST_PROJECT_MASTER
            WHERE "PROJECT ID" IS NOT NULL
              AND "P/C/S" != 'Child' AND "P/C/S" != 'Standalone (EFI Only)'
              AND UPPER(TRIM(CUSTOMER)) = '{cust_val}'
              AND UPPER(TRIM("SP MARKET")) IN ({formatted_market})
        """
        
        # 3. Diagnostic Debug (Temporary)
        # This will show you the exact query before it runs
        # st.code(base_query, language="sql")
    
        try:
            df2 = _self.session.sql(base_query).to_pandas()
            if not df2.empty:
                # Force all column headers to upper for consistent Pandas indexing
                df2.columns = [c.upper() for c in df2.columns]
                # Convert dates safely
                df2["CONSTRUCTION START (F)"] = pd.to_datetime(df2["CONSTRUCTION START (F)"], errors='coerce')
            return df2
        except Exception as e:
            st.error(f"Error fetching Step 2 data: {e}")
            return pd.DataFrame()

    ###
    ### Fetches BOM data from ESR for the specified project/suppliers
    ###  and calculates the prices per site - Budget, SP Quote, and SP Actual
    ###
    def fetch_ESR_data(_self):
        # Retrieve the Price Matrix from session state
        pm_data = st.session_state.get("df1_filtered")

        # 🛡️ GUARD: Ensure data exists before running query
        if pm_data is None or pm_data.empty:
            st.error("⚠️ Step 1 Price Matrix data is missing.")
            return None

        # 1. Pull the Customer and Market lists from your UI filters
        filters = st.session_state.get("active_filters", {})
        customers = filters.get("customers", [])
        markets = filters.get("markets", [])
        
        # 2. Extract unique Project Template directly from the filtered DataFrame.
        #project = pm_data['PROJECT NAME'].dropna().unique().tolist()
        project = pm_data['PROJECT NAME'].dropna().astype(str).str.strip().unique().tolist()

        # 3. Helper function: Converts Python lists into SQL syntax ('Item1', 'Item2')
        # It also safely escapes apostrophes (like in "O'Hare") so SQL doesn't crash
        def format_for_sql(val_list):
            if not val_list:
                return "''" # Prevents syntax errors if a list is empty
            #return ", ".join(["'" + str(v).replace("'", "''") + "'" for v in val_list])
            return ", ".join(["'" + str(v).replace("'", "''") + "'" for v in val_list if v is not None])

        # 4. Format the strings
        customer_sql = format_for_sql(customers)
        market_sql = format_for_sql(markets)
        project_sql = format_for_sql(project)
        
        # 5. The Aggregated "Pushdown Compute" Query
        #  This returns ALL bids per project.  Meaning all the suppliers that bid on the work, not just the one that got assigned
        #  It's needed for the solver table.  Next, we will narrow it down for the Job Matrix table.
        base_query = f"""
                WITH project_winner AS (
                    SELECT 
                        bom.SITEPROJECTNAME AS PROJECT_ID,
                        MAX(bom.JOBASSIGNEDASPNAME) AS CURRENT_ASSIGN_SP
                    FROM NTW_DM_USR.O25450_PV_ESR_BILLOFMATERIALITEMS bom
                    GROUP BY bom.SITEPROJECTNAME
                )
                SELECT 
                    bom.SITEPROJECTNAME AS PROJECT_ID,
                    pw.CURRENT_ASSIGN_SP,
                    sc.SUPPLIER,
                    sc.MUSID,
                    sc.CUSTOMER,             
                    sc.MARKET,
                    SUM(sc.BCR * bom.BOMITEMQUANTITY) AS BCR_COST,
                    SUM(sc.VALUE * bom.BOMITEMQUANTITY) AS SUPPLIER_COST,
                    COUNT(DISTINCT bom.ERICSSONPRODUCTNUMBER) AS ITEM_COUNT,
                    SUM(bom.BOMITEMQUANTITY) AS TOTAL_QUANTITY
                FROM NTW_DM_USR.O25450_PV_ESR_BILLOFMATERIALITEMS bom
                JOIN NTW_DM_USR.VW_SP_Supplier_ScoreCard_Price_Matrix sc
                    ON bom.ERICSSONPRODUCTNUMBER = sc.FPP
                LEFT JOIN project_winner pw
                    ON bom.SITEPROJECTNAME = pw.PROJECT_ID
                WHERE sc.CUSTOMER IN ({customer_sql}) 
                  AND sc.MARKET IN ({market_sql}) 
                  AND sc."PROJECT NAME" IN ({project_sql})
                GROUP BY sc.CUSTOMER, sc.MARKET, bom.SITEPROJECTNAME, pw.CURRENT_ASSIGN_SP, sc.SUPPLIER, sc.MUSID
                ORDER BY sc.CUSTOMER, sc.MARKET, bom.SITEPROJECTNAME, sc.SUPPLIER;
            """
        
        # --- 🟢 THE ULTIMATE SQL X-RAY ---
        #with st.container(border=True):
        #    st.markdown("🕵️ DEBUG: Inspect the SQL Inputs & Query")
        #    if customer_sql == "''" or market_sql == "''" or project_sql == "''":
        #        st.error("🚨 STOP! One of the filter lists is completely empty!")
        #        
        st.markdown("**The BOM Final Compiled Query:**")
        st.code(base_query, language="sql")
        # ---------------------------------
        
        try:
            role = _self.session.sql("SELECT CURRENT_ROLE(), CURRENT_USER()").to_pandas()
            st.write("App is querying as:", role)

            # Execute and standardize headers
            esr_df = _self.session.sql(base_query).to_pandas()
            
            if not esr_df.empty:
                esr_df.columns = [c.upper() for c in esr_df.columns]
            
            # Ensure the dictionary exists in session state before assigning
            if "active_filters" not in st.session_state:
                st.session_state["active_filters"] = {}
                
            # Save directly to session state (This is our "Cache"!)
            st.session_state["active_filters"]["BOM_Raw"] = esr_df
            st.info(f"Sent ESR {len(esr_df)} records.") 

            return esr_df
            
        except Exception as e:
            st.error(f"🚨 Error fetching ESR/BOM data2: {e}")
            return pd.DataFrame()   
            
    ###
    ### Fetches crew capacity based on the locked filters and 
    ###  the date boundaries calculated from Sitetracker projects.
    ###
    def fetch_crew_data(_self):
        # Pull the Source of Truth from state
        filters = st.session_state.active_filters
 
        # Build the query using internal filters
        base_query = f"""
            SELECT DISTINT_KEY, CUSTOMER, "MARKET", "SUPPLIER MUS ID", PROGRAM, "SUPPLIER RENAME",
                   "CREW SCOPE", CREWS, CONFIDENCE, WEEK, YEAR, "DATE", "SUPPLIER TYPE"
            FROM NTW_DM_USR.O22002_PV_IMPARTX_SIM_CREW_CAPACITY_DEMAND
            WHERE DISTINT_KEY IS NOT NULL
            AND CUSTOMER = '{filters["customers"][0]}'
            AND "MARKET" IN ({", ".join([f"'{m}'" for m in filters["markets"]])})
            AND ("SUPPLIER TYPE" = 'Committed' OR "SUPPLIER TYPE" = 'Supplier')
            """
        try:
            # 1. Checkpoint: The Raw Result
            snow_df = _self.session.sql(base_query)
            # This is cheap and tells us if Snowflake actually sent anything
            st.write(f"DEBUG 1: Snowflake Result Row Count: {snow_df.count()}") 

            # 2. Checkpoint: The Pandas Conversion
            df = snow_df.to_pandas()
            st.write(f"DEBUG 2: Pandas DF Row Count (Pre-Clean): {len(df)}")
            if len(df) > 0:
                st.write("DEBUG 3: First 3 rows of Raw Data:")
                st.write(df.head(3))

            # --- Now the cleaning starts ---
            if not df.empty:
                df.columns = [c.upper() for c in df.columns]
                st.write(f"DEBUG 4: Columns found: {df.columns.tolist()}")

                # 1. Clean the 'W' out of WEEK
                if "WEEK" in df.columns:
                    df["WEEK"] = df["WEEK"].astype(str).str.replace('W', '', case=False).str.strip()
                    df["WEEK"] = pd.to_numeric(df["WEEK"], errors='coerce')
            
                # 2. Coerce YEAR to numeric (turns junk text into NaN)
                df["YEAR"] = pd.to_numeric(df["YEAR"], errors='coerce')
            
                st.write(f"DEBUG 5: Null Years before drop: {df['YEAR'].isna().sum()}")

                # 3. DROP the bad rows FIRST (While they are still NaN)
                df = df.dropna(subset=["YEAR", "WEEK"])
                
                # 4. DEFENSIVE CLEANING: Force to Int (removes .0) then to String
                df["YEAR"] = df["YEAR"].astype(int).astype(str)
                df["WEEK"] = df["WEEK"].astype(int).astype(str)

                # 5. DEFENSIVE MATH: Guarantee usable numbers!
                if "CREWS" in df.columns:
                    df["CREWS"] = pd.to_numeric(df["CREWS"], errors='coerce').fillna(0.0)
                if "CONFIDENCE" in df.columns:
                    df["CONFIDENCE"] = pd.to_numeric(df["CONFIDENCE"], errors='coerce').fillna(0.0)

                # 6. 🟢 DEFENSIVE KEYS: Force perfectly clean strings for the downstream merge!
                if "SUPPLIER MUS ID" in df.columns:
                    df["SUPPLIER MUS ID"] = df["SUPPLIER MUS ID"].astype(str).str.replace(r'\.0$', '', regex=True).str.strip().str.upper()
                if "SUPPLIER RENAME" in df.columns:
                    df["SUPPLIER RENAME"] = df["SUPPLIER RENAME"].astype(str).str.strip().str.upper()

                st.write(f"DEBUG 6: Final Count after dropna: {len(df)}")
                
            return df
        
        except Exception as e:
            st.error(f"Error fetching Crew data: {e}")
            # Log the query to help debug if the date format in the table is inconsistent
            st.write(base_query) 
            return pd.DataFrame()
    
    ###
    ### Fetches Supplier Warehouse Location(s) 
    ###
    def fetch_wh_data(_self):
        filters = st.session_state.active_filters

        base_query = f"""
            SELECT "MUSID", "SUPPLIERNAME", MARKET, "FULLADDRESS", ADDRESS,  
                   CITY, STATE, ZIP, LATITUDE, LONGITUDE
            FROM NTW_DM.ETL_SP_SWA_WAREHOUSE_LOCATION_MASTER
            WHERE "MUSID" IS NOT NULL
            AND "MARKET" IN ({", ".join([f"'{m}'" for m in filters["markets"]])})
            """

        try:
            wh_df = _self.session.sql(base_query).to_pandas()
            
            if not wh_df.empty:
                # 🟢 Standardize column names to UPPERCASE
                wh_df.columns = [c.upper() for c in wh_df.columns]
                
                # 🟢 Trim whitespace from join keys
                # This is critical for reliable Pandas merging!
                wh_df['MUSID'] = wh_df['MUSID'].astype(str).str.strip()
                wh_df['MARKET'] = wh_df['MARKET'].astype(str).str.strip()
                
            return wh_df
            
        except Exception as e:
            st.error(f"Error fetching Warehouse Location data: {e}")
            st.write(base_query) 
            return pd.DataFrame()
   
    
    
    ###
    ###  Get the allocated market share for all suppliers
    ###
    def fetch_sp_mkt_share(_self, local_projects_df, local_suppliers_df):
        
        try:
            # 1. Grab clean table from RAM
            projects_df = local_projects_df.copy()
            suppliers_df = local_suppliers_df.copy()
            
            if projects_df.empty or suppliers_df.empty:
                st.error("⚠️ Missing upstream data. Ensure Projects and Suppliers are generated first.")
                return False

            # Define target_df early so we can extract data from it!
            target_df = projects_df.copy()

            # 2. Grab UI filters
            customers = st.session_state.active_filters.get("customers", [])
            markets = st.session_state.active_filters.get("markets", [])
            date_range = st.session_state.active_filters.get("date_range", ())
            crew_year = st.session_state.active_filters.get("crew_target_year", []) 
            crew_week = st.session_state.active_filters.get("crew_target_week", [])
            crew_scope =  st.session_state.active_filters["selected_crew_scope"] 
        
            #st.write("DEBUG customers type/value:", customers)
            #st.write("DEBUG markets type/value:", markets)

            # Extract targets from their respective tables
            templates = target_df['PROJECT_TEMPLATE'].dropna().unique().tolist()
            musid_list = suppliers_df['MUSID'].dropna().unique().tolist()

            # DATE MATH: Convert UI Date Range to 'YYYY-Q#' format
            qtr_list = []
            #if len(date_range) == 2:
            #    start_date, end_date = pd.to_datetime(date_range[0]), pd.to_datetime(date_range[1])
            #    qtr_list = pd.period_range(start=start_date, end=end_date, freq='Q').strftime('%Y-Q%q').tolist()
            if crew_year and crew_week:
                crew_week = int(crew_week)
                crew_year = int(crew_year)
                qtr_num = ((crew_week - 1) // 13) + 1
                qtr_list = [f"{crew_year}-Q{qtr_num}"]
            
            # 3. 🟢 THE DYNAMIC WHERE CLAUSE BUILDER
            where_clauses = []
            
            # Only append rules if the list actually has items in it
            if customers:
                cust_str = "'" + "','".join([str(c).replace("'", "''") for c in customers]) + "'"
                where_clauses.append(f"CUSTOMER IN ({cust_str})")
                
            if markets:
                mkt_str = "'" + "','".join([str(m).replace("'", "''") for m in markets]) + "'"
                where_clauses.append(f"MARKET IN ({mkt_str})")
                
            if templates:
                tmp_str = "'" + "','".join([str(t).replace("'", "''") for t in templates]) + "'"
                where_clauses.append(f"\"PROJECT TEMPLATE\" IN ({tmp_str})")
                
            if musid_list:
                musid_str = "'" + "','".join([str(m).replace("'", "''") for m in musid_list]) + "'"
                where_clauses.append(f"MUSID IN ({musid_str})")
                
            if qtr_list:
                qtr_str = "'" + "','".join(qtr_list) + "'"
                where_clauses.append(f"(\"ALLOCATION QTR\" IN ({qtr_str}) OR \"ALLOCATION QTR\" IS NULL)")

            if crew_scope:
                if crew_scope == 'TOWER CX':
                    alloc_type = "''Antenna and Lines'', ''Antenna and Line''"
                elif crew_scope == 'CRAN_ODC':
                    alloc_type = "''Outdoor Small Cells''"
                else:
                    alloc_type = None
                
                if alloc_type:
                    where_clauses.append(f"(\"ALLOCATION TYPE\" IN ({alloc_type}) OR \"ALLOCATION TYPE\" IS NULL)")
        
            # Always apply the hardcoded exclusion rules
            where_clauses.append("\"P/C/S\" != 'Child'")
            where_clauses.append("\"P/C/S\" != 'Standalone (EFI Only)'")

            # Assemble the final SQL snippet
            where_sql = ""
            if where_clauses:
                where_sql = "WHERE " + " AND ".join(where_clauses)

            # Query Snowflake (Pushdown Compute Engine)
            # Notice we just drop {where_sql} right in.
            alloc_query = f"""
                SELECT CUSTOMER, MARKET, "ALLOCATION TYPE", SUPPLIER, MUSID,
                    "PROJECT TEMPLATE", "ALLOCATION QTR", 
                    SUM("ALLOCATED MARKET SHARE") AS CURRENT_MS,
                    SUM("ASSIGNED SITES") AS ASSIGNED_SITE_COUNT, 
                    AVG("ALLOCATED MARKET SHARE") AS ALLOCATION_COMPLIANCE 
                FROM NTW_DM.O25500_PUF_ASPM_SUPPLIER_ALLOCATION_COMPLIANCE
                {where_sql}
                GROUP BY CUSTOMER, MARKET, "PROJECT TEMPLATE", "ALLOCATION TYPE",                
                    SUPPLIER, MUSID, "ALLOCATION QTR", "ALLOCATED MARKET SHARE"
            """
            
            alloc_df = _self.session.sql(alloc_query).to_pandas()
         
            # --- 🟢 THE ULTIMATE SQL X-RAY ---
            #with st.container(border=True):
            #    st.markdown("🕵️ DEBUG: Inspect the Alloc Query")               
            #    st.code(alloc_query, language="sql")
            # ---------------------------------
                
            # ==========================================
            # 🚀 THE NATIVE SQL PIVOT (V2: True Upsert)
            # ==========================================
            with st.spinner("Executing Native Snowflake Upsert for Suppliers..."):
                    
                # 1. ALWAYS push the Local UI Suppliers to Snowflake first!
                # This guarantees no supplier is left behind, even if they have 0 history.
                ui_suppliers = local_suppliers_df.copy()
                supp_col = 'SP_NAME' if 'SP_NAME' in ui_suppliers.columns else 'SUPPLIER'
                ui_payload = ui_suppliers[[supp_col, 'MUSID']].rename(columns={supp_col: 'SUPPLIER'}).drop_duplicates()
                    
                _self.session.write_pandas(
                    df=ui_payload, 
                    table_name="TEMP_SWA_UI_SUPPLIERS", 
                    #database="IBS_MANA_QA",
                    schema="NTW_DM",
                    auto_create_table=True, 
                    table_type="TRANSIENT", 
                    overwrite=True
                )

                # 2. Push the Metrics (if any historical data exists for this scope)
                has_alloc = False
                if not alloc_df.empty:
                   alloc_df.columns = [str(c).replace(' ', '_').upper() for c in alloc_df.columns]
                   _self.session.write_pandas(
                       df=alloc_df, 
                       table_name="TEMP_SWA_ALLOC_STAGE", 
                       #database="IBS_MANA_QA",
                       schema="NTW_DM",
                       auto_create_table=True, 
                       table_type="TRANSIENT", 
                       overwrite=True
                   )
                   has_alloc = True

               # 3. Build the Source Query (Left-joining the local suppliers with their metrics)
                if has_alloc:
                    src_query = """
                        SELECT 
                            UPPER(TRIM(ui.SUPPLIER)) AS SUPPLIER,
                            UPPER(TRIM(ui.MUSID)) AS MUSID,
                            COALESCE(AVG(al.ALLOCATION_COMPLIANCE), 0.0) AS ALLOCATION_COMPLIANCE,
                            COALESCE(SUM(al.ASSIGNED_SITE_COUNT), 0) AS ASSIGNED_SITE_COUNT,
                            COALESCE(AVG(al.CURRENT_MS), 0.0) AS CURRENT_MS,
                            COALESCE(MAX(al.ALLOCATION_QTR), 'Unknown') AS ALLOCATION_QTR
                        FROM TEMP_SWA_UI_SUPPLIERS ui
                        LEFT JOIN TEMP_SWA_ALLOC_STAGE al
                            ON UPPER(TRIM(ui.MUSID)) = UPPER(TRIM(al.MUSID))
                            AND UPPER(TRIM(ui.SUPPLIER)) = UPPER(TRIM(al.SUPPLIER))
                        GROUP BY UPPER(TRIM(ui.SUPPLIER)), UPPER(TRIM(ui.MUSID))
                    """
                else:
                    # If no history exists, safely stage all local with 0s
                    src_query = """
                        SELECT 
                            UPPER(TRIM(SUPPLIER)) AS SUPPLIER,
                            UPPER(TRIM(MUSID)) AS MUSID,
                            0.0 AS ALLOCATION_COMPLIANCE,
                            0 AS ASSIGNED_SITE_COUNT,
                            0 AS CURRENT_MS,
                            'Unknown' AS ALLOCATION_QTR
                        FROM TEMP_SWA_UI_SUPPLIERS
                        GROUP BY UPPER(TRIM(SUPPLIER)), UPPER(TRIM(MUSID))
                    """

                # 4. Execute the Native SQL UPSERT
                merge_sql = f"""
                    MERGE INTO SWA_SUPPLIERS AS tgt
                    USING ({src_query}) AS src
                        ON UPPER(TRIM(tgt.MUSID)) = UPPER(TRIM(src.MUSID))
                        AND UPPER(TRIM(tgt.SP_NAME)) = UPPER(TRIM(src.SUPPLIER))
                    WHEN MATCHED THEN 
                        UPDATE SET 
                        tgt.ALLOCATION_COMPLIANCE = src.ALLOCATION_COMPLIANCE,
                        tgt.ASSIGNED_SITE_COUNT = src.ASSIGNED_SITE_COUNT,
                        tgt.CURRENT_MS = src.CURRENT_MS,
                        tgt.ALLOCATION_QTR = src.ALLOCATION_QTR
                    WHEN NOT MATCHED THEN
                        INSERT (SP_NAME, MUSID, ALLOCATION_COMPLIANCE, ASSIGNED_SITE_COUNT, ALLOCATION_QTR, CURRENT_MS)
                        VALUES (src.SUPPLIER, src.MUSID, src.ALLOCATION_COMPLIANCE, src.ASSIGNED_SITE_COUNT, src.ALLOCATION_QTR, src.CURRENT_MS)
                """
                    
                merge_result = _self.session.sql(merge_sql).collect()
                    
                # 5. Success UI
                if merge_result:
                    rows_inserted = merge_result[0][0]
                    rows_updated = merge_result[0][1]
                    total_processed = rows_inserted + rows_updated
                else:
                     total_processed = 0
                        
                st.success(f"✅ Snowflake Native Upsert Complete! Processed {total_processed} suppliers.")

        except Exception as e:
            st.error(f"🚨 Pipeline Execution Failure: {e}")
            return False

        # Return the untouched projects matrix back to the UI
        return target_df

    ###
    ### Get the Quality Scores for all the Supplier's Projects
    ###
    def fetch_sp_quality_score(_self):
        
        try:
            # 1. Grab UI filters
            customers = st.session_state.active_filters.get("customers", [])
            markets = st.session_state.active_filters.get("markets", [])
            selected_matrices = st.session_state.active_filters.get("price_matrix", [])
            
            # Guard: bail early if filters are missing
            # """
            if not customers or not markets:
                st.warning("⚠️ Quality score fetch requires at least one customer and market filter.")
                return False
            # """ 
            st.write("DEBUG customers type/value:", customers)
            st.write("DEBUG markets type/value:", markets)
            
            if selected_matrices:
                matrix_string = selected_matrices[0] 
                raw_substrings = matrix_string.replace(' ', '_').split('_')
                tmplt_substrings = [sub for sub in raw_substrings if sub.strip()]
                like_conditions = [f"\"PROGRAM NAME\" LIKE '%{sub}%'" for sub in tmplt_substrings]
                template_sql = f"AND ({' OR '.join(like_conditions)})"
            else:
                template_sql = ""

            # SQL Safety formatting
            """
            cust_list = "'" + "','".join([str(c).replace("'", "''") for c in customers]) + "'" if customers else "SELECT DISTINCT CUSTOMER FROM NTW_DM.O25502_PUF_SUPPLIER_SCORECARD_INTERNAL"
            mkt_list = "'" + "','".join([str(m).replace("'", "''") for m in markets]) + "'" if markets else "SELECT DISTINCT MARKET FROM NTW_DM.O25502_PUF_SUPPLIER_SCORECARD_INTERNAL"
            """
            
            # SQL Safety formatting
            # """
            cust_list = "'" + "','".join([str(c).replace("'", "''") for c in customers]) + "'"
            mkt_list = "'" + "','".join([str(m).replace("'", "''") for m in markets]) + "'"
            # """
            
            # 🚀 THE INLINE MERGE (The "One-Shot" approach)
            # We put your aggregation query directly into the USING ( ... ) block.
            merge_sql = f"""
                MERGE INTO SWA_JOB_SP_MATRIX AS tgt
                USING (
                    WITH Project_KPIs AS (
                        SELECT 
                            "SUPPLIER MUS ID", 
                            "PROJECT ID",
                            COALESCE(
                                (1 - SUM(CASE WHEN KPI = 'CX Defects' THEN NUMERATOR END) 
                                     / NULLIF(SUM(CASE WHEN KPI = 'CX Defects' THEN DENOMINATOR END), 0))
                                * MAX(CASE WHEN KPI = 'CX Defects' THEN "KPI POINTS" END),
                                0
                            ) AS CX_DEFECTS_CALC,
                            COALESCE(MAX("SAFETY SCORE"), 0) AS SAFETY_SCORE,
                            COALESCE(MAX(CASE WHEN KPI = 'Vendor Training' THEN NUMERATOR END), 0) AS VENDOR_TRAINING_TOT,
                            COALESCE(
                                (SUM(CASE WHEN KPI = 'First Time Right' THEN DENOMINATOR END) 
                                 / NULLIF(COUNT(CASE WHEN KPI = 'First Time Right' THEN DENOMINATOR END), 0))
                                * MAX(CASE WHEN KPI = 'First Time Right' THEN "KPI POINTS" END),
                                0
                            ) AS FTR_CALC,
                            COALESCE(
                                (SUM(CASE WHEN KPI = 'COP Cycle Time' THEN "KPI PASS_FAIL" END) 
                                 / NULLIF(COUNT(CASE WHEN KPI = 'COP Cycle Time' THEN "KPI PASS_FAIL" END), 0))
                                * MAX(CASE WHEN KPI = 'COP Cycle Time' THEN "KPI POINTS" END),
                                0
                            ) AS COP_CYCLE_TIME_CALC,
                            COALESCE(
                                (SUM(CASE WHEN KPI = 'EU Cyc Time' THEN "KPI PASS_FAIL" END) 
                                 / NULLIF(COUNT(CASE WHEN KPI = 'EU Cyc Time' THEN "KPI PASS_FAIL" END), 0))
                                * MAX(CASE WHEN KPI = 'EU Cyc Time' THEN "KPI POINTS" END),
                                0
                            ) AS TOT_PTS_EU_CYC_TIME,
                            COALESCE(MAX(CASE WHEN KPI = 'Vendor Certs' THEN NUMERATOR END), 0) AS VENDOR_CERTS_TOT,
                            COALESCE(
                                (SUM(CASE WHEN KPI = 'JHA/SA' THEN NUMERATOR END) 
                                 / NULLIF(SUM(CASE WHEN KPI = 'JHA/SA' THEN DENOMINATOR END), 0))
                                * MAX(CASE WHEN KPI = 'JHA/SA' THEN "KPI POINTS" END),
                                0
                            ) AS JHA_SA_CALC,
                            COALESCE(
                                (SUM(CASE WHEN KPI = 'CX Cyc Time' THEN "KPI PASS_FAIL" END) 
                                 / NULLIF(COUNT(CASE WHEN KPI = 'CX Cyc Time' THEN "KPI PASS_FAIL" END), 0)) 
                                * (CASE 
                                    WHEN COUNT(CASE WHEN KPI = 'EU Cyc Time' AND "KPI PASS_FAIL" IS NOT NULL THEN 1 END) = 0 THEN 10
                                    ELSE 5
                                END), 
                            0) AS TOT_PTS_CX_CYC_TIME
                        FROM NTW_DM.O25502_PUF_SUPPLIER_SCORECARD_INTERNAL
                        WHERE CUSTOMER IN ({cust_list})
                          AND MARKET IN ({mkt_list})
                          {template_sql}
                          AND "P/C/S" != 'Child' AND "P/C/S" != 'Standalone (EFI Only)'
                          AND "ACTIVITY STATUS" = 'Completed'
                        GROUP BY "PROJECT ID", "SUPPLIER MUS ID"
                    )
                    SELECT 
                        "PROJECT ID" AS PROJECT_ID,
                        "SUPPLIER MUS ID" AS MUSID, 
                        ROUND(
                            (CX_DEFECTS_CALC + SAFETY_SCORE + VENDOR_TRAINING_TOT + 
                             FTR_CALC + COP_CYCLE_TIME_CALC + TOT_PTS_EU_CYC_TIME + 
                             VENDOR_CERTS_TOT + JHA_SA_CALC + TOT_PTS_CX_CYC_TIME), 2
                        ) AS SCORECARD_PTS  
                    FROM Project_KPIs
                ) AS src
                ON UPPER(TRIM(CAST(tgt.PROJECT_ID AS STRING))) = UPPER(TRIM(CAST(src.PROJECT_ID AS STRING)))
                AND TRY_TO_NUMBER(tgt.MUSID) = TRY_TO_NUMBER(src.MUSID)
                WHEN MATCHED THEN 
                  UPDATE SET tgt.QUALITY_SCORE = src.SCORECARD_PTS
            """
            
            # --- TEMPORARY DEBUG BLOCK ---
            st.subheader("🕵️ Key Inspection")
            col1, col2 = st.columns(2)

            with col1:
                st.write("Target Matrix Sample (SWA_JOB_SP_MATRIX)")
                tgt_sample = _self.session.sql("SELECT PROJECT_ID, MUSID FROM SWA_JOB_SP_MATRIX LIMIT 5").to_pandas()
                st.dataframe(tgt_sample)

            with col2:
                st.write("Source Scorecard Sample (Internal Table)")
                # Using the raw table name from your query
                src_sample = _self.session.sql('SELECT "PROJECT ID", "SUPPLIER MUS ID" FROM NTW_DM.O25502_PUF_SUPPLIER_SCORECARD_INTERNAL LIMIT 5').to_pandas()
                st.dataframe(src_sample)
            # -----------------------------
            
            with st.spinner("Executing One-Shot Quality Score Merge..."):
                # DEBUG: Print the problematic line
                lines = merge_sql.split('\n')
                for i, line in enumerate(lines, 1):
                    if i in range(115, 125):  # Show lines 115-125
                        st.code(f"Line {i}: {line}")
                merge_result = _self.session.sql(merge_sql).collect()
            
            # Capture the updated row count
            rows_updated = merge_result[0][1] if len(merge_result[0]) > 1 else 0
            
            if rows_updated > 0:
                st.success(f"✅ Quality Score Sync Complete! Updated {rows_updated} rows.")
            else:
                st.warning("⚠️ Merge completed but 0 rows were updated. Check if IDs match between tables.")

            return True

        except Exception as e:
            st.error(f"🚨 Quality Metric Execution Failure: {e}")
            return False

    ###
    ### Get the first 1000 entries of the specified table and put it in a df
    ###
    def fetch_dynamic_table(_self, table_name: str, limit_rows: int = 1000) -> pd.DataFrame:
        try:
            snow_df = _self.session.table(table_name)
            if limit_rows > 0:
                snow_df = snow_df.limit(limit_rows)
            return snow_df.to_pandas()
            
        except Exception as e:
            st.error(f"🚨 Failed to fetch table '{table_name}': {e}")
            return pd.DataFrame()
    
    ###
    ### Reusable debug function to safely preview any Snowflake table within a Streamlit container.
    ###
    def preview_table(_self, table_name):
        # Snowflake standardizes unquoted table names to uppercase
        clean_name = table_name.upper()
        
        with st.container(border=True):
            st.markdown(f"🔍 Preview Table: {clean_name}")
            try:
                # Use the fully qualified path so it matches the DDL
                fq_name = f"NTW_DM.{clean_name}"
                # Get the total count efficiently using Snowflake's compute engine
                total_count = _self.session.table(clean_name).count()

                # Limit the download to 500 to protect Streamlit's memory
                debug_df = _self.session.table(clean_name).limit(500).to_pandas()
        
                if debug_df.empty:
                    st.warning(f"The table '{clean_name}' exists but contains no rows.")
                else:
                    # Display the safe, limited dataframe
                    st.dataframe(debug_df)
                    
                    # Show the user the true context of what they are looking at
                    st.markdown(f"Showing **{len(debug_df)}** of **{total_count}** total rows in Snowflake.")
            
            except Exception as e:
                st.error(f"Could not read from {clean_name}: {e}")
                

    # --- WRITE SECTION (Staging to Temp Tables) ---
    def write_site_projects(_self):
        # 1. Pull the data
        df_to_write_raw = st.session_state.active_filters.get("final_projects_df")
        
        try:       
            if df_to_write_raw is None or df_to_write_raw.empty:
                st.error("⚠️ Critical Error: write_site_projects - Site Tracker Data empty.")
                return
            
            # --- DURATION LOGIC ---
            raw = df_to_write_raw.copy()
            
            # Convert to datetime and calculate difference
            c_start = pd.to_datetime(raw["CONSTRUCTION START (F)"], errors='coerce')
            a_start = pd.to_datetime(raw["ANTENNA AND LINE INSTALLATION START (F)"], errors='coerce')
            construction_diff = (c_start - a_start).dt.days

            actual_start = pd.to_datetime(raw["CONSTRUCTION START (A)"], errors='coerce')

            cond_estimate = (raw["CX CYCLE TIME ESTIMATE"] > 0) & (raw["CX CYCLE TIME ESTIMATE"].notna())
            cond_diff = (construction_diff > 0)
            
            choices = [raw["CX CYCLE TIME ESTIMATE"], construction_diff]
            
            # Apply algorithm
            calculated_duration = np.select([cond_estimate, cond_diff], choices, default=12)
            
            # --- MAPPING & CLEANUP ---
            col_mapping = {
                "PROJECT ID": "PROJECT_ID",
                "CONSTRUCTION START (F)": "START_DATE",
                "CONSTRUCTION START (A)": "START_DATE_A",
                "PROJECT TEMPLATE NAME": "PROJECT_TEMPLATE",
                "SP-ANTENNA & LINE INSTALL": "SP_ASSIGNED",
                "SP-CIVIL SUPPLIER NUMBER": "SP_MUSID_ASSIGNED",
                "SP MARKET": "SP_MARKET",
                "CUSTOMER": "CUSTOMER",
                "CUSTOMER SITE NAME": "SITE_NAME",
                "STREET ADDRESS": "STREET_ADDRESS",
                "CITY": "CITY",
                "STATE": "STATE",
                "ZIP CODE": "ZIP_CODE",
                "COUNTY": "COUNTY",
                "COUNTRY": "COUNTRY",
                "LOCATION LATITUDE": "SITE_LATITUDE",
                "LOCATION LONGITUDE": "SITE_LONGITUDE"
            }

            df_to_write = raw.rename(columns=col_mapping)
            
            # CRITICAL: Manually set DURATION_DAYS from our calculation
            df_to_write["DURATION_DAYS"] = calculated_duration
            df_to_write["START_DATE_A"] = actual_start

            expected_columns = [
                "PROJECT_ID", "START_DATE", "START_DATE_A", "DURATION_DAYS",  
                "PROJECT_TEMPLATE", "SP_MARKET", "SITE_NAME", "SP_ASSIGNED",  
                "SP_MUSID_ASSIGNED","CUSTOMER", "STREET_ADDRESS", "CITY", 
                "STATE", "ZIP_CODE","COUNTY", "COUNTRY", "SITE_LATITUDE", 
                "SITE_LONGITUDE"
            ]
            
            # Ensure columns exist first
            for col in expected_columns:
                if col not in df_to_write.columns:
                    df_to_write[col] = None
                    
            # Final selection and index reset
            df_to_write = df_to_write[expected_columns].reset_index(drop=True)
            
            # 🟢 Execute datetime conversion HERE, right before the write.
            # This forces the blank 'None' columns to become strict Datetime objects,
            # stopping PyArrow from guessing they are Integers!
            df_to_write["START_DATE"] = pd.to_datetime(df_to_write["START_DATE"], errors='coerce').dt.strftime('%Y-%m-%d')
            df_to_write["START_DATE_A"] = pd.to_datetime(df_to_write["START_DATE_A"], errors='coerce').dt.strftime('%Y-%m-%d').fillna("1900-01-01")
            
            # 🚀 WRITE TO SNOWFLAKE
            _self.session.write_pandas(
                df=df_to_write,
                table_name="SWA_SITE_PROJECTS",
                #database="IBS_MANA_QA",
                schema="NTW_DM",
                table_type="TRANSIENT",
                overwrite=True
            )
            st.success(f"✅ Staged {len(df_to_write)} projects.")
            
            # Save off final Projects to session state, so can be retrieved later for other metrics
            st.session_state["final_site_projects"] = df_to_write.copy()
            
            return df_to_write

        except Exception as e:
            st.error(f"⚠️ Write Error: {e}")
    
    def write_suppliers(_self, projects_df):
        # 1. Gather data from State
        pm_data = st.session_state.get("df1_filtered")
        crew_data = st.session_state.active_filters.get("final_crew_df")
        included_suppliers = st.session_state.active_filters.get("suppliers", [])
        
        # Context Variables
        selected_scope = st.session_state.active_filters.get("selected_crew_scope", "Unknown")
        selected_year = int(st.session_state.active_filters.get("crew_target_year", 0))
        selected_week = int(st.session_state.active_filters.get("crew_target_week", 0))

        # 2. Get Warehouse Master
        wh_data = _self.fetch_wh_data()

        try:
            if pm_data is None or pm_data.empty:
                st.error("⚠️ Step 1 Price Matrix data is missing.")
                return False
            
            # --- STEP A: THE BASE ---
            pm_data['SUPPLIER_CLEAN'] = pm_data['SUPPLIER'].astype(str).str.strip()
            clean_included = [str(s).strip() for s in included_suppliers]
            
            base_df = pm_data[pm_data['SUPPLIER_CLEAN'].isin(clean_included)][['MUSID', 'MARKET', 'SUPPLIER', 'CUSTOMER']].drop_duplicates()      
            base_df = base_df.rename(columns={'SUPPLIER': 'SP_NAME'})

            if base_df.empty:
                st.error("🚨 'base_df' is empty. No matches found between Filter and Price Matrix.")
                return False

            # --- STEP B: CREW AGGREGATION (Filtered to Target Week/Year) ---
            if crew_data is None or crew_data.empty:
                crew_agg = pd.DataFrame(columns=['Match_MUSID', 'Match_MKT', 'Match_CUST', 'EFFECTIVE_CAPACITY'])
            else:
                crew_work = crew_data.copy()
                #st.write(crew_work.columns)
                
                # 🟢 FORCE TYPES: Ensure Week and Year are integers on both sides
                # This prevents "17" != 17 from zeroing out your data
                crew_work['WEEK'] = pd.to_numeric(crew_work['WEEK'], errors='coerce').fillna(0).astype(int)
                crew_work['YEAR'] = pd.to_numeric(crew_work['YEAR'], errors='coerce').fillna(0).astype(int)
                
                # Now filter using the forced integers
                crew_work = crew_work[
                    (crew_work['WEEK'] == int(selected_week)) & 
                    (crew_work['YEAR'] == int(selected_year))
                ]

                if "EFFECTIVE_CAPACITY" not in crew_work.columns:
                    # Check for 'CREWS' vs 'NUMBER_CREWS'
                    crew_col = 'CREWS' if 'CREWS' in crew_work.columns else 'NUMBER_CREWS'
                    conf_col = 'CONFIDENCE' if 'CONFIDENCE' in crew_work.columns else 'CONFIDENCE_LEVEL'
                    
                    # Default confidence to 1.0 if the column is missing
                    conf_vals = crew_work[conf_col] if conf_col in crew_work.columns else 1.0
                    crew_work["EFFECTIVE_CAPACITY"] = crew_work[crew_col] * conf_vals
                
                # 🟢 NORMALIZE KEYS: Match the MUSID cleanup we do in STEP C
                crew_work['Match_MUSID'] = crew_work['SUPPLIER MUS ID'].astype(str).str.replace(r'\.0$', '', regex=True).str.strip().str.upper()
                crew_work['Match_MKT'] = crew_work['MARKET'].astype(str).str.strip().str.upper()
                crew_work['Match_CUST'] = crew_work['CUSTOMER'].astype(str).str.strip().str.upper()

                crew_agg = crew_work.groupby(
                    ['Match_MUSID', 'Match_MKT', 'Match_CUST'], 
                    as_index=False
                )['EFFECTIVE_CAPACITY'].sum()

            # --- STEP C: THE JOINS ---
            # Merge Warehouse (Handling the 'MUS ID' vs 'MUSID' mismatch)
            if wh_data is not None and not wh_data.empty:
                sp_table = base_df.merge(
                    wh_data[['MUSID', 'MARKET', 'FULLADDRESS', 'LATITUDE', 'LONGITUDE']],
                    left_on=['MUSID', 'MARKET'], 
                    right_on=['MUSID', 'MARKET'], 
                    how='left'
                )
            else:
                sp_table = base_df.copy()
                # Ensure the columns exist even if wh_data is empty
                for col in ['FULLADDRESS', 'LATITUDE', 'LONGITUDE', 'MUSID']: 
                    sp_table[col] = None

            # If the merge happened, 'MUSID' is the left key.
            sp_table['Match_MUSID'] = sp_table['MUSID'].astype(str).str.replace(r'\.0$', '', regex=True).str.strip().str.upper()
            sp_table['Match_MKT'] = sp_table['MARKET'].astype(str).str.strip().str.upper()
            sp_table['Match_CUST'] = sp_table['CUSTOMER'].astype(str).str.strip().str.upper()

            sp_table = sp_table.merge(crew_agg, on=['Match_MUSID', 'Match_MKT', 'Match_CUST'], how='left')
            
            # --- STEP D: MAP & FILL ---
            sp_table['SP_MARKET'] = sp_table['MARKET']
            sp_table['WH_ADDRESS'] = sp_table['FULLADDRESS'].fillna("UNKNOWN")
            sp_table['WH_LATITUDE'] = pd.to_numeric(sp_table['LATITUDE'], errors='coerce').fillna(0.0)
            sp_table['WH_LONGITUDE'] = pd.to_numeric(sp_table['LONGITUDE'], errors='coerce').fillna(0.0)
            sp_table['CREW_CAPACITY'] = sp_table['EFFECTIVE_CAPACITY'].fillna(0.0)
            
            # 🎯 QUARTER LOGIC (Scalar Assignment)
            qtr_val = f"Q{((selected_week - 1) // 13) + 1}" if selected_week > 0 else "UNKNOWN"
            sp_table['ALLOCATION_QTR'] = qtr_val
            
            sp_table['CREW_SCOPE'] = selected_scope
            sp_table['WEEK'] = selected_week
            sp_table['YEAR'] = selected_year
            sp_table['ALLOCATION_COMPLIANCE'] = 0.0
            sp_table['ASSIGNED_SITE_COUNT'] = 0.0
            sp_table['CURRENT_MS'] = 0.0
            
            expected_columns = [
                "MUSID", "SP_NAME", "SP_MARKET", "CREW_CAPACITY", "CREW_SCOPE",
                "ALLOCATION_COMPLIANCE", "WH_ADDRESS", "WH_LATITUDE", 
                "WH_LONGITUDE", "ASSIGNED_SITE_COUNT", "ALLOCATION_QTR",
                "WEEK", "YEAR", "CUSTOMER", 'CURRENT_MS'
            ]
            
            final_sp_table = sp_table[expected_columns].reset_index(drop=True)
            
            snowpark_df = _self.session.create_dataframe(final_sp_table)
            snowpark_df.write.mode("overwrite").save_as_table("NTW_DM.SWA_SUPPLIERS", table_type="transient")
            
            st.success(f"✅ Staged {len(final_sp_table)} localized suppliers for {qtr_val}.")
            
            # Merge the Market Share info
            alloc_df = _self.fetch_sp_mkt_share(local_projects_df=projects_df, 
                                                local_suppliers_df=final_sp_table
            )
                        
            # Save off final Suppliers to session state, so can be retrieved later for other metrics
            st.session_state["final_suppliers"] = final_sp_table.copy()
            return True

        except Exception as e:
            st.error(f"🚨 Supplier Write Error: {e}")
            return False
             
    def write_job_sp_matrix(_self):
        # 1. Grab our dataframes
        projects_raw = st.session_state.active_filters.get("final_projects_df")
        included_suppliers = st.session_state.active_filters.get("suppliers", [])
        final_suppliers_df = st.session_state.get("final_suppliers")

        try:
            if projects_raw is None or projects_raw.empty:
                st.warning("⚠️ No Sitetracker projects found for this selection.")
                return False
                
            projects = projects_raw.copy()            
            matrix_df = _self.fetch_ESR_data()
            
            st.info(f"received ESR {len(matrix_df)} records.") 
 
            if matrix_df is None or matrix_df.empty:
                st.caption("ℹ️ *Dev Environment Note: Simulation mode active (Empty ESR Source).*")

                matrix_df = DevSimTools.generate_synthetic_matrix(projects, final_suppliers_df)
            
                # Safety check on the mock generator
                if matrix_df is None or matrix_df.empty:
                    st.error("🚨 Failed to generate simulation data. Ensure Projects and Suppliers are selected.")
                    return False
                
                # The simulated data is already clean, so we just copy it over.
                matrix_clean = matrix_df.copy()
                # Write the simulated data to the active filters, since no real data there
                st.session_state.active_filters["BOM_Raw"] = matrix_clean

            else:                  
                # --- Include only the 'included' Suppliers ---
                # Remove punctuation and make upper case for perfect matching
                matrix_df['SUPPLIER_CLEAN'] = matrix_df['SUPPLIER'].astype(str).str.replace(r'[^\w\s]', '', regex=True).str.strip().str.upper()
                
                clean_included = [re.sub(r'[^\w\s]', '', str(s)).strip().upper() for s in included_suppliers]
                
                matrix_clean = matrix_df[matrix_df['SUPPLIER_CLEAN'].isin(clean_included)].copy()
                
                if matrix_clean.empty:
                    st.error("🚨 Filter wiped out all Matrix rows! UI Suppliers don't match Price Matrix.")
                    return False

            # Calculate and Apply the vectorized distances
            matrix_with_distances = _self.apply_drive_distances(matrix_clean, projects, final_suppliers_df)
            matrix_with_distances["DRIVE_DISTANCE"] = matrix_with_distances["DRIVE_DISTANCE"].fillna(0.0)
            
            st.session_state.active_filters["solver_base"] = matrix_with_distances.copy()

            # 1. Condition for blank (empty/whitespace) or null (NaN) = No assigned SP
            # Using fillna('') ensures that both actual NaNs and empty strings are caught safely
            cond_unassigned = matrix_with_distances['CURRENT_ASSIGN_SP'].fillna('').str.strip() == ''

            # 2. Condition for matching the supplier - Job is Assigned to an SP
            # Clean the assigned SP just like we did the supplier column
            assigned_clean = matrix_with_distances['CURRENT_ASSIGN_SP'].fillna('').astype(str).str.replace(r'[^\w\s]', '', regex=True).str.strip().str.upper()

            # Compare the cleaned assigned SP to the cleaned Supplier column
            cond_matching_sp = assigned_clean == matrix_with_distances['SUPPLIER_CLEAN']

            # 3. Combine the masks and filter the dataframe
            final_matrix = matrix_with_distances[cond_unassigned | cond_matching_sp]
            
            # 🚨 TRIPWIRE 1: Did the assignment condition wipe out our data?
            #st.warning(f"Tripwire 1: filtered_jobs_df has {len(filtered_jobs_df)} rows")

            # 🚨 TRIPWIRE 2: Did the drive distance merge wipe out our data?
            #st.warning(f"Tripwire 2: final_matrix has {len(final_matrix)} rows after drive distances")

            # 2nd: Rename the columns so they match expected_columns
            final_matrix = final_matrix.rename(columns={
                "SUPPLIER": "SP_NAME", 
                "SUPPLIER_COST": "SP_COST", 
                "MARKET": "SP_MARKET"
            })

            # 3rd: Define all columns, matching original schema + map fields          
            expected_columns = [
                "PROJECT_ID", "MUSID", "SP_NAME", "SP_MARKET", 
                "CUSTOMER", "BCR_COST", "SP_COST", 
                "DRIVE_DISTANCE", "QUALITY_SCORE",                
                "WH_ADDRESS", "WH_LATITUDE", "WH_LONGITUDE"
            ]
           
            # 2. Safely create any columns that are missing, filling them with None
            for col in expected_columns:
                if col not in final_matrix.columns:
                    final_matrix[col] = None

            # 3. Reorder the dataframe to match the expected schema exactly
            final_matrix = final_matrix[expected_columns].drop_duplicates().reset_index(drop=True)
            
            snowpark_df = _self.session.create_dataframe(final_matrix)
            snowpark_df.write.mode("overwrite").save_as_table("NTW_DM.SWA_JOB_SP_MATRIX", table_type="transient")
                        
            st.success(f"✅ Matrix built! Mapped {len(final_matrix)} distinct bidding opportunities.")
                       
            # Fetch the Quality metrics
            quality_df = _self.fetch_sp_quality_score()

            # Guard: if the fetch failed or returned a non-DataFrame, skip the merge
            if not isinstance(quality_df, pd.DataFrame) or quality_df.empty:
                final_matrix['QUALITY_SCORE'] = 0.0
            else:
                if 'QUALITY_SCORE' in final_matrix.columns:
                    final_matrix = final_matrix.drop(columns=['QUALITY_SCORE'])
                
                final_matrix = pd.merge(
                    final_matrix, 
                    quality_df, 
                    on=['PROJECT_ID', 'SP_NAME'], 
                    how='left'
                )
                final_matrix['QUALITY_SCORE'] = final_matrix['QUALITY_SCORE'].fillna(0.0)
            
            # 3. Handle potential mismatches (fill NaNs with 0 or a neutral score)
            final_matrix['QUALITY_SCORE'] = final_matrix['QUALITY_SCORE'].fillna(0.0) 
            
            # Save off final Projects to session state
            st.session_state["final_job_matrix"] = final_matrix.copy()
            
            return True
            
        except KeyError as e:
            st.error(f"🚨 Matrix Column Error: Missing column {e} in either Projects or Matrix.")
            return False
        except Exception as e:
            st.error(f"🚨 Matrix Write Error: {e}")
            return False


    def write_solver_table(_self):
        # 1. Safely pull data from session state
        solver_base = st.session_state.active_filters.get("solver_base")
        projects_data = st.session_state.active_filters.get("final_projects_df")
        
        # 🛡️ GUARD: Ensure data exists and is a DataFrame before continuing
        if solver_base is None or solver_base.empty:
            st.error("⚠️ Critical Error: write_solver - Solver Base is empty or missing.")
            return False
            
        if projects_data is None or projects_data.empty:
            st.error("⚠️ Critical Error: write_solver - Site Tracker Data empty or missing.")
            return False

        try:       
            # --- 2. PREP THE BOM DATA (filtered_jobs) ---
            # Drop the untrusted column from the BOM data so the PROJ data owns it cleanly
            filtered_jobs = solver_base.drop(columns=['CURRENT_ASSIGN_SP'], errors='ignore')

            # --- 2b. ENRICH WITH SUPPLIER MUSID ---
            final_suppliers_df = st.session_state.get("final_suppliers")
            if final_suppliers_df is not None and not final_suppliers_df.empty:
                # Build a lookup of supplier name -> MUSID
                sp_musid_lookup = final_suppliers_df[['SP_NAME', 'MUSID']].drop_duplicates()
                sp_musid_lookup = sp_musid_lookup.rename(columns={'SP_NAME': 'SUPPLIER', 'MUSID': 'SP_MUSID'})
                filtered_jobs = pd.merge(filtered_jobs, sp_musid_lookup, on='SUPPLIER', how='left')
            else:
                filtered_jobs['SP_MUSID'] = None
                
            # --- 3. PREP THE PROJECT DATA ---
            projects_df = projects_data.copy()
            
            # Convert date directly
            projects_df["CONSTRUCTION START (F)"] = pd.to_datetime(
                projects_df["CONSTRUCTION START (F)"], errors='coerce'
            ).dt.date
            
            # Rename and isolate required columns
            col_mapping = {
                "PROJECT ID": "PROJECT_ID",
                "CONSTRUCTION START (F)": "CX_START_DATE",
                "CUSTOMER SITE NAME": "CUSTOMER_SITE_NAME",
                "SP-CIVIL SUPPLIER NUMBER": "CURRENT_ASSIGN_MUSID", 
                "SP-ANTENNA & LINE INSTALL": "CURRENT_ASSIGN_SP"
            }
            projs_to_write = projects_df.rename(columns=col_mapping)[list(col_mapping.values())]

            # Standardize blank assignments to "Not Assigned"
            is_blank = projs_to_write['CURRENT_ASSIGN_SP'].fillna('').str.strip() == ''
            projs_to_write.loc[is_blank, 'CURRENT_ASSIGN_SP'] = 'Not Assigned'
            
            # --- 4. ONE-TO-MANY MERGE ---
            # Suffixes are no longer needed because we dropped the overlapping column in Step 2!
            merged_df = pd.merge(
                projs_to_write,
                filtered_jobs,
                on="PROJECT_ID", 
                how="left"
            )

            # --- 5. CALCULATE CURRENT ASSIGNMENT COST ---
            # Isolate rows where the BOM supplier is the officially assigned supplier
            current_costs = merged_df[
                merged_df['SUPPLIER'] == merged_df['CURRENT_ASSIGN_SP']
            ][['PROJECT_ID', 'SUPPLIER_COST']]
            
            # Rename and deduplicate
            current_costs = current_costs.rename(columns={'SUPPLIER_COST': 'CURR_ASSIGN_COST'})
            current_costs = current_costs.drop_duplicates(subset=['PROJECT_ID'])

            # Broadcast this cost back to all rows sharing the same PROJECT_ID
            merged_df = pd.merge(merged_df, current_costs, on='PROJECT_ID', how='left')

            # --- 6. FINAL CALCULATIONS & RANKINGS ---
            merged_df = merged_df.rename(columns={'DRIVE_DISTANCE': 'DRIVE_MILES'})
            
            # Calculate savings (Will be NaN if the assigned supplier didn't bid)
            merged_df["SAVING_FR_CURR"] = merged_df["SUPPLIER_COST"] - merged_df["CURR_ASSIGN_COST"]

            # Calculate Supplier Rank (1 is lowest cost)
            merged_df["SP_RANK"] = merged_df.groupby("PROJECT_ID")["SUPPLIER_COST"].rank(method="min")
            
            # --- 7. FINALIZE SCHEMA AND WRITE ---
            merged_df["RECOM_ASSIGN_SP"] = False
            merged_df["FINAL_ASSIGN_SP"] = False
            
            target_columns = [
                "PROJECT_ID", "CUSTOMER_SITE_NAME", "CX_START_DATE", 
                "CURRENT_ASSIGN_SP", "CURRENT_ASSIGN_MUSID", "SUPPLIER", 
                "SP_MUSID", "BCR_COST", "CURR_ASSIGN_COST", "SUPPLIER_COST", 
                "SAVING_FR_CURR", "SP_RANK", "DRIVE_MILES", 
                "RECOM_ASSIGN_SP", "FINAL_ASSIGN_SP"
            ]

            swa_solver_df = merged_df[target_columns]
            
            st.info(f"solver_df columns available: {list(swa_solver_df.columns)}")
            
            snowpark_df = _self.session.create_dataframe(swa_solver_df)
            snowpark_df.write.mode("overwrite").save_as_table("NTW_DM.SWA_SOLVER", table_type="transient")
                        
            st.success(f"✅ Solver built! Total {len(swa_solver_df)} records.")          
            
            return True

        except Exception as e:
            st.error(f"⚠️ Write Solver Table Error: {e}")
            return False