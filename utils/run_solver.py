"""Thin helpers for talking to the macs_alloc FastAPI server."""
import time
import utils.solver
import pandas as pd



def run_solve(payload: dict, poll_limit: int = 120) -> tuple[str, pd.DataFrame]:
    """Post a solve request, poll until done, return (status, assignments_df)."""
    resp = api_post("/solve", payload)
    run_id = resp["run_id"]

    status = "QUEUED"
    for _ in range(poll_limit):
        info = api_get_json(f"/solve/{run_id}")
        status = info.get("status", "UNKNOWN")
        if status in ("SUCCEEDED", "FAILED", "CRASHED", "CANCELED"):
            break
        time.sleep(1)

    assignments = api_get_json(f"/solve/{run_id}/assignments")
    df = pd.DataFrame(assignments)
    if not df.empty:
        df["job_id"] = df["job_id"].astype(str)
        df["supplier_id"] = df["supplier_id"].astype(str)
        df["cost"] = pd.to_numeric(df["cost"], errors="coerce")
        df["drive_distance"] = pd.to_numeric(df["drive_distance"], errors="coerce")
    return status, df
