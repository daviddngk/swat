"""Page 4 – Supplier SMS editor, pie chart, and objective weight sliders."""
from __future__ import annotations
import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

from typing import Optional

# ── helpers ──────────────────────────────────────────────────────────────────

#def _pick_first_col(df: pd.DataFrame, candidates: list[str]) -> Optional[str]:
#    # Convert columns to uppercase for safe Snowflake matching
#    upper_cols = [c.upper() for c in df.columns]
#    for c in candidates:
#        if c.upper() in upper_cols:
#            # Return the actual column name from the dataframe
#            return df.columns[upper_cols.index(c.upper())]
#return None

def _pick_first_col(df: pd.DataFrame, candidates: list[str]) -> Optional[str]:
    # Build a dictionary mapping UPPERCASE to the original exact casing
    col_map = {c.upper(): c for c in df.columns}
    for c in candidates:
        if c.upper() in col_map:
            return col_map[c.upper()]
    return None
    
def _parse_float(value) -> Optional[float]:
    if value is None:
        return None
    txt = str(value).strip()
    if txt == "" or txt.lower() == "nan":
        return None
    try:
        return float(txt)
    except ValueError:
        return None

# ── SMS editor ───────────────────────────────────────────────────────────────

def _render_sms_editor(orch, work_df: pd.DataFrame, sms_col: str, name_col: str, id_col: str):
    """Editable SMS table + pie chart side-by-side."""
    st.session_state.setdefault("supplier_sms_editor_rev", 0)

    sms_left, sms_right = st.columns([3.5, 1.5])

    with sms_left:
        st.markdown("##### Strategic Market Share")
        
        # Dynamically map to Snowflake schema
        #tbl = pd.DataFrame({
        #    "SMS (%)": work_df[sms_col],
        #    "ID": work_df[id_col],
        #    "Name": work_df[name_col] if name_col in work_df.columns else "",
        #    "Initial MS": work_df["ALLOCATION_COMPLIANCE"] if "ALLOCATION_COMPLIANCE" in work_df.columns else np.nan,
        #    "Crews": work_df["CREW_CAPACITY"] if "CREW_CAPACITY" in work_df.columns else np.nan
        #    
        #})
        # Safely map to Snowflake schema handling the None risk
        tbl = pd.DataFrame({
            "SMS (%)": work_df[sms_col],
            "ID": work_df[id_col],
            "Name": work_df[name_col] if name_col and name_col in work_df.columns else "",
            "Initial MS": work_df.get("ALLOCATION_COMPLIANCE", np.nan),
            "Crews": work_df.get("CREW_CAPACITY", np.nan)
        })
        
        editor_key = f"sms_editor_{st.session_state['supplier_sms_editor_rev']}"
        edited = st.data_editor(
            tbl, hide_index=True, use_container_width=True,
            disabled=[c for c in tbl.columns if c != "SMS (%)"],
            column_config={"SMS (%)": st.column_config.NumberColumn(
                "SMS (%)", min_value=0.0, max_value=100.0, step=0.1), "ID": None},
            key=editor_key,
        )
        
        edited_sms = pd.to_numeric(edited["SMS (%)"], errors="coerce")
        total = float(edited_sms.fillna(0).sum())
        
        #if total <= 100.0 + 1e-9:
        #    cur = pd.to_numeric(work_df[sms_col], errors="coerce")
        #    if not edited_sms.fillna(-1).equals(cur.fillna(-1)):
        #        st.session_state["suppliers_editor_df"].loc[:, sms_col] = edited_sms.values
        #        work_df = st.session_state["suppliers_editor_df"]
        #        st.session_state["supplier_sms_editor_rev"] += 1
        #        st.rerun()
        if total <= 100.0 + 1e-9:
            cur = pd.to_numeric(work_df[sms_col], errors="coerce")
            # 🟢 FIX: Use a value-based mathematical comparison, not strict .equals()
            if not (edited_sms.fillna(-1) == cur.fillna(-1)).all():
                st.session_state["suppliers_editor_df"].loc[:, sms_col] = edited_sms.values
                work_df = st.session_state["suppliers_editor_df"]
                st.session_state["supplier_sms_editor_rev"] += 1
                st.rerun()
        else:
            st.error("🚨 SMS total exceeds 100%. Reduce values to continue.")

    with sms_right:
        st.markdown("##### SMS Distribution")
        
        # 🟢 OPTIMIZATION: Vectorized approach instead of iterrows()
        # 1. Clean the SMS column natively
        clean_sms = pd.to_numeric(work_df[sms_col], errors="coerce").fillna(0)
        sms_total = float(clean_sms.sum())
        
        # 2. Extract only valid slices (>0)
        valid_mask = clean_sms > 0
        
        # 3. Resolve the label (Fallback to ID if Name is missing)
        if name_col and name_col in work_df.columns:
            labels = work_df[name_col].fillna("").astype(str).str.strip()
            labels = np.where(labels == "", work_df[id_col].astype(str), labels)
        else:
            labels = work_df[id_col].astype(str)
            
        # 4. Build the pie DataFrame instantly
        pie_df = pd.DataFrame({
            "segment": labels[valid_mask],
            "sms_pct": clean_sms[valid_mask]
        })
        
        # 5. Add the "Open" allocation
        to_alloc = max(0.0, 100.0 - sms_total)
        pie_df = pd.concat([
            pie_df, 
            pd.DataFrame([{"segment": "Open", "sms_pct": to_alloc}])
        ], ignore_index=True)
                
        # Create the label text
        pie_df['slice_label'] = pie_df['sms_pct'].apply(lambda x: f"{x:.1f}%" if x > 4 else "")
        
    #with sms_right:
    #    st.markdown("##### SMS Distribution")
    #    pie_rows = []
    #    for _, r in work_df.iterrows():
    #        v = _parse_float(r[sms_col])
    #        if v and v > 0:
    #            label = str(r[name_col]).strip() if name_col in work_df.columns and not pd.isna(r[name_col]) and str(r[name_col]).strip() else str(r[id_col])
    #            pie_rows.append({"segment": label, "sms_pct": v})
    #            
    #    sms_total = float(pd.to_numeric(work_df[sms_col], errors="coerce").fillna(0).sum())
    #    to_alloc = max(0.0, 100.0 - sms_total)
    #    pie_df = pd.DataFrame(pie_rows + [{"segment": "Open", "sms_pct": to_alloc}])
    #           
    #    # 🟢 Create the label text (Hide labels for slices smaller than 4% to prevent overlap)
    #    pie_df['slice_label'] = pie_df['sms_pct'].apply(lambda x: f"{x:.1f}%" if x > 4 else "")

        if not pie_df.empty:
            # 1. BASE: Calculates the angles for both layers
            base = alt.Chart(pie_df).encode(
                theta=alt.Theta("sms_pct:Q", stack=True),
                order=alt.Order("sms_pct:Q", sort="descending") # 🟢 ALIGNS TEXT & SLICES
            )

            # 2. PIE LAYER & LEGEND: 
            pie = base.mark_arc(outerRadius=120).encode(
                color=alt.Color(
                    "segment:N", 
                    title="Supplier / Open", 
                    legend=alt.Legend(
                        orient="bottom", 
                        columns=2, 
                        labelLimit=100,  # 🟢 Forces truncation of long names
                        titleLimit=200   # 🟢 Keeps the title from stretching the container
                    )
                ),
                tooltip=[alt.Tooltip("segment:N"), alt.Tooltip("sms_pct:Q", format=".1f")]
            )

            # 3. TEXT LAYER: Handles the numbers. 
            text = base.mark_text(radius=80, size=14, fontWeight="bold", color="white").encode(
                text=alt.Text("slice_label:N")
            )

            # 4. LAYER THEM TOGETHER
            chart = (pie + text).properties(height=350)
            
            st.altair_chart(chart, use_container_width=True)

    m1, m2 = st.columns(2)
    with m1:
        st.metric("Total set SMS (%)", f"{sms_total:.1f}")
    with m2:
        st.metric("Open (%)", f"{to_alloc:.1f}")

    # 🚀 NATIVE SNOWFLAKE COMMIT LOGIC
    if st.button("Commit SMS edits to Snowflake", type="primary"):
        with st.spinner("Pushing Market Share to Snowflake..."):
            try:
                # 1. Isolate the payload (Keys + SMS)
                payload_df = work_df[[id_col, sms_col]].copy()
                
                # 2. Stage the data in Snowflake using orch
                orch.session.write_pandas(
                    df=payload_df, 
                    table_name="TEMP_SWA_SMS_STAGE", 
                    auto_create_table=True, table_type="transient", overwrite=True
                )
                
                # 3. Execute the Native MERGE using orch
                #merge_sql = f"""
                #    MERGE INTO SWA_SUPPLIERS AS tgt
                #    USING TEMP_SWA_SMS_STAGE AS src
                #      ON UPPER(TRIM(tgt.{id_col})) = UPPER(TRIM(src.{id_col}))
                #    WHEN MATCHED THEN 
                #      UPDATE SET 
                #        tgt.{sms_col} = src.{sms_col}
                #"""
                # 🟢 FIX: Double-quote all Snowflake identifiers to prevent syntax crashes
                merge_sql = f"""
                    MERGE INTO SWA_SUPPLIERS AS tgt
                    USING TEMP_SWA_SMS_STAGE AS src
                      ON UPPER(TRIM(tgt."{id_col}")) = UPPER(TRIM(src."{id_col}"))
                    WHEN MATCHED THEN 
                      UPDATE SET 
                        "{sms_col}" = src."{sms_col}"
                """
                st.code(merge_sql, language="sql")
                merge_result = orch.session.sql(merge_sql).collect()
                
                # 🟢 THE FIX: Safely parse the MERGE output
                # If Snowflake returns 1 column (Updates only), use index 0. If 2 columns, use index 1.
                if merge_result and len(merge_result) > 0:
                    row = merge_result[0]
                    rows_updated = row[0] if len(row) == 1 else row[1]
                else:
                    rows_updated = 0
                
                # Force a refresh of the cached data on next load
                if "suppliers_editor_signature" in st.session_state:
                    del st.session_state["suppliers_editor_signature"]
                    
                st.success(f"✅ Snowflake Upsert Complete! Updated SMS for {rows_updated} suppliers.")
            
            except Exception as e:
                st.error(f"🚨 Failed to update Snowflake: {e}")

# ── Weight sliders ───────────────────────────────────────────────────────────

def _render_weight_sliders() -> tuple[float, float, float]:
    """Three linked sliders that always sum to 1. Returns (w_cost, w_quality, w_distance)."""
    for k, v in [("w_cost", 1/3), ("w_quality", 1/3), ("w_distance", 1/3)]:
        st.session_state.setdefault(k, v)
    for k in ("lock_cost", "lock_quality", "lock_distance"):
        st.session_state.setdefault(k, False)
    for k in ("_prev_w_cost", "_prev_w_quality", "_prev_w_distance"):
        st.session_state.setdefault(k, st.session_state[k.replace("_prev_", "")])

    def _save_prev():
        for n in ("cost", "quality", "distance"):
            st.session_state[f"_prev_w_{n}"] = st.session_state[f"w_{n}"]

    def rebalance(changed: str):
        keys = ["cost", "quality", "distance"]
        w = {k: float(st.session_state[f"w_{k}"]) for k in keys}
        locked = {k: bool(st.session_state[f"lock_{k}"]) for k in keys}

        if locked[changed]:
            st.session_state[f"w_{changed}"] = st.session_state[f"_prev_w_{changed}"]
            return

        locked_sum = sum(w[k] for k in keys if locked[k] and k != changed)
        w[changed] = max(0.0, min(1.0 - locked_sum, w[changed]))
        remainder = max(0.0, 1.0 - locked_sum - w[changed])
        free = [k for k in keys if not locked[k] and k != changed]

        if free:
            free_sum = sum(w[k] for k in free)
            if free_sum <= 1e-12:
                for k in free:
                    w[k] = remainder / len(free)
            else:
                scale = remainder / free_sum
                for k in free:
                    w[k] *= scale

        for k in keys:
            w[k] = round(w[k], 3)
        delta = round(1.0 - sum(w.values()), 3)
        if abs(delta) > 1e-9:
            w[changed] = round(max(0.0, min(1.0, w[changed] + delta)), 3)

        for k in keys:
            st.session_state[f"w_{k}"] = w[k]
        _save_prev()

    def _row(title, wkey, lkey, name):
        left, right, _ = st.columns([6, 1, 7])
        with left:
            st.markdown(f"**{title}**")
            st.slider(title, 0.0, 1.0, step=0.01, key=wkey,
                      on_change=rebalance, kwargs={"changed": name},
                      label_visibility="collapsed")
        with right:
            icon = "🔒" if st.session_state.get(lkey) else "🔓"
            st.checkbox(icon, key=lkey, label_visibility="visible",
                        help="Lock this weight.")

    st.subheader("Objective Weighting")
    _row("Cost", "w_cost", "lock_cost", "cost")
    _row("Quality", "w_quality", "lock_quality", "quality")
    _row("Drive Distance", "w_distance", "lock_distance", "distance")
    _save_prev()

    st.caption(
        f"Weights → Cost: {st.session_state.w_cost:.2f}, "
        f"Quality: {st.session_state.w_quality:.2f}, "
        f"Distance: {st.session_state.w_distance:.2f} "
        f"(sum = {st.session_state.w_cost + st.session_state.w_quality + st.session_state.w_distance:.2f})"
    )
    return st.session_state.w_cost, st.session_state.w_quality, st.session_state.w_distance

# ── Public entry point ───────────────────────────────────────────────────────

def render_sms_and_weights(orch):
    st.header("Supplier SMS & Optimization Weights")

    try:
        # 🚀 Pulled natively from Snowflake using orch instead of API
        supp_df = orch.fetch_dynamic_table("SWA_SUPPLIERS", limit_rows=0)
    except Exception as e:
        st.error(f"Cannot reach Snowflake: {e}")
        return

    # Dynamically map the ID column
    id_col = _pick_first_col(supp_df, ["MUSID", "SUPPLIER_ID", "ID"])
    
    if supp_df.empty or id_col not in supp_df.columns:
        st.info("No suppliers loaded yet. Ensure SWA_SUPPLIERS has data in Snowflake.")
        return

    # Call helper functions directly without _self
    sms_col = _pick_first_col(supp_df, ["SMS_PCT", "TARGET_SMS", "STRATEGIC_MARKET_SHARE_PCT", "SMS", "ALLOCATION_COMPLIANCE"]) or "SMS_PCT"
    name_col = _pick_first_col(supp_df, ["SP_NAME", "SUPPLIER_NAME", "NAME"])

    ids = supp_df[id_col].astype(str).tolist()
    sig = (len(supp_df), "|".join(sorted(ids)))
    
    if "suppliers_editor_df" not in st.session_state or st.session_state.get("suppliers_editor_signature") != sig:
        work = supp_df.copy()
        
        # 1. Identify the source column we want to pull defaults from
        source_share_col = _pick_first_col(work, ["STRATEGIC_MARKET_SHARE", "STRATEGIC_MARKET_SHARE_PCT"])
        
        # 2. Apply the defaults safely
        if sms_col not in work.columns:
            if source_share_col:
                # Create the SMS column and fill it entirely with the strategic defaults
                work[sms_col] = work[source_share_col]
            else:
                # Fallback if neither exists
                work[sms_col] = np.nan 
        elif source_share_col:
            # If the SMS column exists but has missing data, fill the gaps with the strategic defaults
            work[sms_col] = work[sms_col].fillna(work[source_share_col])
            
        st.session_state["suppliers_editor_df"] = work
        st.session_state["suppliers_editor_signature"] = sig

    # Pass orch down into the editor so it can write back to Snowflake
    _render_sms_editor(orch, st.session_state["suppliers_editor_df"], sms_col, name_col, id_col)

    st.markdown("---")
    _render_weight_sliders()