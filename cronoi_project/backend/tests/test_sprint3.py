"""Sprint 3 Integration Tests — Cronoi LS"""
import requests
import time
import json

BASE = "http://localhost:8000/api/v1"
COMPANY = "00000000-0000-0000-0000-000000000001"
H = {"X-Company-Id": COMPANY}
OK = True


def test(name, condition, detail=""):
    global OK
    mark = "PASS" if condition else "FAIL"
    if not condition:
        OK = False
    suffix = f" -- {detail}" if detail else ""
    print(f"  [{mark}] {name}{suffix}")


def run_tests():
    global OK

    print("=" * 60)
    print("CRONOI LS — Sprint 3 Integration Tests")
    print("=" * 60)

    # --- 1. Health ---
    print("\n--- 1. Health Check ---")
    r = requests.get("http://localhost:8000/api/health")
    test("Health endpoint", r.status_code == 200, r.json().get("status"))

    # --- 2. Transport Units ---
    print("\n--- 2. Transport Units ---")
    r = requests.post(f"{BASE}/transport-units/seed", json={}, headers=H)
    test("Seed transport units", r.status_code in [200, 201])

    r = requests.get(f"{BASE}/transport-units/pallets", headers=H)
    pallets_tu = r.json()
    test("Get pallet defs", r.status_code == 200 and len(pallets_tu) > 0, f"{len(pallets_tu)} tip")

    r = requests.get(f"{BASE}/transport-units/vehicles", headers=H)
    vehicles_tu = r.json()
    test("Get vehicle defs", r.status_code == 200 and len(vehicles_tu) > 0, f"{len(vehicles_tu)} tip")

    # --- 3. Orders ---
    print("\n--- 3. Orders ---")
    order_data = {
        "order_no": f"TST-{int(time.time())}",
        "customer_name": "Test Sprint3",
        "city": "Izmir",
        "address": "Gaziemir Sanayi",
        "requested_ship_date": "2026-04-01",
        "items": [
            {"name": "Koltuk Takimi", "quantity": 4, "length_cm": 90, "width_cm": 60, "height_cm": 45, "weight_kg": 35},
            {"name": "Sehpa", "quantity": 6, "length_cm": 50, "width_cm": 50, "height_cm": 30, "weight_kg": 12},
        ],
    }
    r = requests.post(f"{BASE}/orders", json=order_data, headers=H)
    test("Create order", r.status_code in [200, 201], f"status={r.status_code}")
    order = r.json()
    order_id = order.get("id", "")
    test("Order has id", bool(order_id), order_id[:8] if order_id else "no id")
    test("Order has order_no", bool(order.get("order_no")), order.get("order_no", "?"))

    r = requests.get(f"{BASE}/orders", headers=H)
    orders = r.json()
    test("List orders", r.status_code == 200 and isinstance(orders, list) and len(orders) > 0, f"{len(orders)} adet")

    # --- 4. Shipment + Optimization ---
    print("\n--- 4. Shipment + Optimization ---")
    ship_data = {
        "pallet_type": "P1",
        "products": [
            {"name": "Koltuk Takimi", "quantity": 4, "length_cm": 90, "width_cm": 60, "height_cm": 45, "weight_kg": 35},
            {"name": "Sehpa", "quantity": 6, "length_cm": 50, "width_cm": 50, "height_cm": 30, "weight_kg": 12},
        ],
    }
    r = requests.post(f"{BASE}/shipments", json=ship_data, headers=H)
    test("Create shipment", r.status_code in [200, 201], f"status={r.status_code}")
    ship = r.json()
    ship_id = ship.get("id", "")
    ref_no = ship.get("reference_no", "?")
    test("Shipment has ref_no", ref_no and ref_no != "?", ref_no)

    r = requests.post(f"{BASE}/shipments/{ship_id}/optimize", json={}, headers=H)
    test("Start optimization", r.status_code == 200)

    # Poll for completion
    done = False
    polls = 0
    for i in range(25):
        time.sleep(1)
        polls = i + 1
        r = requests.get(f"{BASE}/shipments/{ship_id}/status", headers=H)
        st = r.json()
        if st.get("status") == "done":
            done = True
            break
    test("Optimization done", done, f"polls={polls}, status={st.get('status', '?')}")

    # Get pallets
    r = requests.get(f"{BASE}/shipments/{ship_id}/pallets", headers=H)
    pallet_data = r.json()
    pallet_count = len(pallet_data.get("pallets", []))
    test("Pallets created", pallet_count > 0, f"{pallet_count} palet")

    # --- 5. 3D Dimension Validation ---
    print("\n--- 5. 3D Dimension Validation ---")
    for p in pallet_data.get("pallets", []):
        pidx = p.get("pallet_index", "?")
        for pr in p.get("products", []):
            l = pr.get("length_cm", 0)
            w = pr.get("width_cm", 0)
            name = pr.get("name", "?")
            # Product should fit within EUR pallet (80x120) in at least one orientation
            fits = (l <= 120 and w <= 80) or (l <= 80 and w <= 120)
            test(f"Palet#{pidx} {name} fits EUR", fits, f"{l}x{w}cm in 80x120")

    # --- 6. Physical Pallet Constraints ---
    print("\n--- 6. Pallet Weight/Height ---")
    for p in pallet_data.get("pallets", []):
        pidx = p.get("pallet_index", "?")
        th = p.get("total_height_cm", 0)
        tw = p.get("total_weight_kg", 0)
        test(f"Palet#{pidx} height <= 180cm", th <= 180, f"{th}cm")
        test(f"Palet#{pidx} weight <= 1000kg", tw <= 1000, f"{tw}kg")

    # --- 7. Soft Delete & Restore ---
    print("\n--- 7. Soft Delete & Restore ---")
    if not order_id:
        print("  [SKIP] No order_id — skipping soft delete tests")
    else:
        r = requests.delete(f"{BASE}/orders/{order_id}?force=true", headers=H)
        test("Soft delete order", r.status_code in [200, 204], f"status={r.status_code}")

        r = requests.get(f"{BASE}/orders/{order_id}", headers=H)
        test("Deleted order returns 404", r.status_code == 404)

        r = requests.patch(f"{BASE}/orders/{order_id}/restore", headers=H)
        test("Restore order", r.status_code == 200)

        r = requests.get(f"{BASE}/orders/{order_id}", headers=H)
        test("Restored order accessible", r.status_code == 200)

    # --- 8. Shipment Complete Flow ---
    print("\n--- 8. Shipment Complete ---")
    if not order_id or not ship_id:
        print("  [SKIP] Missing order_id or ship_id")
    else:
        r = requests.post(
            f"{BASE}/shipments/{ship_id}/complete",
            json={"order_ids": [order_id]},
            headers=H,
        )
        test("Complete shipment", r.status_code == 200, f"status={r.status_code}")
        if r.status_code == 200:
            comp = r.json()
            test("Has reference_no", bool(comp.get("reference_no")), comp.get("reference_no", "?"))

        # Check order now has shipment_ref
        r = requests.get(f"{BASE}/orders/{order_id}", headers=H)
        if r.status_code == 200:
            od = r.json()
            # od might be a dict or list depending on endpoint
            if isinstance(od, list):
                od = od[0] if od else {}
            test("Order has shipment_ref", bool(od.get("shipment_ref")), od.get("shipment_ref", "none"))
            test("Order status is loaded", od.get("status") == "loaded", od.get("status", "?"))

    # Cleanup
    if order_id:
        requests.delete(f"{BASE}/orders/{order_id}?force=true", headers=H)

    # --- Summary ---
    print("\n" + "=" * 60)
    result = "ALL TESTS PASSED" if OK else "SOME TESTS FAILED"
    print(f"RESULT: {result}")
    print("=" * 60)
    return OK


if __name__ == "__main__":
    run_tests()
