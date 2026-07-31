import streamlit as st
import pandas as pd
from typing import List, Any
from datetime import date
from dateutil.relativedelta import relativedelta

def calculate_relative_date(direction: str, count: int, grain: str):
    """
    Calculates a start and end date based on user selection.
    Returns a sorted list of [start_date, end_date].
    """
    end_dt = date.today()
    multiplier = -1 if direction == "Last" else 1
    
    if grain == "Months":
        offset = relativedelta(months=count * multiplier)
    elif grain == "Quarters":
        offset = relativedelta(months=(count * 3) * multiplier)
    else:
        offset = relativedelta(days=0)
        
    start_dt = end_dt + offset
    # Return as a sorted list for Streamlit date_input compatibility
    return sorted([start_dt, end_dt])
    
def fmt_list(filters: dict, key: str) -> str:
    vals = filters.get(key, [])
    return ", ".join(vals) if vals else "*N/A*"

def display_item(icon: str, label: str, value: str) -> None:
    st.markdown(
        f"<div style='font-size: 0.9em; margin-bottom: 6px;'>"
        f"<b>{icon} {label}:</b> {value}"
        f"</div>", 
        unsafe_allow_html=True
    )

def format_date_range(date_range: tuple) -> str:
    if len(date_range) == 2:
        return f"{date_range[0]} to {date_range[1]}"
    return "Incomplete"
            
def color_savings_by_rank(row):
    val = row["SAVING_FR_CURR"]
    rank = row["SP_RANK"]
                
    # Default: no styling for any column
    styles = [""] * len(row)
                
    # Find the index of SAVING_FR_CURR in the row
    col_idx = row.index.get_loc("SAVING_FR_CURR")
                
    if pd.isna(val):
        return styles
                
    # Darker for ranks 1-2, lighter for 3-4, lightest for 5+
    if val < 0:
        if rank <= 2:
            styles[col_idx] = "background-color: #2E8B57; color: white"   # dark green
        elif rank <= 4:            
            styles[col_idx] = "background-color: #90EE90; color: black"   # medium green
        else:
            styles[col_idx] = "background-color: #D0F5D0; color: black"   # light green
    elif val > 0:
        #if rank <= 2:
        #    styles[col_idx] = "background-color: #CD5C5C; color: white"   # dark red
        #elif rank <= 4:
        styles[col_idx] = "background-color: #FFB6C1; color: black"   # medium red
    #else:
        #    styles[col_idx] = "background-color: #FFE4E8; color: black"   # light red
                
    return styles
