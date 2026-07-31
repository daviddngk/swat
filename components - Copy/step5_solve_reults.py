"""Page 5 – Solve trigger (Greedy / CP-SAT) and results display."""
from __future__ import annotations

from typing import Optional

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

# (Adjust these import paths if your files are in the same root folder instead of a utils folder)
from utils.scoring import add_weighted_scores, ScoreConfig
from utils.solver import solve_greedy, solve_cpsat
from utils.display import color_savings_by_rank


# ── helpers ──────────────────────────────────────────────────────────────────

def _pick(df, candidates):
    # Dictionary lookup is O(1) instead of re-scanning the list
    col_map = {c.upper(): c for c in df.columns}
    for c in candidates:
        if c.upper() in col_map:
            return col_map[c.upper()]
    return None

def _extract_sms_targets(suppliers_df) -> dict[str, float]:
    """Pull strategic-market-share targets from suppliers (or editor state)."""
    candidates = [suppliers_df]
    editor = st.session_state.get("suppliers_editor_df")
    if isinstance(editor, pd.DataFrame):
        candidates.insert(0, editor)

    for df in candidates:
        sms_col = _pick(df, ["SMS_PCT", "STRATEGIC_MARKET_SHARE_PCT", "TARGET_SMS", "strategic_market_share", "sms"])
        id_col = _pick(df, ["MUSID", "supplier_id"])
        
        if sms_col is None or id_col is None:
            continue
            
        # 🟢 OPTIMIZATION: Vectorized extraction replaces iterrows()
        temp_df = pd.DataFrame({
            "id": df[id_col].astype(str).str.strip(),
            "sms": pd.to_numeric(df[sms_col], errors="coerce")
        }).dropna()
        
        temp_df = temp_df[(temp_df["id"] != "") & (temp_df["sms"] > 0)]
        
        if temp_df.empty:
            continue
            
        targets = dict(zip(temp_df["id"], temp_df["sms"]))
        total = temp_df["sms"].sum()
        mx = temp_df["sms"].max()

        if mx <= 1.0 + 1e-9 and total <= 1.0 + 1e-9:
            return targets
        return {k: v / 100.0 for k, v in targets.items()}
    return {}
    
def _parse_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None

def _fmt_money(x):
    try:
        return f"${float(x):,.0f}"
    except Exception:
        return "NA"

def _fmt_int(x):
    try:
        return f"{int(x):,d}"
    except Exception:
        return "NA"

def _fmt_qual(x):
    try:
        return f"{float(x) * 10:.1f}"
    except Exception:
        return "NA"

def _build_penalties(orch) -> Optional[dict]:
    strength = float(st.session_state.get("w_sms_compliance", 0.0))
    # 🚀 Fetched directly from Snowflake using orch
    raw_suppliers = orch.fetch_dynamic_table("SWA_SUPPLIERS", limit_rows=0)
    targets = _extract_sms_targets(raw_suppliers)
    
    if strength <= 0 or not targets:
        return None
    return {"market_share": {"enabled": True, "strength": strength, "targets": targets, "mode": "absolute_deviation"}}

def _metrics(adf, scored_df):
    if adf is None or adf.empty:
        return None
        
    # 🟢 Ensure BOTH merge keys exist before subsetting
    if "supplier_id" not in adf.columns or "job_id" not in adf.columns:
        return {"count": 0, "cost": 0.0, "dist": 0.0, "qual": 0.0}

    # 🟢 Make the status check case-insensitive and safe
    if "status" in adf.columns:
        assigned_df = adf[adf["status"].astype(str).str.upper() == "ASSIGNED"].copy()
    else:
        assigned_df = adf.copy() # Fallback if solver doesn't return a status column
        
    if assigned_df.empty:
        return {"count": 0, "cost": 0.0, "dist": 0.0, "qual": 0.0}

    merged = assigned_df[["job_id", "supplier_id"]].merge(
        scored_df, on=["job_id", "supplier_id"], how="left"
    )
    
    # 🟢 THE FIX: Pull cost from the 'merged' dataframe, not the raw solver output
    cost = pd.to_numeric(merged["cost"], errors="coerce")
    
    return {
        "count": len(assigned_df),
        "cost": float(cost.fillna(0).sum()),
        "dist": float(merged["drive_distance"].fillna(0).sum()),
        "qual": float(merged["quality_score"].mean()) if merged["quality_score"].notna().any() else 0.0,
    }

#def _apply_baseline(adf, jobs_df):
#    if "assigned_supplier_id" in jobs_df.columns and not adf.empty:
#        bl = jobs_df[["job_id", "assigned_supplier_id"]].rename(columns={"assigned_supplier_id": "baseline_supplier_id"})
#        adf = adf.merge(bl, on="job_id", how="left")
#        adf["supplier_changed"] = adf["baseline_supplier_id"].astype(str) != adf["supplier_id"].astype(str)
#    return adf

def _mark_results(solver_df: pd.DataFrame, results_df: pd.DataFrame) -> pd.DataFrame:
    """
    Takes the chosen assignments from the solver and flags the corresponding 
    rows in the main solver_df as the recommended assignment.
    """
        
    # 1. Initialize the target column to False
    col_name = "RECOM_ASSIGN_SP"
    work_df = solver_df.copy()
    
    if results_df is None or results_df.empty:
        work_df[col_name] = False
        return work_df

    # 2. Create temporary matching columns to guarantee perfect ID alignment 
    # (Without overwriting the original ID formats needed for Snowflake)
    work_df["_match_job"] = work_df["job_id"].astype(str).str.strip()
    work_df["_match_sp"] = work_df["supplier_id"].astype(str).str.strip()

    # Drop unassigned jobs and create matching columns for the results
    valid_results = results_df.dropna(subset=["supplier_id"]).copy()
    valid_results["_match_job"] = valid_results["job_id"].astype(str).str.strip()
    valid_results["_match_sp"] = valid_results["supplier_id"].astype(str).str.strip()
    
    # Add a flag to indicate these specific pairs were chosen
    valid_results["_is_chosen"] = True

    # 3. Left-merge the chosen flag onto the main solver_df
    merged = work_df.merge(
        valid_results[["_match_job", "_match_sp", "_is_chosen"]], 
        on=["_match_job", "_match_sp"], 
        how="left"
    )

    # 4. Apply the boolean flag and drop the temporary matching columns
    work_df[col_name] = merged["_is_chosen"].fillna(False).astype(bool)
    work_df = work_df.drop(columns=["_match_job", "_match_sp"])

    return work_df
    
def _write_final_assign_2SF (orch, editted_df, edit_col):
    try:
        # Isolate the payload: We only need the primary keys and the edited boolean
        payload_df = editted_df[["job_id", "supplier_id", edit_col]].copy()
                    
        # Rename them back to Snowflake's native names for the merge
        payload_df = payload_df.rename(columns={
            "job_id": "PROJECT_ID",
            "supplier_id": "SP_MUSID"
        })
                    
        # Stage the data
        orch.session.write_pandas(
            df=payload_df, 
            table_name="TEMP_SOLVER_ASSIGNMENTS_STAGE", 
            auto_create_table=True, table_type="transient", overwrite=True
        )
                    
        # Execute the Native MERGE
        # (Remember: No 'tgt.' on the left side of the UPDATE SET!)
        merge_sql = f"""
            MERGE INTO SWA_SOLVER AS tgt
                USING TEMP_SOLVER_ASSIGNMENTS_STAGE AS src
                 ON UPPER(TRIM(tgt.PROJECT_ID)) = UPPER(TRIM(src.PROJECT_ID))
                AND UPPER(TRIM(tgt.SP_MUSID)) = UPPER(TRIM(src.SP_MUSID))
            WHEN MATCHED THEN 
                UPDATE SET 
                "{edit_col.upper()}" = src."{edit_col}"
        """
        #st.code(merge_sql, language="sql")
        merge_result = orch.session.sql(merge_sql).collect()
                    
        # Safely parse the results
        if merge_result and len(merge_result) > 0:
            row = merge_result[0]
            rows_updated = row[0] if len(row) == 1 else row[1]
        else:
             rows_updated = 0
                        
        st.success(f"✅ Snowflake Upsert Complete! Updated {rows_updated} rows.")
                    
    except Exception as e:
        st.error(f"🚨 Failed to update Snowflake: {e}")    
    
# ── public entry point ───────────────────────────────────────────────────────

def render_solve_results(orch):
    st.header("Solve & Results")

    # ── weights from session ──
    w_cost = float(st.session_state.get("w_cost", 1 / 3))
    w_quality = float(st.session_state.get("w_quality", 1 / 3))
    w_distance = float(st.session_state.get("w_distance", 1 / 3))

    st.caption(f"Using weights → Cost: {w_cost:.2f}  Quality: {w_quality:.2f}  Distance: {w_distance:.2f}")

    # ── 1. LOAD UNIFIED SOLVER DATA ──
    solver_df = orch.fetch_dynamic_table("SWA_SOLVER", limit_rows=0)
    matrix_df = orch.fetch_dynamic_table("SWA_JOB_SP_MATRIX", limit_rows=0)

    if solver_df.empty:
        st.warning("No job data found in SWA_SOLVER. Import data first.")
        return

    #st.info(f"solver_df columns available: {list(solver_df.columns)}")
    
    # ── 2. DYNAMIC SCHEMA MAPPING (Crash-Proof) ──
    # Safely find the exact column names in solver_df using your _pick helper
    job_col = _pick(solver_df, ["PROJECT_ID", "PROJECT ID", "JOB_ID"]) or "PROJECT_ID"
    sp_col = _pick(solver_df, ["SP_MUSID", "SUPPLIER_ID", "MUSID"]) or "SP_MUSID"
    cost_col = _pick(solver_df, ["SUPPLIER_COST", "SP_ACTUAL", "COST"]) or "SUPPLIER_COST"
    dist_col = _pick(solver_df, ["DRIVE_MILES","DRIVE_DISTANCE", "DISTANCE"]) or "DRIVE_DISTANCE"
    assign_col = _pick(solver_df, ["CURRENT_ASSIGN_MUSID", "ASSIGNED_SP", "ASSIGNED_SUPPLIER_ID", "CURRENT_ASSIGN_SP"]) or "CURRENT_ASSIGN_MUSID"

    solver_df = solver_df.rename(columns={
        job_col: "job_id", 
        sp_col: "supplier_id",
        cost_col: "cost", 
        dist_col: "drive_distance", 
        assign_col: "assigned_supplier_id"
    })
    
    # Standardize the Supplier primary key
    sup_id_col = _pick(matrix_df, ["MUSID", "SUPPLIER_ID"]) or "MUSID"
    matrix_df = matrix_df.rename(columns={sup_id_col: "supplier_id", job_col: "job_id"})
    
    # ── 3. SMART QUALITY SCORE MERGE ──
    # Pulls Quality Score from SWA_JOB_SP_MATRIX (Handles both Job-level and Global-level scoring natively)
    if "QUALITY_SCORE" in matrix_df.columns:       
        
        # 1. Bulletproof cleaning (removes trailing '.0', strips spaces, forces UPPERCASE)
        def clean_keys(df, col):
            if col in df.columns:
                return df[col].astype(str).str.replace(r'\.0$', '', regex=True).str.strip().str.upper()
            return df[col]
            
        matrix_df["supplier_id"] = clean_keys(matrix_df, "supplier_id")
        matrix_df["job_id"] = clean_keys(matrix_df, "job_id")
        
        solver_df["supplier_id"] = clean_keys(solver_df, "supplier_id")
        solver_df["job_id"] = clean_keys(solver_df, "job_id")

        # 2. Update columns and keys to include job_id
        qual_cols = ["QUALITY_SCORE", "supplier_id", "job_id"]
        merge_keys = ["supplier_id", "job_id"]
             
        # 3. Perform the exact match merge
        qual_subset = matrix_df[qual_cols].drop_duplicates(subset=merge_keys)
        solver_df = pd.merge(solver_df, qual_subset, on=merge_keys, how="left")
        
        # 4. Clean up the final column
        solver_df = solver_df.rename(columns={"QUALITY_SCORE": "quality_score"})
        solver_df["quality_score"] = pd.to_numeric(solver_df["quality_score"], errors="coerce").fillna(0.0)
    else:
        st.info("Didn't find column in matrix_df")
        solver_df["quality_score"] = 0.0

    # Clean numeric formats safely
    for c in ("cost", "drive_distance", "quality_score"):
        if c in solver_df.columns:
            solver_df[c] = pd.to_numeric(solver_df[c], errors="coerce").fillna(0.0)
        else:
            solver_df[c] = 0.0  # Safe fallback if the column is missing

    # ── 4. APPLY Z-SCORES ──
    scored_df = add_weighted_scores(
        solver_df, w_cost=w_cost, w_quality=w_quality, w_distance=w_distance, config=ScoreConfig(clip_z=4.0)
    )

    # Ensure IDs are strings to prevent hidden solver merge failures
    if "job_id" in scored_df.columns:
        scored_df["job_id"] = scored_df["job_id"].astype(str).str.strip()
    if "supplier_id" in scored_df.columns:
        scored_df["supplier_id"] = scored_df["supplier_id"].astype(str).str.strip()
    if "assigned_supplier_id" in scored_df.columns:
        scored_df["assigned_supplier_id"] = scored_df["assigned_supplier_id"].astype(str).str.strip().replace(["None", "nan", "<NA>", "NaN"], "")
        
    # ── 5. INSTANT BASELINE METRICS (Crash-Proof) ──
    total_jobs = scored_df["job_id"].nunique() if "job_id" in scored_df.columns else 0
    
    # 🟢 THE FIX: Safely check if BOTH columns exist before comparing them
    if "assigned_supplier_id" in scored_df.columns and "supplier_id" in scored_df.columns:
        baseline_df = scored_df[scored_df["supplier_id"] == scored_df["assigned_supplier_id"]]
        bl_assigned = baseline_df["job_id"].nunique()
        bl_cost = float(baseline_df["cost"].sum()) if "cost" in baseline_df.columns else 0.0
        bl_dist = float(baseline_df["drive_distance"].sum()) if "drive_distance" in baseline_df.columns else 0.0
        bl_qual = float(baseline_df["quality_score"].mean()) if "quality_score" in baseline_df.columns and not baseline_df.empty else 0.0
    else:
        bl_assigned, bl_cost, bl_dist, bl_qual = 0, 0.0, 0.0, 0.0
        # 🚨 DEBUGGING ALERT: Show exactly what columns exist on the screen so we can fix the missing ID!
        st.error(f"🚨 Missing ID Columns! Scored columns available: {list(scored_df.columns)}")
        
    bl_unassigned = total_jobs - bl_assigned

    # ── 6. UI & SESSION STATE ──
    for k in ("greedy_assignments", "greedy_unassigned", "cpsat_assignments"):
        st.session_state.setdefault(k, None)

    st.session_state.setdefault("w_sms_compliance", 0.5)
    st.slider("SMS Compliance Strength", 0.0, 1.0, step=0.01, key="w_sms_compliance",
              help="Higher values push allocations closer to target market shares.")

    st.markdown("---")
    c_head, c_greedy, c_cpsat = st.columns([2, 1, 1])
    with c_head:
        st.subheader("Scenario Comparison")

    penalties_payload = _build_penalties(orch)
    
#    def _apply_baseline(adf):
#        if not adf.empty and "assigned_supplier_id" in scored_df.columns:
#            cols = ["job_id", "assigned_supplier_id"]
#            if "CURRENT_ASSIGN_SP" in scored_df.columns:
#                cols.append("CURRENT_ASSIGN_SP")
#            bl = scored_df[cols].drop_duplicates(subset=["job_id"]).rename(columns={
#                "assigned_supplier_id": "baseline_supplier_id",
#                "CURRENT_ASSIGN_SP": "baseline_supplier_name"
#            })
#            adf = adf.merge(bl, on="job_id", how="left")
#            adf["supplier_changed"] = (adf["baseline_supplier_id"] != "") & (adf["baseline_supplier_id"] != adf["supplier_id"].astype(str))
#        return adf
    
    # ── 7. EXECUTE SOLVERS ──
    with c_greedy:
        if st.button("Solve (Single Pass)", type="primary", use_container_width=True):
            with st.spinner("Running native Single Pass solver…"):
                
                raw_results = solve_greedy(scored_df, penalties=penalties_payload)
                
                if not raw_results:
                    st.error("No assignments returned.")
                else:
                    results_df = pd.DataFrame(raw_results)
                    marked_df = _mark_results(scored_df, results_df)
                    st.session_state.greedy_assignments = marked_df
                    st.rerun()
    
    with c_cpsat:
        if st.button("Solve (Multi-Pass)", use_container_width=True):
            with st.spinner("Running native multi-pass solver…"):
                raw_results = solve_cpsat(scored_df, time_limit_s=60, max_workers=8, penalties=penalties_payload)
                results_df = pd.DataFrame(raw_results)
                
            if results_df.empty:
                st.error("No assignments returned.")
            else:
                marked_df = _mark_results(scored_df, results_df)
                #adf = _apply_baseline(adf)
                st.session_state.cpsat_assignments = marked_df
                st.rerun()

    # ── 8. COMPARISON TABLE ──
    g_m = _metrics(st.session_state.greedy_assignments, scored_df)
    c_m = _metrics(st.session_state.cpsat_assignments, scored_df)

    def _val(m, k, fn=str): return fn(m[k]) if m else "NA"
    def _diff(m, k, bl_val, fn=str, invert=False):
        if m is None: return "NA"
        d = m[k] - bl_val
        return fn(-d if invert else d)

    g_un = total_jobs - g_m["count"] if g_m else "NA"
    c_un = total_jobs - c_m["count"] if c_m else "NA"

    rows = [
        ("Jobs Assigned", _fmt_int(bl_assigned), _val(g_m, "count", _fmt_int), _val(c_m, "count", _fmt_int)),
        ("Jobs Unassigned", _fmt_int(bl_unassigned), _fmt_int(g_un) if g_m else "NA", _fmt_int(c_un) if c_m else "NA"),
        ("Cost", _fmt_money(bl_cost), _val(g_m, "cost", _fmt_money), _val(c_m, "cost", _fmt_money)),
        ("Cost Savings", "NA", _diff(g_m, "cost", bl_cost, _fmt_money, True), _diff(c_m, "cost", bl_cost, _fmt_money, True)),
        ("Drive Distance", _fmt_int(bl_dist), _val(g_m, "dist", _fmt_int), _val(c_m, "dist", _fmt_int)),
        ("Distance Saving", "NA", _diff(g_m, "dist", bl_dist, _fmt_int, True), _diff(c_m, "dist", bl_dist, _fmt_int, True)),
        ("Quality (0-100)", _fmt_qual(bl_qual), _val(g_m, "qual", _fmt_qual), _val(c_m, "qual", _fmt_qual)),
        ("Quality Improvement", "NA", _diff(g_m, "qual", bl_qual, _fmt_qual), _diff(c_m, "qual", bl_qual, _fmt_qual)),
    ]
    cmp_df = pd.DataFrame(rows, columns=["Metric", "Baseline", "Single Pass", "Multi-Pass"])
    st.table(cmp_df.set_index("Metric"))

    # ── 9. DETAILED RESULTS ──
    if st.session_state.greedy_assignments is not None:
        adf = st.session_state.greedy_assignments
        st.markdown("### Single Pass Assignments")
        
        # 1. Clean up columns you don't want to show
        adf = adf.drop(columns=[
            "z_cost_raw", "z_distance_raw", "z_cost", "z_distance", "z_quality_raw",
            "z_quality", "outlier_cost", "outlier_distance", "outlier_quality", "f_cost",
            "f_distance", "f_quality", "weighted_z_score", "w_cost_used", "w_quality_used", 
            "w_distance_used"
        ], errors="ignore")

        # 🟢 Define the exact name of your boolean column here
        # (Based on your DDL, it might be 'OVERRIDE_ASSIGN', 'FINAL_ASSIGN_SP', or 'recom_assign_SP')
        edit_col = "FINAL_ASSIGN_SP" 

        # 🟢 Force strict True/False casting to eliminate the gray "NaN" state
        if edit_col in adf.columns:
            adf[edit_col] = adf[edit_col].fillna(False).astype(bool)
        else:
            # Fallback just in case the column is completely missing
            adf[edit_col] = False

        # 2. Lock all columns EXCEPT the boolean column
        locked_cols = [c for c in adf.columns if c != edit_col]

        # 3. Apply your styling
        styled = adf.style.apply(color_savings_by_rank, axis=1).format({
            "BCR_COST": "${:,.0f}", "SAVING_FR_CURR": "${:,.0f}", "SUPPLIER_COST": "${:,.0f}", 
            "CURR_ASSIGN_COST": "${:,.0f}", "SP_RANK": "{:.0f}", "DRIVE_MILES": "{:.2f}",
            "cost": "${:,.0f}", "drive_distance": "{:.2f}", "quality_score": "{:,.1f}"
        })

        # 4. 🟢 Use data_editor instead of dataframe
        edited_df = st.data_editor(
            styled, 
            disabled=locked_cols,
            # 🟢 ENHANCEMENT: Explicitly define the checkbox UI to ensure it renders brightly
            column_config={
                edit_col: st.column_config.CheckboxColumn(
                    "Final Assign SP", # You can customize the display header here!
                    help="Check to make this assignment final.",
                    default=False,
                )
            },
            use_container_width=True,
            key="greedy_editor"
        )

        # Download button uses the newly edited dataframe
        st.download_button("Download Single Pass CSV", edited_df.to_csv(index=False).encode(), "swa_assignments_sp.csv", "text/csv")
        
        # ── 5. 🟢 SAVE TO SNOWFLAKE LOGIC ──
        if st.button("Save Assignments to Snowflake", type="primary", key="save_greedy"):
            with st.spinner("Pushing assignments to SWA_SOLVER..."):
                _write_final_assign_2SF(orch, edited_df, edit_col)
                    
    if st.session_state.cpsat_assignments is not None:
        adf = st.session_state.cpsat_assignments
        adf = adf.drop(columns=["z_cost_raw", "z_distance_raw", "z_cost", "z_distance", "z_quality_raw",
                                "z_quality", "outlier_cost", "outlier_distance", "outlier_quality", "f_cost",
                                "f_distance", "f_quality", "weighted_z_score", "w_cost_used", "w_quality_used", 
                                "w_distance_used"])

        st.markdown("### Multi-Pass Assignments")
        if "supplier_changed" in adf.columns:
            st.metric("Supplier changes vs baseline", int(adf["supplier_changed"].sum()))

        edit_col = "FINAL_ASSIGN_SP" 

        # 🟢 Force strict True/False casting to eliminate the gray "NaN" state
        if edit_col in adf.columns:
            adf[edit_col] = adf[edit_col].fillna(False).astype(bool)
        else:
            # Fallback just in case the column is completely missing
            adf[edit_col] = False

        # 2. Lock all columns EXCEPT the boolean column
        locked_cols = [c for c in adf.columns if c != edit_col]
        
        styled = adf.style.apply(color_savings_by_rank, axis=1).format(
                {"BCR_COST": "${:,.0f}", "SAVING_FR_CURR": "${:,.0f}", "SUPPLIER_COST": "${:,.0f}", 
                 "CURR_ASSIGN_COST": "${:,.0f}", "SP_RANK": "{:.0f}", "DRIVE_MILES": "{:.2f}",
                 "cost": "${:,.0f}", "drive_distance": "{:.2f}", "quality_score": "{:,.1f}"}
            )
        
        cpsat_df = st.data_editor(
            styled, 
            disabled=locked_cols,
            # 🟢 ENHANCEMENT: Explicitly define the checkbox UI to ensure it renders brightly
            column_config={
                edit_col: st.column_config.CheckboxColumn(
                    "Final Assign SP", # You can customize the display header here!
                    help="Check to make this assignment final.",
                    default=False,
                )
            },
            use_container_width=True,
            key="cpsat_editor"
        )

        #st.dataframe(styled)
        
        st.download_button("Download Multi-Pass CSV", adf.to_csv(index=False).encode(), "swa_assignments_mp.csv", "text/csv")
        # 🟢 SAVE TO SNOWFLAKE LOGIC ──
        if st.button("Save Assignments to Snowflake", type="primary", key="save_cpsat"):
            with st.spinner("Pushing assignments to SWA_SOLVER..."):
                _write_final_assign_2SF(orch, cpsat_df, edit_col)

        