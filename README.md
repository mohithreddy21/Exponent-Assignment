# Bus Charging Scheduler

This is a Python + Streamlit application designed for scheduling and optimizing electric bus charging stations along a fixed transit route.

## 🚀 How to Run Locally

### 1. Prerequisites
Make sure you have Python 3.8+ installed on your system.

### 2. Install Dependencies
Install the required libraries listed in `requirements.txt`:
```bash
pip install -r requirements.txt
```

### 3. Launch the Application
Run the Streamlit development server:
```bash
streamlit run app.py
```
This will open the web app in your default browser at `http://localhost:8501`.

---

## ⚙️ How to Tune a Weight
Weights control the scheduling trade-offs between individual wait times, operator fleet fairness, and overall network travel time:

1. **Via the User Interface**:
   - Select a scenario from the dropdown.
   - Adjust the **Weight Optimization** sliders in the sidebar.
   - The scheduling engine will instantly recalculate and redraw the Gantt chart and timetables in real-time.

2. **Via Scenario Data Files**:
   - Open any scenario file (e.g., `data/scenario_1.json`).
   - Edit the `"weights"` dictionary:
     ```json
     "weights": {
       "individual": 1.5,
       "operator": 1.0,
       "overall": 2.0
     }
     ```
   - Restart the app or refresh the page to load the new defaults.

---

## 📝 How to Add a New Rule
Adding a new scheduling rule is designed to be highly modular and does not require modifying the simulation engine.

1. **Define the Rule**:
   Create a class in `engine.py` that inherits from `Rule` and implements the `evaluate` method:
   ```python
   class ElectricityCostRule(Rule):
       """Prioritize charging during low-tariff hours."""
       def __init__(self):
           super().__init__("electricity_cost")
           
       def evaluate(self, bus_id: str, station_name: str, state: 'SimulationState', current_time: float) -> float:
           # Get current hour (e.g. 19:30 is 19.5)
           hour = (current_time / 60.0) % 24
           # Peak hours: 17:00 to 22:00 (1020 min to 1320 min)
           is_peak = 17.0 <= hour <= 22.0
           
           # If it's peak hours, return a negative score to delay charging if possible
           return -50.0 if is_peak else 0.0
   ```

2. **Register the Rule**:
   Add the rule to the `Simulator`'s rule dictionary in `engine.py`:
   ```python
   class Simulator:
       def __init__(self, scenario: Scenario):
           self.scenario = scenario
           self.rules = {
               "individual": IndividualRule(),
               "operator": OperatorRule(),
               "overall": OverallRule(),
               "electricity_cost": ElectricityCostRule()  # <-- Add here
           }
   ```

3. **Define its Weight**:
   Add the weight in the scenario's `"weights"` dictionary (e.g. `electricity_cost: 1.0`) in your JSON files, or adjust it via the UI sidebar by adding a slider.
