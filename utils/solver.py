# utils/solver.py
from __future__ import annotations

import logging
from datetime import datetime, date
from typing import Iterable, Optional
import heapq
import pandas as pd
from ortools.sat.python import cp_model
import utils.scoring as scoring 
import streamlit as st

logger = logging.getLogger(__name__)

# ---------------------------------------------------------
# 🛠️ Data Extraction Helpers
# ---------------------------------------------------------

def _parse_start_date(value: object) -> int:
    if pd.isna(value) or value is None:
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).split()[0] 
    try:
        return date.fromisoformat(text).toordinal()
    except ValueError:
        pass
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date().toordinal()
        except ValueError:
            continue
    return 0

def _extract_capacity(suppliers_df: pd.DataFrame) -> dict[str, int]:
    cap: dict[str, int] = {}
    if suppliers_df.empty:
        return cap
        
    # 🟢 THE FIX 1: Add "CREW_CAPACITY" to the list of recognized column names
    crew_col = next((c for c in suppliers_df.columns if c.upper() in ["CREW_CAPACITY", "CAPACITY", "CREWS", "NUMBER_CREWS"]), None)
    id_col = next((c for c in suppliers_df.columns if c.upper() in ["SUPPLIER_ID", "MUSID"]), None)
    
    for _, row in suppliers_df.iterrows():
        sid = str(row.get(id_col, "")).strip()
        if not sid: continue
        
        try:
            # 🟢 THE FIX 2: Default to 999 (unlimited) if the cell is blank or the column is missing!
            val = row[crew_col] if crew_col else None
            cap[sid] = int(float(val)) if pd.notna(val) and str(val).strip() != "" else 999
        except (ValueError, TypeError):
            cap[sid] = 999
            
    return cap

def _extract_job_windows(jobs_df: pd.DataFrame) -> dict[str, tuple[int, int, int]]:
    windows: dict[str, tuple[int, int, int]] = {}
    if jobs_df.empty:
        return windows

    id_col = next((c for c in jobs_df.columns if c.upper() in ["JOB_ID", "PROJECT_ID"]), "job_id")
    start_col = next((c for c in jobs_df.columns if c.upper() in ["START_DATE", "START"]), None)
    dur_col = next((c for c in jobs_df.columns if c.upper() in ["DURATION_DAYS", "DURATION"]), None)

    for _, row in jobs_df.iterrows():
        job_id = str(row.get(id_col, ""))
        start_val = row.get(start_col)
        dur = int(float(row[dur_col])) if dur_col and pd.notna(row[dur_col]) else 1
        
        start_ord = _parse_start_date(start_val)
        windows[job_id] = (start_ord, dur, start_ord + dur)
            
    return windows

# ---------------------------------------------------------
# 🚀 The Optimization Engines
# ---------------------------------------------------------

def solve_greedy(solver_df, penalties=None):
    # 🟢 1. BULLETPROOF ID SYNC (Only one dataframe to clean now!)
    scored = solver_df.copy()

    scored["job_id"] = scored["job_id"].astype(str).str.strip()
    if "supplier_id" in scored.columns:
        scored["supplier_id"] = scored["supplier_id"].astype(str).str.strip()

    # Extract the unique jobs directly from the unified matrix
    jobs = scored["job_id"].unique().tolist()

    # 🟢 2. EXTRACT SMS TARGETS 
    raw_targets = penalties.get("market_share", {}).get("targets", {}) if penalties else {}
    sms_targets = {k: (0.0 if pd.isna(v) else float(v)) for k, v in raw_targets.items()}
    sms_strength = penalties.get("market_share", {}).get("strength", 0.0) if penalties else 0.0
    
    # Track assignments for dynamic SMS
    all_sids = set(scored["supplier_id"].unique())
    supplier_assignment_counts = {s: 0 for s in all_sids}
    total_assigned = 0

    results = []
    
    # Pre-sort the unified dataframe once so the best baseline score is always on top
    scored = scored.sort_values(["job_id", "weighted_z_score"], ascending=[True, False])

    for job_id in jobs:
        subset = scored[scored["job_id"] == job_id]
        
        # Safe fallback (though extremely unlikely since jobs came from the same df)
        if subset.empty:
            results.append({
                "job_id": job_id, "supplier_id": None, "cost": None, 
                "drive_distance": None, "status": "UNASSIGNED"
            })
            continue

        # 🟢 3. OPTIMIZED DYNAMIC SMS PENALTY
        # If SMS is active, vectorize the penalty calculation instead of slow axis=1 apply
        if sms_strength > 0 and total_assigned > 0:
            subset = subset.copy() # Avoid SettingWithCopyWarning
            
            # Map the current assignment counts instantly across the subset
            current_shares = subset["supplier_id"].map(supplier_assignment_counts).fillna(0) / total_assigned
            target_shares = subset["supplier_id"].map(sms_targets).fillna(0.0)
            
            # Positive deviation = too much work; Negative = needs more
            deviations = current_shares - target_shares
            subset["dynamic_score"] = subset["weighted_z_score"] - (sms_strength * deviations)
            
            # Pick the supplier with the highest dynamic score
            chosen_row = subset.loc[subset["dynamic_score"].idxmax()]
        else:
            # If SMS is 0, just grab the top row instantly (since we pre-sorted)
            chosen_row = subset.iloc[0]

        # 4. ASSIGN AND UPDATE
        final_sid = str(chosen_row["supplier_id"])
        final_sp = str(chosen_row.get("SUPPLIER", chosen_row.get("supplier", "")))
        supplier_assignment_counts[final_sid] += 1
        total_assigned += 1
        
        results.append({
            "job_id": job_id,
            "supplier_id": final_sid,
            #"supplier" : final_sp,
            #"cost": float(chosen_row["cost"]) if pd.notna(chosen_row["cost"]) else None,
            #"drive_distance": float(chosen_row["drive_distance"]) if pd.notna(chosen_row["drive_distance"]) else None,
            #"status": "ASSIGNED",
        })
        
        st.session_state.greedy_assign_list = results
        
    return results


def solve_cpsat(solver_df, time_limit_s=60, max_workers=8, penalties=None):
    # 🟢 1. BULLETPROOF ID SYNC (Only one dataframe to clean now!)
    scored = solver_df.copy()

    scored["job_id"] = scored["job_id"].astype(str).str.strip()
    if "supplier_id" in scored.columns:
        scored["supplier_id"] = scored["supplier_id"].astype(str).str.strip()

    # Extract the unique jobs directly from the unified matrix
    jobs = scored["job_id"].unique().tolist()
    
    # 🟢 2. EXTRACT SMS TARGETS
    raw_targets = penalties.get("market_share", {}).get("targets", {}) if penalties else {}
    sms_targets = {k: (0.0 if pd.isna(v) else float(v)) for k, v in raw_targets.items()}
    sms_strength = penalties.get("market_share", {}).get("strength", 0.0) if penalties else 0.0
    
    scored["weighted_z_score"] = scored["weighted_z_score"].fillna(-1e6)
    scored["min_cost"] = scoring.to_minimization_cost(scored["weighted_z_score"])
    
    model = cp_model.CpModel()
    x = {}
    objective_terms = []
    unassigned_terms = []

    # 🟢 3. OPTIMIZATION: Group by job_id upfront to eliminate slow dataframe masking in loops
    job_groups = scored.groupby("job_id")

    # 4. BUILD ASSIGNMENT VARIABLES
    for job_id in jobs:
        # Skip if somehow the job isn't in the groups
        if job_id not in job_groups.groups: 
            continue
            
        options = job_groups.get_group(job_id)
        vars_for_job = []
        
        for _, row in options.iterrows():
            sid = str(row["supplier_id"])
            
            # Create a boolean variable: 1 if this supplier gets this job, 0 if not
            var = model.NewBoolVar(f"x_{job_id}_{sid}")
            x[(job_id, sid)] = var
            vars_for_job.append(var)
            
            # Add the cost to the objective
            cost_val = int(round(float(row["min_cost"])))
            objective_terms.append(cost_val * var)
            
        if vars_for_job:
            unassigned = model.NewBoolVar(f"u_{job_id}")
            # Constraint: Exactly 1 supplier must be chosen, OR it remains unassigned
            model.Add(sum(vars_for_job) + unassigned == 1)
            # Leaving a job unassigned incurs a massive 1,000,000 penalty
            unassigned_terms.append(1_000_000 * unassigned)

    # 5. SMS LOGIC (Absolute Deviation Penalty)
    if sms_strength > 0 and sms_targets:
        total_jobs = len(jobs)
        penalty_multiplier = int(sms_strength * 500_000)

        # Get all unique suppliers instantly
        all_sids = scored["supplier_id"].unique()

        for sid in all_sids:
            target_count = int(round(total_jobs * sms_targets.get(sid, 0.0)))
            supplier_vars = [x[(j, sid)] for j in jobs if (j, sid) in x]

            if supplier_vars:
                actual_count = sum(supplier_vars)
                dev_var = model.NewIntVar(0, total_jobs, f"dev_{sid}")

                model.Add(dev_var >= actual_count - target_count)
                model.Add(dev_var >= target_count - actual_count)
                objective_terms.append(penalty_multiplier * dev_var)

    # Minimize total cost + unassigned penalties + SMS deviation fines
    model.Minimize(sum(objective_terms) + sum(unassigned_terms))
    
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(time_limit_s)
    solver.parameters.num_search_workers = int(max_workers)
    
    status = solver.Solve(model)
    
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        print("CP-SAT INFEASIBLE: Conflicting constraints preventing solution.")
        return [] 
    
    results = []
    
    # 6. EXTRACT ASSIGNMENTS
    for job_id in jobs:
        assigned = False
        
        if job_id in job_groups.groups:
            options = job_groups.get_group(job_id)
            for _, row in options.iterrows():
                sid = str(row["supplier_id"])
                if (job_id, sid) in x and solver.Value(x[(job_id, sid)]) == 1:
                    results.append({
                        "job_id": job_id, "supplier_id": sid
                        # Safely cast outputs just like solve_greedy
                        #, "status": "ASSIGNED", "cost": float(row["cost"]) if pd.notna(row["cost"]) else None,
                        #"drive_distance": float(row["drive_distance"]) if pd.notna(row["drive_distance"]) else None
                    })
                    assigned = True
                    break
                
        #if not assigned:
        #    results.append({
        #        "job_id": job_id, "supplier_id": None, "status": "UNASSIGNED"
                #, "cost": None, 
                #"drive_distance": None, "status": "UNASSIGNED"
        #    })
            
    return results
    