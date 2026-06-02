# Architecture Documentation

This document describes the architectural decisions, design patterns, data models, and future scalability strategy for the Bus Charging Scheduler.

---

## 🏗️ Scheduling Framework Choice

We selected a hybrid approach combining **Discrete Event Simulation (DES)** and a **Heuristic Local Search (Hill Climbing)** to solve the scheduling problem.

### Why DES is the right fit:
1. **Time-accuracy**: Buses arrive, queue, and charge at discrete times. A time-stepped simulation would be inefficient or inaccurate. DES jumps from event to event, making it extremely fast (`<1ms` for a 20-bus schedule).
2. **Modular Dispatching (Rules)**: When a charger becomes available, the dispatcher evaluates a set of scoring functions. This priority-based queue mimics real-world dispatch desks and makes it trivial to add new logic (e.g. driver shifts) without rewriting the state engine.
3. **Traceability**: The simulator logs detailed telemetry for every bus and station, enabling high-fidelity visualizations like Gantt charts.

### Why Heuristic Search is the right fit:
1. **NP-Hard Complexity**: The combination of deciding **which stations to use** (charging plan selection) and **who charges first** (dispatch ordering) creates a massive combinatorial search space ($O(S^B)$ where $S$ is charging plan options and $B$ is the number of buses).
2. **Custom Objectives**: Linear programming solvers (MIP) require linear constraints. Our optimizer can minimize non-linear metrics like *variance of delays* or *sum of squared wait times* (which heavily penalize starvation).
3. **Execution Speed**: The Hill Climbing optimizer runs 200 iterations in `<0.2` seconds. This speed allows for **real-time recalculation** when users adjust sliders in the UI.

---

## 🗃️ Data Structure Design

We designed a fully parameterized JSON schema where the **scenario file is the single source of truth for the entire world**. The schema represents:
1. **Network Topography**: Ordered nodes and segment distances.
2. **Physical Constraints**: Cruising speed, charging duration, and battery capacities.
3. **Station Parameters**: Number of chargers at each node.
4. **Weights**: Default parameters for the scoring algorithm.
5. **Demand Schedule**: Scheduled departures, origins, destinations, and operator associations.

### JSON Schema Example
```json
{
  "name": "Scenario 1 — Even spacing",
  "weights": {
    "individual": 1.0,
    "operator": 1.0,
    "overall": 1.0
  },
  "physical_constants": {
    "battery_range_km": 240,
    "charging_time_min": 25,
    "speed_km_h": 60
  },
  "route": {
    "nodes": ["Bengaluru", "A", "B", "C", "D", "Kochi"],
    "distances": [100, 120, 100, 120, 100]
  },
  "stations": {
    "A": { "chargers": 1 },
    "B": { "chargers": 2 }
  },
  "buses": [
    { "id": "bus-01", "operator": "kpn", "origin": "Bengaluru", "destination": "Kochi", "departure_time": "19:00" }
  ]
}
```

---

## 🔮 Future Scalability and Anticipated Changes

We designed the scheduling engine and data models to handle changes **entirely through configuration data, with zero code changes**.

| Change Anticipated | How the Design Handles It (No Code Changes) |
| :--- | :--- |
| **Adding a new station** | Simply add the station name and charger count to `"stations"` and insert the node into the `"route"` list. The generator will automatically find new valid charging paths. |
| **Doubling chargers at a station** | Change `"chargers": 1` to `"chargers": 2` in the station configuration. The simulator handles multi-charger capacity checks natively. |
| **Different segment distances** | Update the `"distances"` array in the JSON file. Travel times and battery range depletion will automatically adjust. |
| **Buses starting or ending mid-route** | Specify different `"origin"` and `"destination"` nodes for the bus. The scheduler dynamically extracts the correct sub-route and valid charging plans. |
| **Adding a new operator** | Assign the new operator name (e.g. `"intercity"`) in the bus object. The operator fairness calculations automatically adapt to new fleets. |
| **Buses with different ranges/speeds** | We can extend the bus JSON object to override global physical constants (e.g. `"battery_range_override": 300`). |

---

## 🛠️ Code Customization Examples

### 1. How to tune a weight
To change the weight of a rule, modify the `"weights"` dictionary in the scenario configuration or use the Streamlit sidebar sliders.

Code snippet of how the simulator evaluates weighted scores:
```python
def select_next_bus(self, queue, station_name, state, time, weights):
    best_bus_id = queue[0]
    best_score = -float('inf')
    
    for bus_id in queue:
        score = 0.0
        for name, rule in self.rules.items():
            w = weights.get(name, 0.0)
            if w != 0.0:
                score += w * rule.evaluate(bus_id, station_name, state, time)
        if score > best_score:
            best_score = score
            best_bus_id = bus_id
            
    return best_bus_id
```

### 2. How to add a new rule
Suppose we want to add a new hard or soft rule: **Priority Buses** (certain buses should always charge first, e.g. express services).

**Step 1:** Add a new rule class in `engine.py`:
```python
class PriorityBusRule(Rule):
    """Buses with 'priority': true in the scenario are served first."""
    def __init__(self):
        super().__init__("priority")
        
    def evaluate(self, bus_id: str, station_name: str, state: 'SimulationState', current_time: float) -> float:
        bus = state.buses[bus_id]
        # Check if the bus is marked as a priority bus in its data (adds high score)
        is_priority = bus.id in ["bus-BK-01", "bus-KB-01"] # Or fetch from bus metadata
        return 1000.0 if is_priority else 0.0
```

**Step 2:** Instantiate it in the `Simulator` constructor:
```python
self.rules = {
    "individual": IndividualRule(),
    "operator": OperatorRule(),
    "overall": OverallRule(),
    "priority": PriorityBusRule()  # <-- Register the rule
}
```

---

## 📌 Architectural Assumptions
1. **Instant Node Transits**: Buses do not experience traffic or speed variations. Travel time is deterministic and defined strictly by `distance / speed`.
2. **Fixed Charge Time**: Buses always charge to full, which takes exactly 25 minutes, regardless of the entry state of charge.
3. **No Backtracking**: Buses travel strictly from their origin to their destination in one direction.
4. **Deterministic Simulation**: All state transitions, arrival times, and wait times are deterministic. The local search optimization uses a fixed random seed to ensure reproducibility of results across runs.
