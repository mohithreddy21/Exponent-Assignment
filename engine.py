import json
import heapq
import random
import math
from typing import List, Dict, Tuple, Any

# --- Time conversion helpers ---
def time_to_min(time_str: str) -> int:
    h, m = map(int, time_str.split(':'))
    return h * 60 + m

def min_to_time(minutes: float) -> str:
    minutes = int(round(minutes))
    h = (minutes // 60) % 24
    m = minutes % 60
    return f"{h:02d}:{m:02d}"


# --- Rule System ---
class Rule:
    """Base class for all scheduling rules used in the priority queue."""
    def __init__(self, name: str):
        self.name = name
    
    def evaluate(self, bus_id: str, station_name: str, state: 'SimulationState', current_time: float) -> float:
        raise NotImplementedError


class IndividualRule(Rule):
    """
    Individual bus rule: avoids long wait times.
    Score increases as the bus's wait time in the queue increases.
    """
    def __init__(self):
        super().__init__("individual")
        
    def evaluate(self, bus_id: str, station_name: str, state: 'SimulationState', current_time: float) -> float:
        bus = state.buses[bus_id]
        if bus.wait_start_time is None:
            return 0.0
        return float(current_time - bus.wait_start_time)


class OperatorRule(Rule):
    """
    Operator fleet rule: ensures smooth group running.
    Prioritizes buses of operators that have suffered more accumulated delay so far.
    This balances out delays across operator fleets.
    """
    def __init__(self):
        super().__init__("operator")
        
    def evaluate(self, bus_id: str, station_name: str, state: 'SimulationState', current_time: float) -> float:
        bus = state.buses[bus_id]
        op = bus.operator
        
        # Calculate average delay (total wait time + current wait time) of this operator's fleet
        delays = []
        for b in state.buses.values():
            if b.operator == op:
                d = b.total_wait_time
                if b.status == "WAITING" and b.wait_start_time is not None:
                    d += (current_time - b.wait_start_time)
                delays.append(d)
        
        return float(sum(delays) / len(delays)) if delays else 0.0


class OverallRule(Rule):
    """
    Overall system rule: keeps total network time low.
    Prioritizes buses that started earlier, clearing them from the system.
    """
    def __init__(self):
        super().__init__("overall")
        
    def evaluate(self, bus_id: str, station_name: str, state: 'SimulationState', current_time: float) -> float:
        bus = state.buses[bus_id]
        # Prioritize buses that departed the earliest
        return float(current_time - bus.scheduled_departure_time)


# --- Simulation Data Models ---
class SimBus:
    def __init__(self, bus_id: str, operator: str, origin: str, destination: str, departure_time_str: str):
        self.id = bus_id
        self.operator = operator
        self.origin = origin
        self.destination = destination
        self.scheduled_departure_time = time_to_min(departure_time_str)
        self.charging_plan = []  # List of station names where the bus will charge
        
        # State variables (reset before simulation)
        self.status = "NOT_DEPARTED"  # NOT_DEPARTED, EN_ROUTE, WAITING, CHARGING, ARRIVED
        self.current_node_idx = 0
        self.current_battery = 0.0
        self.wait_start_time = None
        self.total_wait_time = 0.0
        self.arrival_time = None
        self.timeline = []  # Log of events: {"event": str, "node": str, "time": float, "battery": float, "wait_time": float}

    def reset(self, initial_battery: float):
        self.status = "NOT_DEPARTED"
        self.current_node_idx = 0
        self.current_battery = initial_battery
        self.wait_start_time = None
        self.total_wait_time = 0.0
        self.arrival_time = None
        self.timeline = []


class SimulationState:
    def __init__(self, buses: List[SimBus], stations_config: Dict[str, Any], route_nodes: List[str], route_distances: List[float], speed_km_h: float, battery_range: float, charging_time: float):
        self.buses = {b.id: b for b in buses}
        self.route_nodes = route_nodes
        self.route_distances = route_distances
        self.speed_km_h = speed_km_h
        self.battery_range = battery_range
        self.charging_time = charging_time
        
        # Station state maps
        self.stations = {}
        for name, info in stations_config.items():
            self.stations[name] = {
                "chargers_total": info.get("chargers", 1),
                "chargers_busy": 0,
                "queue": [],  # List of bus IDs
                "history": []  # List of dicts: {"bus_id": str, "start_time": float, "end_time": float}
            }

    def get_bus_route(self, bus: SimBus) -> Tuple[List[str], List[float]]:
        """Returns the specific sub-route nodes and segment distances for the bus."""
        idx_orig = self.route_nodes.index(bus.origin)
        idx_dest = self.route_nodes.index(bus.destination)
        if idx_orig < idx_dest:
            nodes = self.route_nodes[idx_orig : idx_dest + 1]
            distances = self.route_distances[idx_orig : idx_dest]
        else:
            nodes = list(reversed(self.route_nodes[idx_dest : idx_orig + 1]))
            distances = list(reversed(self.route_distances[idx_dest : idx_orig]))
        return nodes, [float(d) for d in distances]


# --- Scenario Representation ---
class Scenario:
    def __init__(self, config_data: Dict[str, Any]):
        self.name = config_data["name"]
        self.description = config_data.get("description", "")
        self.weights = config_data.get("weights", {"individual": 1.0, "operator": 1.0, "overall": 1.0})
        
        pc = config_data["physical_constants"]
        self.battery_range = float(pc["battery_range_km"])
        self.charging_time = float(pc["charging_time_min"])
        self.speed = float(pc["speed_km_h"])
        
        self.route_nodes = config_data["route"]["nodes"]
        self.route_distances = [float(d) for d in config_data["route"]["distances"]]
        
        self.stations_config = config_data["stations"]
        
        self.buses = []
        for b in config_data["buses"]:
            self.buses.append(
                SimBus(
                    bus_id=b["id"],
                    operator=b["operator"],
                    origin=b["origin"],
                    destination=b["destination"],
                    departure_time_str=b["departure_time"]
                )
            )

    @classmethod
    def from_file(cls, filepath: str) -> 'Scenario':
        with open(filepath, 'r') as f:
            data = json.load(f)
        return cls(data)


# --- Plan Generator & Validator ---
def validate_plan(route_nodes: List[str], route_distances: List[float], plan: List[str], battery_range: float) -> bool:
    """Validates if a charging plan is physically feasible (never runs out of range)."""
    battery = battery_range
    for i in range(len(route_distances)):
        dist = route_distances[i]
        battery -= dist
        if battery < 0:
            return False
        
        # If the arrival node is in the plan, charge the battery to full
        next_node = route_nodes[i + 1]
        if next_node in plan:
            battery = battery_range
            
    return True


def get_all_subsets(lst: List[Any]) -> List[List[Any]]:
    if not lst:
        return [[]]
    first = lst[0]
    rest = get_all_subsets(lst[1:])
    return rest + [[first] + r for r in rest]


def generate_valid_plans(route_nodes: List[str], route_distances: List[float], stations: List[str], battery_range: float) -> List[List[str]]:
    """Generates all possible valid charging station subsets for a given route."""
    # Find stations that are physically on the route (excluding endpoints)
    route_stations = [n for n in route_nodes[1:-1] if n in stations]
    subsets = get_all_subsets(route_stations)
    
    valid = []
    for subset in subsets:
        if validate_plan(route_nodes, route_distances, subset, battery_range):
            # Sort subset based on route occurrence order
            ordered_subset = [n for n in route_stations if n in subset]
            valid.append(ordered_subset)
            
    # Sort plans by number of charges (fewer charges first)
    valid.sort(key=len)
    return valid


# --- DES Simulator Engine ---
class Simulator:
    def __init__(self, scenario: Scenario):
        self.scenario = scenario
        self.rules = {
            "individual": IndividualRule(),
            "operator": OperatorRule(),
            "overall": OverallRule()
        }

    def run(self, charging_plans: Dict[str, List[str]], custom_weights: Dict[str, float] = None) -> Tuple[SimulationState, Dict[str, Any]]:
        """
        Runs a discrete event simulation of the schedule using the specified charging plans.
        Uses custom priority weights if provided, otherwise defaults to scenario weights.
        """
        weights = custom_weights if custom_weights is not None else self.scenario.weights
        
        # Initialize Simulation State
        state = SimulationState(
            buses=[SimBus(b.id, b.operator, b.origin, b.destination, min_to_time(b.scheduled_departure_time)) for b in self.scenario.buses],
            stations_config=self.scenario.stations_config,
            route_nodes=self.scenario.route_nodes,
            route_distances=self.scenario.route_distances,
            speed_km_h=self.scenario.speed,
            battery_range=self.scenario.battery_range,
            charging_time=self.scenario.charging_time
        )
        
        # Apply charging plans
        for b_id, plan in charging_plans.items():
            state.buses[b_id].charging_plan = plan
            state.buses[b_id].reset(state.battery_range)
            
        # Event Queue (heap)
        # Event structure: (time, event_type, bus_id, node_idx)
        # Using string comparisons of event_type as tie-breaker
        events = []
        
        for b in state.buses.values():
            heapq.heappush(events, (float(b.scheduled_departure_time), "DEPARTURE", b.id, 0))
            
        # Run loop
        while events:
            time, event_type, bus_id, node_idx = heapq.heappop(events)
            bus = state.buses[bus_id]
            route_nodes, route_distances = state.get_bus_route(bus)
            
            if event_type == "DEPARTURE":
                bus.status = "EN_ROUTE"
                bus.timeline.append({
                    "event": "Departure",
                    "node": route_nodes[0],
                    "time": time,
                    "battery": bus.current_battery,
                    "wait_time": 0.0
                })
                # Travel to next node (index 1)
                dist = route_distances[0]
                travel_time = (dist / state.speed_km_h) * 60.0
                bus.current_node_idx = 0
                heapq.heappush(events, (time + travel_time, "ARRIVE", bus_id, 1))
                
            elif event_type == "ARRIVE":
                bus.current_node_idx = node_idx
                node_name = route_nodes[node_idx]
                
                # Consume battery for the segment traveled
                dist = route_distances[node_idx - 1]
                bus.current_battery -= dist
                
                bus.timeline.append({
                    "event": "Arrival",
                    "node": node_name,
                    "time": time,
                    "battery": bus.current_battery,
                    "wait_time": 0.0
                })
                
                # Check if it's the destination
                if node_idx == len(route_nodes) - 1:
                    bus.status = "ARRIVED"
                    bus.arrival_time = time
                else:
                    # Station node: check if charging is scheduled
                    if node_name in bus.charging_plan:
                        bus.status = "WAITING"
                        bus.wait_start_time = time
                        bus.timeline.append({
                            "event": "Wait Start",
                            "node": node_name,
                            "time": time,
                            "battery": bus.current_battery,
                            "wait_time": 0.0
                        })
                        # Request charging
                        self._request_charge(bus.id, node_name, time, node_idx, state, events)
                    else:
                        # Bypass node
                        dist = route_distances[node_idx]
                        travel_time = (dist / state.speed_km_h) * 60.0
                        heapq.heappush(events, (time + travel_time, "ARRIVE", bus_id, node_idx + 1))
                        
            elif event_type == "CHARGE_COMPLETE":
                node_name = route_nodes[node_idx]
                bus.timeline.append({
                    "event": "Charge Complete",
                    "node": node_name,
                    "time": time,
                    "battery": bus.current_battery,
                    "wait_time": 0.0
                })
                # Release charger and potentially schedule next bus
                self._release_charger(bus.id, node_name, time, state, events, weights)
                
                # Travel to next node
                dist = route_distances[node_idx]
                travel_time = (dist / state.speed_km_h) * 60.0
                heapq.heappush(events, (time + travel_time, "ARRIVE", bus.id, node_idx + 1))
                
        # Post-simulation metric calculations
        metrics = self._calculate_metrics(state, weights)
        return state, metrics

    def _request_charge(self, bus_id: str, station_name: str, time: float, node_idx: int, state: SimulationState, events: list):
        station = state.stations[station_name]
        bus = state.buses[bus_id]
        
        if station["chargers_busy"] < station["chargers_total"]:
            station["chargers_busy"] += 1
            bus.status = "CHARGING"
            bus.timeline.append({
                "event": "Charge Start",
                "node": station_name,
                "time": time,
                "battery": bus.current_battery,
                "wait_time": 0.0
            })
            # Battery is instantly charged to full at charge end
            bus.current_battery = state.battery_range
            heapq.heappush(events, (time + state.charging_time, "CHARGE_COMPLETE", bus_id, node_idx))
            station["history"].append({
                "bus_id": bus_id,
                "start_time": time,
                "end_time": time + state.charging_time
            })
        else:
            station["queue"].append(bus_id)

    def _release_charger(self, bus_id: str, station_name: str, time: float, state: SimulationState, events: list, weights: Dict[str, float]):
        station = state.stations[station_name]
        
        if not station["queue"]:
            station["chargers_busy"] -= 1
        else:
            # Select the next bus from the queue using priority weights
            next_bus_id = self._select_next_bus(station["queue"], station_name, state, time, weights)
            station["queue"].remove(next_bus_id)
            
            next_bus = state.buses[next_bus_id]
            next_bus.status = "CHARGING"
            wait_duration = time - next_bus.wait_start_time
            next_bus.total_wait_time += wait_duration
            
            # Record wait duration in the wait start event log retroactively
            for log in reversed(next_bus.timeline):
                if log["event"] == "Wait Start" and log["node"] == station_name:
                    log["wait_time"] = wait_duration
                    break
            
            next_bus.timeline.append({
                "event": "Charge Start",
                "node": station_name,
                "time": time,
                "battery": next_bus.current_battery,
                "wait_time": 0.0
            })
            next_bus.current_battery = state.battery_range
            
            heapq.heappush(events, (time + state.charging_time, "CHARGE_COMPLETE", next_bus_id, next_bus.current_node_idx))
            station["history"].append({
                "bus_id": next_bus_id,
                "start_time": time,
                "end_time": time + state.charging_time
            })

    def _select_next_bus(self, queue: List[str], station_name: str, state: SimulationState, time: float, weights: Dict[str, float]) -> str:
        """Selects the bus with the highest weighted priority score from the queue."""
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

    def _calculate_metrics(self, state: SimulationState, weights: Dict[str, float]) -> Dict[str, Any]:
        buses = list(state.buses.values())
        num_buses = len(buses)
        
        if num_buses == 0:
            return {"individual": 0.0, "operator": 0.0, "overall": 0.0, "global_score": 0.0}
            
        # Individual Delay: Mean squared wait time (penalizes starvation)
        sum_squared_wait = sum(b.total_wait_time ** 2 for b in buses)
        m_individual = sum_squared_wait / num_buses
        
        # Overall Delay: Average trip duration (arrival - departure)
        total_trip_durations = sum(b.arrival_time - b.scheduled_departure_time for b in buses if b.arrival_time is not None)
        m_overall = total_trip_durations / num_buses
        
        # Operator fleet smoothness and fairness
        # Calculate trip delay (trip duration - free flow travel time) for each bus
        free_flow_time = (sum(state.route_distances) / state.speed_km_h) * 60.0
        
        op_delays = {}
        for b in buses:
            if b.arrival_time is not None:
                delay = (b.arrival_time - b.scheduled_departure_time) - free_flow_time
                op_delays.setdefault(b.operator, []).append(delay)
                
        # Variance of average delays between operators (fairness)
        op_averages = []
        op_variances = []
        for op, delays in op_delays.items():
            avg = sum(delays) / len(delays)
            op_averages.append(avg)
            if len(delays) > 1:
                mean_d = sum(delays) / len(delays)
                var = sum((d - mean_d) ** 2 for d in delays) / (len(delays) - 1)
                op_variances.append(var)
            else:
                op_variances.append(0.0)
                
        if len(op_averages) > 1:
            mean_a = sum(op_averages) / len(op_averages)
            between_op_variance = sum((a - mean_a) ** 2 for a in op_averages) / (len(op_averages) - 1)
        else:
            between_op_variance = 0.0
            
        mean_within_op_variance = sum(op_variances) / len(op_variances) if op_variances else 0.0
        m_operator = between_op_variance + mean_within_op_variance
        
        # Global Score
        w_ind = weights.get("individual", 1.0)
        w_op = weights.get("operator", 1.0)
        w_ov = weights.get("overall", 1.0)
        
        global_score = w_ind * m_individual + w_op * m_operator + w_ov * m_overall
        
        return {
            "individual_metric": m_individual,
            "operator_metric": m_operator,
            "overall_metric": m_overall,
            "global_score": global_score,
            "max_wait_time": max(b.total_wait_time for b in buses),
            "total_wait_time": sum(b.total_wait_time for b in buses)
        }


# --- Heuristic Local Search Optimizer ---
class Optimizer:
    def __init__(self, scenario: Scenario):
        self.scenario = scenario
        self.simulator = Simulator(scenario)
        
        # Generate valid charging plans for each bus
        self.valid_plans = {}
        for b in scenario.buses:
            # Reconstruct the route nodes and distances for this bus
            idx_orig = scenario.route_nodes.index(b.origin)
            idx_dest = scenario.route_nodes.index(b.destination)
            if idx_orig < idx_dest:
                nodes = scenario.route_nodes[idx_orig : idx_dest + 1]
                distances = scenario.route_distances[idx_orig : idx_dest]
            else:
                nodes = list(reversed(scenario.route_nodes[idx_dest : idx_orig + 1]))
                distances = list(reversed(scenario.route_distances[idx_dest : idx_orig]))
                
            self.valid_plans[b.id] = generate_valid_plans(
                nodes,
                distances,
                list(scenario.stations_config.keys()),
                scenario.battery_range
            )

    def optimize(self, max_iterations: int = 200, custom_weights: Dict[str, float] = None) -> Tuple[Dict[str, List[str]], Dict[str, Any]]:
        """
        Runs a hill climbing local search to find the configuration of charging plans
        that minimizes the global score metric.
        """
        # Initial config: choose the plan with minimum charges for each bus (baseline)
        current_config = {}
        for b_id, plans in self.valid_plans.items():
            current_config[b_id] = plans[0]  # Plans are sorted by length, so plans[0] is the minimum charge plan
            
        # Run baseline simulation
        _, current_metrics = self.simulator.run(current_config, custom_weights)
        current_score = current_metrics["global_score"]
        
        best_config = dict(current_config)
        best_score = current_score
        best_metrics = current_metrics
        
        # Hill climbing loop
        random.seed(42)  # For deterministic execution / reproducibility
        for _ in range(max_iterations):
            # Select a random bus
            bus_id = random.choice(list(self.valid_plans.keys()))
            plans = self.valid_plans[bus_id]
            
            if len(plans) <= 1:
                continue
                
            # Pick a new plan at random from the candidate list
            old_plan = current_config[bus_id]
            new_plan = random.choice([p for p in plans if p != old_plan])
            
            # Propose new config
            current_config[bus_id] = new_plan
            
            # Evaluate new config
            _, new_metrics = self.simulator.run(current_config, custom_weights)
            new_score = new_metrics["global_score"]
            
            # If the score improves, accept it
            if new_score < best_score:
                best_score = new_score
                best_config = dict(current_config)
                best_metrics = new_metrics
            else:
                # Revert change
                current_config[bus_id] = old_plan
                
        return best_config, best_metrics
