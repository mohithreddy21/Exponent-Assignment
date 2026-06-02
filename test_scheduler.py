import os
import sys
from engine import Scenario, Simulator, Optimizer, min_to_time, time_to_min

def run_tests():
    scenario_dir = "data"
    scenarios = ["scenario_1.json", "scenario_2.json", "scenario_3.json", "scenario_4.json", "scenario_5.json"]
    
    all_passed = True
    
    for filename in scenarios:
        filepath = os.path.join(scenario_dir, filename)
        if not os.path.exists(filepath):
            print(f"[-] Scenario file {filepath} not found!")
            all_passed = False
            continue
            
        print(f"\n[+] Testing scenario: {filename}")
        
        # Load scenario
        scenario = Scenario.from_file(filepath)
        
        # Run optimizer
        optimizer = Optimizer(scenario)
        best_plans, best_metrics = optimizer.optimize(max_iterations=300)
        
        # Run simulation with best plans
        simulator = Simulator(scenario)
        state, metrics = simulator.run(best_plans)
        
        # --- TEST 1: Battery constraints ---
        battery_ok = True
        for bus_id, bus in state.buses.items():
            route_nodes, route_distances = state.get_bus_route(bus)
            
            # Trace battery level along the timeline
            curr_battery = state.battery_range
            node_idx = 0
            
            for event in bus.timeline:
                ev_type = event["event"]
                ev_node = event["node"]
                ev_time = event["time"]
                
                if ev_type == "Departure":
                    curr_battery = state.battery_range
                elif ev_type == "Arrival":
                    # Find segment distance to this node
                    prev_node = route_nodes[node_idx]
                    node_idx = route_nodes.index(ev_node)
                    segment_dist = sum(route_distances[route_nodes.index(prev_node) : node_idx])
                    curr_battery -= segment_dist
                    
                    if curr_battery < 0:
                        print(f"  [-] Bus {bus_id} ran out of battery at node {ev_node} (Battery: {curr_battery})")
                        battery_ok = False
                elif ev_type == "Charge Start":
                    # Battery is recharged to full during charge
                    curr_battery = state.battery_range
                    
            if bus.arrival_time is None:
                print(f"  [-] Bus {bus_id} never arrived at destination!")
                battery_ok = False
                
        if battery_ok:
            print("  [PASS] Battery range constraints satisfied for all buses.")
        else:
            all_passed = False
            
        # --- TEST 2: Charger overlap constraints ---
        charger_ok = True
        for station_name, station_data in state.stations.items():
            history = station_data["history"]
            chargers_total = station_data["chargers_total"]
            
            # Find max concurrent charging sessions at any point in time
            # We can use a sweep-line algorithm
            events = []
            for record in history:
                events.append((record["start_time"], 1, record["bus_id"]))
                events.append((record["end_time"], -1, record["bus_id"]))
            
            # Sort by time. If times are equal, release (-1) before acquire (1)
            events.sort(key=lambda x: (x[0], x[1]))
            
            curr_charging = 0
            max_charging = 0
            for time, change, bus_id in events:
                curr_charging += change
                if curr_charging > max_charging:
                    max_charging = curr_charging
                    
            if max_charging > chargers_total:
                print(f"  [-] Station {station_name} exceeded charger capacity! Concurrent: {max_charging}, Limit: {chargers_total}")
                charger_ok = False
                
        if charger_ok:
            print(f"  [PASS] Charger capacity constraints satisfied (Max concurrent charging <= chargers limit).")
        else:
            all_passed = False
            
        # --- TEST 3: Optimization efficiency ---
        # Compare best score to baseline score (which uses minimum charges)
        baseline_plans = {b.id: optimizer.valid_plans[b.id][0] for b in scenario.buses}
        _, baseline_metrics = simulator.run(baseline_plans)
        
        baseline_score = baseline_metrics["global_score"]
        best_score = metrics["global_score"]
        
        print(f"  [METRIC] Baseline Global Score: {baseline_score:.2f} | Optimized Global Score: {best_score:.2f}")
        print(f"  [METRIC] Baseline Total Wait Time: {baseline_metrics['total_wait_time']:.1f} min | Optimized Total Wait Time: {metrics['total_wait_time']:.1f} min")
        
        if best_score <= baseline_score:
            print(f"  [PASS] Optimizer successfully improved or maintained schedule score.")
        else:
            print(f"  [-] Optimizer degraded schedule score! (Baseline: {baseline_score}, Best: {best_score})")
            all_passed = False
            
    if all_passed:
        print("\n[SUCCESS] All verification tests passed successfully!")
        sys.exit(0)
    else:
        print("\n[FAILURE] Some verification tests failed!")
        sys.exit(1)

if __name__ == "__main__":
    run_tests()
