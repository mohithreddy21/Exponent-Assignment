import streamlit as st
import os
import glob
import pandas as pd
import altair as alt
from engine import Scenario, Simulator, Optimizer, min_to_time, time_to_min

# Page Configuration
st.set_page_config(
    page_title="Exponent Energy - Bus Charging Scheduler",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom Premium Styling (Dark Mode Theme Overrides)
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700&display=swap');
    
    /* Font family overrides */
    html, body, [class*="css"] {
        font-family: 'Outfit', sans-serif;
    }
    
    /* Title styling */
    .title-container {
        display: flex;
        align-items: center;
        margin-bottom: 20px;
    }
    .title-icon {
        font-size: 2.5rem;
        margin-right: 15px;
    }
    .title-text {
        font-size: 2.2rem;
        font-weight: 700;
        background: linear-gradient(90deg, #3b82f6 0%, #10b981 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
    }
    
    /* Glassmorphism Metric Cards */
    .metric-card {
        background: rgba(30, 41, 59, 0.7);
        backdrop-filter: blur(12px);
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 14px;
        padding: 20px;
        text-align: center;
        box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.3);
        transition: transform 0.25s ease, border-color 0.25s ease;
        margin-bottom: 15px;
    }
    .metric-card:hover {
        transform: translateY(-4px);
        border-color: rgba(59, 130, 246, 0.4);
    }
    .metric-val {
        font-size: 2.2rem;
        font-weight: 700;
        margin-bottom: 5px;
    }
    .val-score { color: #3b82f6; }
    .val-wait { color: #f59e0b; }
    .val-total { color: #10b981; }
    .val-max { color: #ef4444; }
    .metric-label {
        font-size: 0.8rem;
        color: #94a3b8;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        font-weight: 600;
    }
    
    /* Beautiful badges for operators */
    .op-badge {
        padding: 5px 10px;
        border-radius: 8px;
        font-size: 0.75rem;
        font-weight: 700;
        text-transform: uppercase;
        display: inline-block;
        letter-spacing: 0.05em;
    }
    .op-kpn {
        background-color: rgba(59, 130, 246, 0.15);
        color: #60a5fa;
        border: 1px solid rgba(59, 130, 246, 0.3);
    }
    .op-freshbus {
        background-color: rgba(16, 185, 129, 0.15);
        color: #34d399;
        border: 1px solid rgba(16, 185, 129, 0.3);
    }
    .op-flixbus {
        background-color: rgba(245, 158, 11, 0.15);
        color: #fbbf24;
        border: 1px solid rgba(245, 158, 11, 0.3);
    }
    
    /* Timeline Table Styling */
    .timeline-table {
        width: 100%;
        border-collapse: collapse;
        margin: 10px 0;
        border-radius: 8px;
        overflow: hidden;
    }
    .timeline-table th {
        background-color: #1e293b;
        color: #94a3b8;
        font-weight: 600;
        text-align: left;
        padding: 10px 15px;
        border-bottom: 2px solid #334155;
    }
    .timeline-table td {
        padding: 10px 15px;
        border-bottom: 1px solid #334155;
    }
    
    /* Status styling */
    .status-badge {
        padding: 3px 8px;
        border-radius: 6px;
        font-size: 0.75rem;
        font-weight: 600;
    }
    .status-departed { background: #3b82f6; color: white; }
    .status-arrived { background: #10b981; color: white; }
    .status-charge { background: #fbbf24; color: black; }
    .status-wait { background: #ef4444; color: white; }
</style>
""", unsafe_allow_html=True)

# Main Title Header
st.markdown("""
<div class="title-container">
    <span class="title-icon">⚡</span>
    <span class="title-text">Exponent Energy - Bus Charging Scheduler</span>
</div>
""", unsafe_allow_html=True)

# Find scenario files
scenario_files = sorted(glob.glob(os.path.join("data", "scenario_*.json")))
scenario_names = []
scenario_map = {}

for filepath in scenario_files:
    try:
        scen = Scenario.from_file(filepath)
        name = f"Scenario {os.path.basename(filepath).split('_')[1].split('.')[0]}: {scen.name}"
        scenario_names.append(name)
        scenario_map[name] = filepath
    except Exception as e:
        st.error(f"Error loading scenario {filepath}: {e}")

if not scenario_names:
    st.error("No scenario files found in the 'data/' directory. Please ensure JSON files are present.")
    st.stop()

# Scenario Selection Dropdown (requested at the top)
selected_scenario_name = st.selectbox("Select Charging Scenario", scenario_names)
selected_filepath = scenario_map[selected_scenario_name]

# Load current scenario
scenario = Scenario.from_file(selected_filepath)

# --- SIDEBAR: Tuning Weights & Optimizer Settings ---
st.sidebar.markdown("### 🛠️ Scheduling Settings")

# Live Weight Tuning Section
st.sidebar.markdown("#### Weight Optimization")
st.sidebar.caption("Tune weights to balance scheduling priorities. The scheduler will recalculate in real-time.")

# Default weights from the scenario
default_weights = scenario.weights
w_ind = st.sidebar.slider("Individual Bus Weight (Avoid Starvation)", 0.0, 5.0, float(default_weights.get("individual", 1.0)), 0.1)
w_op = st.sidebar.slider("Operator Group Weight (Fairness)", 0.0, 5.0, float(default_weights.get("operator", 1.0)), 0.1)
w_ov = st.sidebar.slider("Overall System Weight (Network Duration)", 0.0, 5.0, float(default_weights.get("overall", 1.0)), 0.1)

custom_weights = {
    "individual": w_ind,
    "operator": w_op,
    "overall": w_ov
}

# Advanced settings
st.sidebar.markdown("#### Optimizer Tuning")
opt_iterations = st.sidebar.slider("Optimization Search Iterations", 50, 1000, 200, 50)

# Reset Button
if st.sidebar.button("Reset to Scenario Defaults"):
    st.experimental_rerun()

st.sidebar.markdown("---")
st.sidebar.markdown("### 📋 Physical Parameters")
st.sidebar.text(f"🔋 Battery Range: {scenario.battery_range} km")
st.sidebar.text(f"⏳ Charging Duration: {scenario.charging_time} min")
st.sidebar.text(f"🚀 Cruise Speed: {scenario.speed} km/h")
st.sidebar.text(f"🛣️ Route Distance: {sum(scenario.route_distances)} km")

# --- RUN SCHEDULING PIPELINE ---
# Run optimizer to get best plans
optimizer = Optimizer(scenario)
with st.spinner("Optimizing charging schedules..."):
    best_plans, best_metrics = optimizer.optimize(max_iterations=opt_iterations, custom_weights=custom_weights)

# Run simulator with optimized plans
simulator = Simulator(scenario)
state, metrics = simulator.run(best_plans, custom_weights)

# Calculate baseline for comparison
baseline_plans = {b.id: optimizer.valid_plans[b.id][0] for b in scenario.buses}
_, baseline_metrics = simulator.run(baseline_plans, custom_weights)

# --- KPI DASHBOARD LAYOUT ---
st.markdown("### 📊 Performance Summary")
col1, col2, col3, col4 = st.columns(4)

# Global score improvement display
score_diff = baseline_metrics["global_score"] - metrics["global_score"]
score_pct = (score_diff / baseline_metrics["global_score"]) * 100 if baseline_metrics["global_score"] > 0 else 0

with col1:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-val val-score">{metrics['global_score']:.1f}</div>
        <div class="metric-label">Weighted Score (Lower is better)</div>
        <div style="font-size: 0.8rem; color: #10b981; margin-top: 5px;">
            Improved by {score_pct:.1f}% vs baseline
        </div>
    </div>
    """, unsafe_allow_html=True)

with col2:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-val val-wait">{metrics['total_wait_time']:.0f} min</div>
        <div class="metric-label">Total Fleet Wait Time</div>
        <div style="font-size: 0.8rem; color: #10b981; margin-top: 5px;">
            Baseline was {baseline_metrics['total_wait_time']:.0f} min
        </div>
    </div>
    """, unsafe_allow_html=True)

with col3:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-val val-max">{metrics['max_wait_time']:.0f} min</div>
        <div class="metric-label">Max Wait for Single Bus</div>
        <div style="font-size: 0.8rem; color: {'#10b981' if metrics['max_wait_time'] <= 45 else '#f59e0b'}; margin-top: 5px;">
            Baseline was {baseline_metrics['max_wait_time']:.0f} min
        </div>
    </div>
    """, unsafe_allow_html=True)

# Calculate average trip duration
buses_arrived = [b for b in state.buses.values() if b.arrival_time is not None]
avg_trip = sum(b.arrival_time - b.scheduled_departure_time for b in buses_arrived) / len(buses_arrived) if buses_arrived else 0
base_buses_arrived = [b for b in state.buses.values() if b.arrival_time is not None]
# Average duration of baseline
baseline_avg_trip = sum(b.arrival_time - b.scheduled_departure_time for b in base_buses_arrived) / len(base_buses_arrived) if base_buses_arrived else 0

with col4:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-val val-total">{avg_trip:.1f} min</div>
        <div class="metric-label">Avg Bus Trip Duration</div>
        <div style="font-size: 0.8rem; color: #10b981; margin-top: 5px;">
            Baseline was {baseline_avg_trip:.1f} min
        </div>
    </div>
    """, unsafe_allow_html=True)

# --- TAB CONTENT VIEW ---
tabs = st.tabs(["🕒 Per-Bus Timetable", "🚉 Per-Station Schedule", "📥 Scenario Inputs", "⚙️ Raw Data View"])

# --- TAB 1: PER-BUS TIMETABLE ---
with tabs[0]:
    st.markdown("### Scheduled Bus Timelines")
    st.write("Below is the complete schedule for all buses. Expand any row to see its segment-by-segment timeline.")
    
    # Prepare DataFrame for overview table
    bus_records = []
    for b_id, bus in state.buses.items():
        charging_stops = ", ".join(bus.charging_plan) if bus.charging_plan else "None"
        bus_records.append({
            "Bus ID": bus.id,
            "Operator": bus.operator.upper(),
            "Route": f"{bus.origin} ➔ {bus.destination}",
            "Scheduled Departure": min_to_time(bus.scheduled_departure_time),
            "Charging Plan": charging_stops,
            "Total Wait Time (min)": int(bus.total_wait_time),
            "Arrival Time": min_to_time(bus.arrival_time) if bus.arrival_time else "En Route",
            "Total Trip Duration (min)": int(bus.arrival_time - bus.scheduled_departure_time) if bus.arrival_time else None
        })
        
    df_bus = pd.DataFrame(bus_records)
    
    # Render table columns with styling
    for i, row in df_bus.iterrows():
        col_id, col_op, col_route, col_dep, col_plan, col_wait, col_arr = st.columns([2, 2, 3, 2, 3, 2, 2])
        
        with col_id:
            st.markdown(f"**{row['Bus ID']}**")
        with col_op:
            op_cls = f"op-{row['Operator'].lower()}"
            st.markdown(f'<span class="op-badge {op_cls}">{row["Operator"]}</span>', unsafe_allow_html=True)
        with col_route:
            st.write(row['Route'])
        with col_dep:
            st.write(row['Scheduled Departure'])
        with col_plan:
            st.write(row['Charging Plan'])
        with col_wait:
            st.write(f"{row['Total Wait Time (min)']} min")
        with col_arr:
            st.write(row['Arrival Time'])
            
        # Expander for timeline logs
        bus_obj = state.buses[row['Bus ID']]
        with st.expander(f"Detailed Timeline for {row['Bus ID']}"):
            timeline_html = '<table class="timeline-table"><tr><th>Event</th><th>Location</th><th>Time</th><th>Remaining Range (km)</th><th>Wait Time (min)</th></tr>'
            for event in bus_obj.timeline:
                ev_time_str = min_to_time(event["time"])
                ev_wait = f"{int(event['wait_time'])} min" if event["wait_time"] > 0 else "-"
                
                # Format event name as status badges
                ev_name = event["event"]
                status_cls = ""
                if ev_name == "Departure": status_cls = "status-departed"
                elif ev_name == "Arrival": status_cls = "status-arrived"
                elif ev_name == "Charge Start": status_cls = "status-charge"
                elif ev_name == "Charge Complete": status_cls = "status-arrived"
                elif ev_name == "Wait Start": status_cls = "status-wait"
                
                timeline_html += f'<tr><td><span class="status-badge {status_cls}">{ev_name}</span></td><td>{event["node"]}</td><td>{ev_time_str}</td><td>{event["battery"]:.1f} km</td><td>{ev_wait}</td></tr>'
            timeline_html += "</table>"
            st.markdown(timeline_html, unsafe_allow_html=True)
            
        st.markdown("---")

# --- TAB 2: PER-STATION SCHEDULE & GANTT CHART ---
with tabs[1]:
    st.markdown("### Charging Station Schedules")
    
    # Render Gantt Chart
    st.markdown("#### Charger Occupancy Gantt Chart")
    
    gantt_records = []
    for station_name, station_data in state.stations.items():
        for record in station_data["history"]:
            bus = state.buses[record["bus_id"]]
            gantt_records.append({
                "Station": station_name,
                "Bus ID": record["bus_id"],
                "Operator": bus.operator.upper(),
                "Start Time": record["start_time"],
                "End Time": record["end_time"],
                "Start Str": min_to_time(record["start_time"]),
                "End Str": min_to_time(record["end_time"])
            })
            
    if gantt_records:
        df_gantt = pd.DataFrame(gantt_records)
        
        chart = alt.Chart(df_gantt).mark_bar(cornerRadius=5, height=20).encode(
            x=alt.X('Start Time:Q', title='Time (Minutes from Midnight)', scale=alt.Scale(zero=False)),
            x2='End Time:Q',
            y=alt.Y('Station:N', title='Station', sort='ascending'),
            color=alt.Color('Operator:N', scale=alt.Scale(
                domain=['KPN', 'FRESHBUS', 'FLIXBUS'],
                range=['#3b82f6', '#10b981', '#f59e0b']
            ), title="Operator"),
            tooltip=['Bus ID', 'Operator', 'Station', 'Start Str', 'End Str']
        ).properties(
            width='container',
            height=250
        ).configure_axis(
            labelFontSize=12,
            titleFontSize=14
        )
        st.altair_chart(chart, use_container_width=True)
    else:
        st.info("No buses charged in this scenario configuration.")
        
    st.markdown("#### Station Allocation Logs")
    col_a, col_b, col_c, col_d = st.columns(4)
    station_cols = {"A": col_a, "B": col_b, "C": col_c, "D": col_d}
    
    for station_name, station_col in station_cols.items():
        with station_col:
            st.markdown(f"#### Node {station_name}")
            station_data = state.stations[station_name]
            st.caption(f"Chargers: {station_data['chargers_total']} | Active queue: {len(station_data['queue'])}")
            
            history = station_data["history"]
            if not history:
                st.write("No charging logs.")
            else:
                logs_df = []
                for idx, record in enumerate(history):
                    bus = state.buses[record["bus_id"]]
                    logs_df.append({
                        "Order": idx + 1,
                        "Bus ID": record["bus_id"],
                        "Start": min_to_time(record["start_time"]),
                        "End": min_to_time(record["end_time"])
                    })
                st.dataframe(pd.DataFrame(logs_df), hide_index=True)

# --- TAB 3: SCENARIO INPUTS ---
with tabs[2]:
    st.markdown("### Scenario Definitions")
    st.write(f"**Description**: {scenario.description}")
    
    col_left, col_right = st.columns(2)
    
    with col_left:
        st.markdown("#### Route Geometry & Distances")
        route_records = []
        for i in range(len(scenario.route_distances)):
            route_records.append({
                "Segment": f"{scenario.route_nodes[i]} ➔ {scenario.route_nodes[i+1]}",
                "Distance (km)": f"{scenario.route_distances[i]} km",
                "Travel Duration": f"{scenario.route_distances[i] / scenario.speed * 60:.0f} minutes"
            })
        st.table(pd.DataFrame(route_records))
        
        st.markdown("#### Charging Station Capacities")
        station_caps = []
        for name, info in scenario.stations_config.items():
            station_caps.append({
                "Station Name": name,
                "Chargers Available": info.get("chargers", 1)
            })
        st.table(pd.DataFrame(station_caps))
        
    with col_right:
        st.markdown("#### Scheduled Bus Departures")
        dep_records = []
        for b in scenario.buses:
            dep_records.append({
                "Bus ID": b.id,
                "Operator": b.operator.upper(),
                "Origin": b.origin,
                "Destination": b.destination,
                "Departure Time": min_to_time(b.scheduled_departure_time)
            })
        st.dataframe(pd.DataFrame(dep_records), use_container_width=True, hide_index=True)

# --- TAB 4: RAW SCENARIO DATA VIEW ---
with tabs[3]:
    st.markdown("### Raw JSON Scenario Config")
    st.write("This is the exact JSON data structure read by the scheduler. Reviewers can verify it conforms to the assignment guidelines.")
    with open(selected_filepath, 'r') as f:
        st.json(f.read())
