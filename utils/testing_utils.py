import pandas as pd
import random

class DevSimTools:
    """Utilities for bypassing empty development databases during testing."""
    
    @staticmethod
    def generate_synthetic_matrix(projects_df, suppliers_df):
        # Prevent the 'list has no attribute empty' error
        p_is_empty = (len(projects_df) == 0) if isinstance(projects_df, list) else projects_df.empty
        s_is_empty = (len(suppliers_df) == 0) if isinstance(suppliers_df, list) else suppliers_df.empty

        if p_is_empty or s_is_empty:
            return pd.DataFrame()

        mock_rows = []
        
        # Ensure we are iterating correctly whether it's a list or DF
        if not isinstance(projects_df, list):
            sample_projs = projects_df
        else:
            sample_projs = projects_df[:15]
        
        # Conversion to list of dicts for universal looping
        proj_list = sample_projs.to_dict('records') if not isinstance(sample_projs, list) else sample_projs
        sup_list = suppliers_df.to_dict('records') if not isinstance(suppliers_df, list) else suppliers_df

        for proj in proj_list:
            # 🟢 SAFEST EXTRACTION: Handles dicts, raw strings, and objects
            if isinstance(proj, dict):
                p_id = proj.get("PROJECT ID") or proj.get("PROJECT_ID", "UNKNOWN")
                cust = proj.get("CUSTOMER", "UNKNOWN")
                # 👈 Check for both the clean mapped name and the raw Sitetracker name
                curr_sp = proj.get("CURRENT_ASSIGN_SP") or proj.get("SP-ANTENNA & LINE INSTALL", "Not Assigned")
                supplier = proj.get("SUPPLIER") or proj.get("SP-CIVIL SUPPLIER NUMBER", "Not Assigned")
            elif isinstance(proj, str):
                p_id = proj
                cust = "UNKNOWN"
                curr_sp = "Not Assigned"
                supplier = "Not Assigned"
            else:
                p_id = getattr(proj, "PROJECT ID", getattr(proj, "PROJECT_ID", "UNKNOWN"))
                cust = getattr(proj, "CUSTOMER", "UNKNOWN")
                curr_sp = getattr(proj, "CURRENT_ASSIGN_SP", getattr(proj, "SP-ANTENNA & LINE INSTALL", "Not Assigned"))
                supplier = getattr(proj, "SUPPLIER", getattr(proj, "SP-CIVIL SUPPLIER NUMBER", "Not Assigned"))

            # If you want to cross-join ALL suppliers to ALL projects, keep this.
            # Warning: 100 projects * 200 suppliers = 20,000 rows generated instantly.
            for sup in sup_list:  
                budget = random.uniform(8000, 22000)
                actual_bid = budget * random.uniform(0.85, 1.10)
                
                s_id = sup.get("MUSID") if isinstance(sup, dict) else getattr(sup, "MUSID", "UNKNOWN")
                s_name = sup.get("SP_NAME") if isinstance(sup, dict) else getattr(sup, "SP_NAME", "UNKNOWN")
                s_mkt = sup.get("SP_MARKET") if isinstance(sup, dict) else getattr(sup, "SP_MARKET", "UNKNOWN")

                mock_rows.append({
                    "PROJECT_ID": p_id,
                    "MUSID": s_id,
                    "SP_NAME": s_name,
                    "SP_MARKET": s_mkt,
                    "CUSTOMER": cust,
                    "CURRENT_ASSIGN_SP": curr_sp, 
                    "SUPPLIER": supplier,
                    "SITE_BUDGET": round(budget, 2),
                    "SP_ACTUAL": round(actual_bid, 2)
                })
                
        final_df = pd.DataFrame(mock_rows)
        
        # 🟢 THE ILLUSION BREAKER: Shuffle the DataFrame
        # This mixes up the rows so the preview shows distinct projects immediately
        if not final_df.empty:
            final_df = final_df.sample(frac=1).reset_index(drop=True)
            
        return final_df

    
    
    
    
