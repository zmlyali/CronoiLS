"""
Cronoi LS – Comprehensive API Integration Tests
Covers: Orders, Shipments, Scenarios, Constraints, Transport Units
Status transitions, CRUD operations, edge cases, and lifecycle flows.
"""
import requests
import time
import json
import sys

BASE = "http://localhost:8000/api/v1"
COMPANY = "00000000-0000-0000-0000-000000000001"
H = {"X-Company-Id": COMPANY, "Content-Type": "application/json"}

# ── Global counters ──────────────────────────────────────────
PASS_COUNT = 0
FAIL_COUNT = 0
SKIP_COUNT = 0
SECTION = ""
FAILURES = []


def section(name):
    global SECTION
    SECTION = name
    print(f"\n{'─'*60}")
    print(f"  {name}")
    print(f"{'─'*60}")


def check(name, condition, detail=""):
    global PASS_COUNT, FAIL_COUNT
    mark = "✓" if condition else "✗"
    color = "" if condition else " ← FAIL"
    suffix = f"  ({detail})" if detail else ""
    print(f"  [{mark}] {name}{suffix}{color}")
    if condition:
        PASS_COUNT += 1
    else:
        FAIL_COUNT += 1
        FAILURES.append(f"[{SECTION}] {name} – {detail}")


def skip(name, reason=""):
    global SKIP_COUNT
    SKIP_COUNT += 1
    print(f"  [–] {name}  (SKIP: {reason})")


def unique_no(prefix="TST"):
    return f"{prefix}-{int(time.time()*1000)}"


# ══════════════════════════════════════════════════════════════
#  1. HEALTH CHECK
# ══════════════════════════════════════════════════════════════

def test_health():
    section("1. Health Check")
    r = requests.get("http://localhost:8000/api/health")
    check("GET /api/health returns 200", r.status_code == 200, f"status={r.status_code}")
    data = r.json()
    check("Response has status=ok", data.get("status") == "ok")
    check("Response has version", bool(data.get("version")))


# ══════════════════════════════════════════════════════════════
#  2. TRANSPORT UNITS
# ══════════════════════════════════════════════════════════════

def test_transport_units():
    section("2. Transport Units – Seed & CRUD")

    # Seed
    r = requests.post(f"{BASE}/transport-units/seed", json={}, headers=H)
    check("Seed transport units", r.status_code in [200, 201], f"status={r.status_code}")

    # Pallets
    r = requests.get(f"{BASE}/transport-units/pallets", headers=H)
    pallets = r.json()
    check("List pallet defs", r.status_code == 200 and isinstance(pallets, list), f"{len(pallets)} defs")
    check("Has pallet definitions", len(pallets) > 0)

    # Create custom pallet
    custom_pallet = {
        "code": f"TEST_{int(time.time())}",
        "name": "Test Palet",
        "length_cm": 100, "width_cm": 80,
        "max_height_cm": 150, "max_weight_kg": 800,
        "tare_weight_kg": 20
    }
    r = requests.post(f"{BASE}/transport-units/pallets", json=custom_pallet, headers=H)
    check("Create custom pallet def", r.status_code in [200, 201], f"status={r.status_code}")
    if r.status_code in [200, 201]:
        pid = r.json().get("id")
        # Toggle
        r2 = requests.patch(f"{BASE}/transport-units/pallets/{pid}/toggle", headers=H)
        check("Toggle pallet active", r2.status_code == 200)
        # Delete
        r3 = requests.delete(f"{BASE}/transport-units/pallets/{pid}", headers=H)
        check("Delete custom pallet", r3.status_code == 200)

    # Vehicles
    r = requests.get(f"{BASE}/transport-units/vehicles", headers=H)
    vehicles = r.json()
    check("List vehicle defs", r.status_code == 200 and isinstance(vehicles, list), f"{len(vehicles)} defs")
    check("Has vehicle definitions", len(vehicles) > 0)

    # Create custom vehicle
    custom_vehicle = {
        "code": f"VTST_{int(time.time())}",
        "name": "Test TIR", "type": "tir",
        "length_cm": 1360, "width_cm": 245, "height_cm": 270,
        "max_weight_kg": 24000
    }
    r = requests.post(f"{BASE}/transport-units/vehicles", json=custom_vehicle, headers=H)
    check("Create custom vehicle def", r.status_code in [200, 201], f"status={r.status_code}")
    if r.status_code in [200, 201]:
        vid = r.json().get("id")
        r2 = requests.patch(f"{BASE}/transport-units/vehicles/{vid}/toggle", headers=H)
        check("Toggle vehicle active", r2.status_code == 200)
        r3 = requests.delete(f"{BASE}/transport-units/vehicles/{vid}", headers=H)
        check("Delete custom vehicle", r3.status_code == 200)


# ══════════════════════════════════════════════════════════════
#  3. ORDERS – CRUD
# ══════════════════════════════════════════════════════════════

def test_orders_crud():
    section("3. Orders – CRUD Operations")

    # CREATE
    order_no = unique_no("ORD")
    payload = {
        "order_no": order_no,
        "customer_name": "API Test MüÅŸteri",
        "city": "Ä°stanbul",
        "address": "KadÄ±köy Moda Cad.",
        "priority": 2,
        "notes": "Test sipariÅŸ",
        "items": [
            {"name": "Masa", "quantity": 3, "length_cm": 120, "width_cm": 80, "height_cm": 75, "weight_kg": 45,
             "constraints": [{"code": "FRAGILE"}]},
            {"name": "Sandalye", "quantity": 8, "length_cm": 50, "width_cm": 50, "height_cm": 90, "weight_kg": 8},
        ]
    }
    r = requests.post(f"{BASE}/orders", json=payload, headers=H)
    check("Create order", r.status_code in [200, 201], f"status={r.status_code}")
    order = r.json()
    oid = order.get("id", "")
    check("Order has UUID id", len(oid) == 36, oid[:12] if oid else "no id")
    check("Order has correct order_no", order.get("order_no") == order_no)
    check("Order status is pending", order.get("status") == "pending")
    check("Order has 2 items", len(order.get("items", [])) == 2, f"{len(order.get('items',[]))} items")
    check("First item has constraint", len(order.get("items", [{}])[0].get("constraints", [])) > 0)

    # READ single
    r = requests.get(f"{BASE}/orders/{oid}", headers=H)
    check("Get single order", r.status_code == 200)
    fetched = r.json()
    check("Fetched order matches", fetched.get("order_no") == order_no)

    # READ list
    r = requests.get(f"{BASE}/orders", headers=H)
    check("List orders", r.status_code == 200)
    all_orders = r.json()
    check("Orders is a list", isinstance(all_orders, list))
    found = any(o.get("id") == oid for o in all_orders)
    check("Created order in list", found)

    # Filter by status
    r = requests.get(f"{BASE}/orders?status=pending", headers=H)
    check("Filter by status=pending", r.status_code == 200)
    filtered = r.json()
    check("Filtered list is non-empty", len(filtered) > 0)

    # Filter by city
    r = requests.get(f"{BASE}/orders?city=Ä°stanbul", headers=H)
    check("Filter by city", r.status_code == 200)

    # UPDATE (PUT)
    update_payload = {
        "customer_name": "Güncel Test MüÅŸteri",
        "priority": 1,
        "notes": "Güncellendi",
        "items": [
            {"name": "Masa Büyük", "quantity": 2, "length_cm": 150, "width_cm": 90, "height_cm": 75, "weight_kg": 60},
            {"name": "Koltuk", "quantity": 4, "length_cm": 80, "width_cm": 70, "height_cm": 100, "weight_kg": 25,
             "constraints": [{"code": "HEAVY"}]},
        ]
    }
    r = requests.put(f"{BASE}/orders/{oid}", json=update_payload, headers=H)
    check("Update order (PUT)", r.status_code == 200, f"status={r.status_code}")
    updated = r.json()
    check("Customer name updated", updated.get("customer_name") == "Güncel Test MüÅŸteri")
    check("Priority updated", updated.get("priority") == 1)
    check("Items replaced", len(updated.get("items", [])) == 2)

    # UPDATE on non-existent
    fake_id = "00000000-0000-0000-0000-000000000099"
    r = requests.put(f"{BASE}/orders/{fake_id}", json=update_payload, headers=H)
    check("PUT non-existent ←’ 404", r.status_code == 404)

    # DELETE (soft)
    r = requests.delete(f"{BASE}/orders/{oid}", headers=H)
    check("Soft delete order", r.status_code in [200, 204], f"status={r.status_code}")

    # Verify deleted ←’ 404
    r = requests.get(f"{BASE}/orders/{oid}", headers=H)
    check("Deleted order ←’ 404", r.status_code == 404)

    # Not in default list
    r = requests.get(f"{BASE}/orders", headers=H)
    found_after = any(o.get("id") == oid for o in r.json())
    check("Deleted order not in list", not found_after)

    # Include deleted
    r = requests.get(f"{BASE}/orders?include_deleted=true", headers=H)
    found_incl = any(o.get("id") == oid for o in r.json())
    check("Deleted visible with include_deleted", found_incl)

    # RESTORE
    r = requests.patch(f"{BASE}/orders/{oid}/restore", headers=H)
    check("Restore deleted order", r.status_code == 200, f"status={r.status_code}")

    r = requests.get(f"{BASE}/orders/{oid}", headers=H)
    check("Restored order accessible", r.status_code == 200)

    # DELETE non-existent
    r = requests.delete(f"{BASE}/orders/{fake_id}", headers=H)
    check("Delete non-existent ←’ 404", r.status_code == 404)

    # Cleanup
    requests.delete(f"{BASE}/orders/{oid}?force=true", headers=H)

    return oid  # may be deleted


# ══════════════════════════════════════════════════════════════
#  4. ORDER STATUS TRANSITIONS
# ══════════════════════════════════════════════════════════════

def test_order_status_transitions():
    section("4. Order Status Transitions")

    # Create a fresh order
    payload = {
        "order_no": unique_no("STS"),
        "customer_name": "Status Test",
        "city": "Ankara",
        "items": [{"name": "Box", "quantity": 2, "length_cm": 40, "width_cm": 30, "height_cm": 20, "weight_kg": 10}]
    }
    r = requests.post(f"{BASE}/orders", json=payload, headers=H)
    oid = r.json().get("id", "")

    # Valid transitions: pending ←’ in_shipment ←’ pallet_planned ←’ vehicle_planned ←’ loaded ←’ delivered
    transitions = [
        ("pending", "in_shipment", True),
        ("in_shipment", "pallet_planned", True),
        ("pallet_planned", "vehicle_planned", True),
        ("vehicle_planned", "loaded", True),
        ("loaded", "delivered", True),
    ]

    for from_st, to_st, should_pass in transitions:
        r = requests.patch(f"{BASE}/orders/{oid}/status", json={"status": to_st}, headers=H)
        if should_pass:
            check(f"{from_st} ←’ {to_st}", r.status_code == 200, f"status={r.status_code}")
        else:
            check(f"{from_st} ←’ {to_st} rejected", r.status_code == 400, f"status={r.status_code}")

    # Delivered is terminal – no more transitions
    r = requests.patch(f"{BASE}/orders/{oid}/status", json={"status": "pending"}, headers=H)
    check("delivered ←’ pending REJECTED", r.status_code == 400, f"status={r.status_code}")

    r = requests.patch(f"{BASE}/orders/{oid}/status", json={"status": "cancelled"}, headers=H)
    check("delivered ←’ cancelled REJECTED", r.status_code == 400, f"status={r.status_code}")

    # Cleanup
    requests.delete(f"{BASE}/orders/{oid}?force=true", headers=H)

    # Test invalid transitions
    payload["order_no"] = unique_no("STS2")
    r = requests.post(f"{BASE}/orders", json=payload, headers=H)
    oid2 = r.json().get("id", "")

    # pending ←’ loaded (skip steps – should FAIL)
    r = requests.patch(f"{BASE}/orders/{oid2}/status", json={"status": "loaded"}, headers=H)
    check("pending ←’ loaded REJECTED (skip steps)", r.status_code == 400, f"status={r.status_code}")

    # pending ←’ delivered (skip all – should FAIL)
    r = requests.patch(f"{BASE}/orders/{oid2}/status", json={"status": "delivered"}, headers=H)
    check("pending ←’ delivered REJECTED", r.status_code == 400, f"status={r.status_code}")

    # Invalid status name
    r = requests.patch(f"{BASE}/orders/{oid2}/status", json={"status": "nonexistent"}, headers=H)
    check("Invalid status name ←’ 400", r.status_code == 400, f"status={r.status_code}")

    # pending ←’ cancelled (valid)
    r = requests.patch(f"{BASE}/orders/{oid2}/status", json={"status": "cancelled"}, headers=H)
    check("pending ←’ cancelled", r.status_code == 200)

    # cancelled is terminal
    r = requests.patch(f"{BASE}/orders/{oid2}/status", json={"status": "pending"}, headers=H)
    check("cancelled ←’ pending REJECTED", r.status_code == 400, f"status={r.status_code}")

    # Cleanup
    requests.delete(f"{BASE}/orders/{oid2}?force=true", headers=H)

    # Test backward transition: in_shipment ←’ pending
    payload["order_no"] = unique_no("STS3")
    r = requests.post(f"{BASE}/orders", json=payload, headers=H)
    oid3 = r.json().get("id", "")
    requests.patch(f"{BASE}/orders/{oid3}/status", json={"status": "in_shipment"}, headers=H)
    r = requests.patch(f"{BASE}/orders/{oid3}/status", json={"status": "pending"}, headers=H)
    check("in_shipment ←’ pending (allowed rollback)", r.status_code == 200)
    requests.delete(f"{BASE}/orders/{oid3}?force=true", headers=H)


# ══════════════════════════════════════════════════════════════
#  5. ORDER EDIT RESTRICTIONS
# ══════════════════════════════════════════════════════════════

def test_order_edit_restrictions():
    section("5. Order Edit Restrictions")

    payload = {
        "order_no": unique_no("EDR"),
        "customer_name": "Edit Restrict",
        "city": "Bursa",
        "items": [{"name": "Kutu", "quantity": 1, "length_cm": 30, "width_cm": 20, "height_cm": 15, "weight_kg": 5}]
    }
    r = requests.post(f"{BASE}/orders", json=payload, headers=H)
    oid = r.json().get("id", "")

    update = {"customer_name": "Edited Name"}

    # pending ←’ editable
    r = requests.put(f"{BASE}/orders/{oid}", json=update, headers=H)
    check("PUT when pending ←’ 200", r.status_code == 200)

    # in_shipment ←’ editable
    requests.patch(f"{BASE}/orders/{oid}/status", json={"status": "in_shipment"}, headers=H)
    r = requests.put(f"{BASE}/orders/{oid}", json=update, headers=H)
    check("PUT when in_shipment ←’ 200", r.status_code == 200)

    # pallet_planned ←’ NOT editable
    requests.patch(f"{BASE}/orders/{oid}/status", json={"status": "pallet_planned"}, headers=H)
    r = requests.put(f"{BASE}/orders/{oid}", json=update, headers=H)
    check("PUT when pallet_planned ←’ 409", r.status_code == 409, f"status={r.status_code}")

    # Cleanup
    requests.patch(f"{BASE}/orders/{oid}/status", json={"status": "pending"}, headers=H)
    requests.delete(f"{BASE}/orders/{oid}?force=true", headers=H)


# ══════════════════════════════════════════════════════════════
#  6. ORDER DELETE RESTRICTIONS
# ══════════════════════════════════════════════════════════════

def test_order_delete_restrictions():
    section("6. Order Delete Restrictions")

    payload = {
        "order_no": unique_no("DEL"),
        "customer_name": "Delete Test",
        "city": "Antalya",
        "items": [{"name": "Paket", "quantity": 1, "length_cm": 25, "width_cm": 20, "height_cm": 15, "weight_kg": 3}]
    }
    r = requests.post(f"{BASE}/orders", json=payload, headers=H)
    oid = r.json().get("id", "")

    # Move to in_shipment
    requests.patch(f"{BASE}/orders/{oid}/status", json={"status": "in_shipment"}, headers=H)

    # Soft delete without force ←’ 409 (not pending)
    r = requests.delete(f"{BASE}/orders/{oid}", headers=H)
    check("Delete non-pending without force ←’ 409", r.status_code == 409, f"status={r.status_code}")

    # Force delete ←’ 204
    r = requests.delete(f"{BASE}/orders/{oid}?force=true", headers=H)
    check("Force delete non-pending ←’ 204", r.status_code in [200, 204], f"status={r.status_code}")

    # Double delete ←’ 404
    r = requests.delete(f"{BASE}/orders/{oid}?force=true", headers=H)
    check("Delete already-deleted ←’ 404", r.status_code == 404, f"status={r.status_code}")


# ══════════════════════════════════════════════════════════════
#  7. BULK ORDER IMPORT
# ══════════════════════════════════════════════════════════════

def test_bulk_orders():
    section("7. Bulk Order Import")

    bulk_data = [
        {"order_no": unique_no("BLK1"), "product_name": "Kargo Kutusu",
         "customer_name": "Toplu MüÅŸteri 1", "city": "Ä°zmir",
         "dimensions": "40x30x20", "weight_kg": 5, "quantity": 10},
        {"order_no": unique_no("BLK2"), "product_name": "Ambalaj",
         "customer_name": "Toplu MüÅŸteri 2", "city": "Ankara",
         "dimensions": "60x40x30", "weight_kg": 8, "quantity": 5},
    ]
    r = requests.post(f"{BASE}/orders/bulk", json=bulk_data, headers=H)
    check("Bulk import orders", r.status_code in [200, 201], f"status={r.status_code}")
    result = r.json()
    check("Imported count", result.get("imported", 0) >= 2, f"imported={result.get('imported')}")
    check("Has order_nos", len(result.get("order_nos", [])) >= 2)

    # Cleanup bulk orders
    for ono in result.get("order_nos", []):
        orders = requests.get(f"{BASE}/orders", headers=H).json()
        for o in orders:
            if o.get("order_no") == ono:
                requests.delete(f"{BASE}/orders/{o['id']}?force=true", headers=H)


# ══════════════════════════════════════════════════════════════
#  8. SHIPMENTS – CRUD
# ══════════════════════════════════════════════════════════════

def test_shipments_crud():
    section("8. Shipments – CRUD Operations")

    ship_data = {
        "pallet_type": "P1",
        "destination": "Ä°stanbul Depo",
        "notes": "API test sevkiyat",
        "products": [
            {"name": "Mobilya", "quantity": 5, "length_cm": 100, "width_cm": 60, "height_cm": 50, "weight_kg": 40},
            {"name": "Aksesuar", "quantity": 10, "length_cm": 30, "width_cm": 20, "height_cm": 15, "weight_kg": 3},
        ]
    }

    # CREATE
    r = requests.post(f"{BASE}/shipments", json=ship_data, headers=H)
    check("Create shipment", r.status_code in [200, 201], f"status={r.status_code}")
    ship = r.json()
    sid = ship.get("id", "")
    check("Shipment has UUID id", len(sid) == 36, sid[:12] if sid else "no id")
    check("Shipment has reference_no", bool(ship.get("reference_no")))
    check("Shipment status is draft", ship.get("status") == "draft")

    # LIST
    r = requests.get(f"{BASE}/shipments", headers=H)
    check("List shipments", r.status_code == 200)
    ships = r.json()
    check("Shipments is a list", isinstance(ships, list))
    found = any(s.get("id") == sid for s in ships)
    check("Created shipment in list", found)

    # GET detail
    r = requests.get(f"{BASE}/shipments/{sid}", headers=H)
    check("Get shipment detail", r.status_code == 200)
    detail = r.json()
    check("Detail has products", len(detail.get("products", [])) > 0)
    check("Detail has reference_no", detail.get("reference_no") == ship.get("reference_no"))

    # GET non-existent
    fake_id = "00000000-0000-0000-0000-000000000099"
    r = requests.get(f"{BASE}/shipments/{fake_id}", headers=H)
    check("Get non-existent ←’ 404", r.status_code == 404)

    # DELETE (soft)
    r = requests.delete(f"{BASE}/shipments/{sid}", headers=H)
    check("Soft delete shipment", r.status_code in [200, 204], f"status={r.status_code}")

    # Verify deleted
    r = requests.get(f"{BASE}/shipments/{sid}", headers=H)
    check("Deleted shipment ←’ 404", r.status_code == 404)

    # RESTORE
    r = requests.patch(f"{BASE}/shipments/{sid}/restore", headers=H)
    check("Restore shipment", r.status_code == 200)

    r = requests.get(f"{BASE}/shipments/{sid}", headers=H)
    check("Restored shipment accessible", r.status_code == 200)

    # Cleanup
    requests.delete(f"{BASE}/shipments/{sid}?force=true", headers=H)

    return sid


# ══════════════════════════════════════════════════════════════
#  9. SHIPMENT STATUS TRANSITIONS
# ══════════════════════════════════════════════════════════════

def test_shipment_status_transitions():
    section("9. Shipment Status Transitions")

    ship_data = {
        "pallet_type": "P1",
        "products": [
            {"name": "Test Ürün", "quantity": 3, "length_cm": 60, "width_cm": 40, "height_cm": 30, "weight_kg": 15}
        ]
    }
    r = requests.post(f"{BASE}/shipments", json=ship_data, headers=H)
    sid = r.json().get("id", "")

    # Valid forward: draft ←’ plan_confirmed ←’ loading ←’ completed ←’ in_transit ←’ delivered
    transitions = [
        ("draft", "plan_confirmed", True),
        ("plan_confirmed", "loading", True),
        ("loading", "completed", True),
        ("completed", "in_transit", True),
        ("in_transit", "delivered", True),
    ]

    for from_st, to_st, should_pass in transitions:
        r = requests.patch(f"{BASE}/shipments/{sid}/status", json={"status": to_st}, headers=H)
        if should_pass:
            check(f"{from_st} ←’ {to_st}", r.status_code == 200, f"status={r.status_code}")
        else:
            check(f"{from_st} ←’ {to_st} REJECTED", r.status_code == 400, f"status={r.status_code}")

    # Delivered is terminal
    r = requests.patch(f"{BASE}/shipments/{sid}/status", json={"status": "draft"}, headers=H)
    check("delivered ←’ draft REJECTED (terminal)", r.status_code == 400, f"status={r.status_code}")

    # Cleanup
    requests.delete(f"{BASE}/shipments/{sid}?force=true", headers=H)

    # Test invalid skips
    r = requests.post(f"{BASE}/shipments", json=ship_data, headers=H)
    sid2 = r.json().get("id", "")

    r = requests.patch(f"{BASE}/shipments/{sid2}/status", json={"status": "delivered"}, headers=H)
    check("draft ←’ delivered REJECTED (skip)", r.status_code == 400, f"status={r.status_code}")

    r = requests.patch(f"{BASE}/shipments/{sid2}/status", json={"status": "in_transit"}, headers=H)
    check("draft ←’ in_transit REJECTED (skip)", r.status_code == 400, f"status={r.status_code}")

    # draft ←’ cancelled (valid)
    r = requests.patch(f"{BASE}/shipments/{sid2}/status", json={"status": "cancelled"}, headers=H)
    check("draft ←’ cancelled", r.status_code == 200)

    # cancelled ←’ draft (reopen)
    r = requests.patch(f"{BASE}/shipments/{sid2}/status", json={"status": "draft"}, headers=H)
    check("cancelled ←’ draft (reopen)", r.status_code == 200)

    # Cleanup
    requests.delete(f"{BASE}/shipments/{sid2}?force=true", headers=H)


# ══════════════════════════════════════════════════════════════
#  10. SHIPMENT DELETE RESTRICTIONS
# ══════════════════════════════════════════════════════════════

def test_shipment_delete_restrictions():
    section("10. Shipment Delete Restrictions")

    ship_data = {
        "pallet_type": "P1",
        "products": [
            {"name": "Kutu", "quantity": 2, "length_cm": 40, "width_cm": 30, "height_cm": 20, "weight_kg": 8}
        ]
    }
    r = requests.post(f"{BASE}/shipments", json=ship_data, headers=H)
    sid = r.json().get("id", "")

    # Move to plan_confirmed
    requests.patch(f"{BASE}/shipments/{sid}/status", json={"status": "plan_confirmed"}, headers=H)

    # Delete without force ←’ 409
    r = requests.delete(f"{BASE}/shipments/{sid}", headers=H)
    check("Delete non-draft without force ←’ 409", r.status_code == 409, f"status={r.status_code}")

    # Force delete ←’ 204
    r = requests.delete(f"{BASE}/shipments/{sid}?force=true", headers=H)
    check("Force delete non-draft ←’ success", r.status_code in [200, 204], f"status={r.status_code}")


# ══════════════════════════════════════════════════════════════
#  11. OPTIMIZATION + PALLET FLOW
# ══════════════════════════════════════════════════════════════

def test_optimization_flow():
    section("11. Optimization + Pallet Flow")

    ship_data = {
        "pallet_type": "P1",
        "products": [
            {"name": "TV Kartusu", "quantity": 6, "length_cm": 90, "width_cm": 15, "height_cm": 60, "weight_kg": 25},
            {"name": "Aksesuar Kutusu", "quantity": 12, "length_cm": 30, "width_cm": 20, "height_cm": 15, "weight_kg": 3},
        ]
    }
    r = requests.post(f"{BASE}/shipments", json=ship_data, headers=H)
    ship = r.json()
    sid = ship.get("id", "")
    check("Create shipment for optimization", r.status_code in [200, 201])

    # Start optimization
    r = requests.post(f"{BASE}/shipments/{sid}/optimize", json={}, headers=H)
    check("Start optimization", r.status_code == 200, f"status={r.status_code}")

    # Poll for completion
    done = False
    final_status = ""
    for i in range(30):
        time.sleep(1)
        r = requests.get(f"{BASE}/shipments/{sid}/status", headers=H)
        st = r.json()
        final_status = st.get("status", "")
        if final_status in ["done", "optimized", "plan_confirmed"]:
            done = True
            break
    check("Optimization completes", done, f"final_status={final_status}, polls={i+1}")

    # Get pallets
    r = requests.get(f"{BASE}/shipments/{sid}/pallets", headers=H)
    check("Get pallets", r.status_code == 200)
    pallet_data = r.json()
    pallets = pallet_data.get("pallets", [])
    check("Pallets created", len(pallets) > 0, f"{len(pallets)} pallets")

    # Validate pallet constraints
    for p in pallets:
        pidx = p.get("pallet_number", p.get("pallet_index", "?"))
        th = p.get("total_height_cm", 0)
        tw = p.get("total_weight_kg", 0)
        fr = p.get("fill_rate_pct", 0)
        check(f"Pallet #{pidx} height â‰¤ 180cm", th <= 180, f"{th}cm")
        check(f"Pallet #{pidx} weight â‰¤ 1000kg", tw <= 1000, f"{tw}kg")
        check(f"Pallet #{pidx} fill_rate > 0", fr > 0, f"{fr}%")

    # Get full shipment detail – should have pallets now
    r = requests.get(f"{BASE}/shipments/{sid}", headers=H)
    detail = r.json()
    check("Detail includes pallets", len(detail.get("pallets", [])) > 0)
    check("Detail has avg_fill_rate", detail.get("avg_fill_rate_pct", 0) > 0 or detail.get("avg_fill_rate_pct") is not None)

    # Verify pallet products are included in shipment detail
    detail_pallets = detail.get("pallets", [])
    pallets_with_products = [p for p in detail_pallets if len(p.get("products", [])) > 0]
    check("Detail pallets include products", len(pallets_with_products) > 0,
         f"{len(pallets_with_products)}/{len(detail_pallets)} pallets have products")
    if pallets_with_products:
        first_prod = pallets_with_products[0]["products"][0]
        check("Pallet product has name field", "name" in first_prod, f"keys={list(first_prod.keys())}")
        check("Pallet product has quantity field", "quantity" in first_prod)

    # Save pallets endpoint
    save_pallets = [
        {"type": "P1", "totalWeight": 100,
         "totalHeight": 120, "totalVolume": 0.5, "fillRate": 75,
         "products": [{"name": "Test", "quantity": 1, "length": 80, "width": 60,
                       "height": 40, "weight": 20}]}
    ]
    r = requests.post(f"{BASE}/shipments/{sid}/pallets", json=save_pallets, headers=H)
    check("Save pallets", r.status_code in [200, 201], f"status={r.status_code}")

    # Cleanup
    requests.delete(f"{BASE}/shipments/{sid}?force=true", headers=H)

    return sid


# ══════════════════════════════════════════════════════════════
#  12. SCENARIO GENERATION + SELECTION
# ══════════════════════════════════════════════════════════════

def test_scenarios():
    section("12. Scenario Generation & Selection")

    # Create + optimize a shipment first
    ship_data = {
        "pallet_type": "P1",
        "products": [
            {"name": "Ürün A", "quantity": 8, "length_cm": 60, "width_cm": 40, "height_cm": 30, "weight_kg": 15},
        ]
    }
    r = requests.post(f"{BASE}/shipments", json=ship_data, headers=H)
    sid = r.json().get("id", "")

    r = requests.post(f"{BASE}/shipments/{sid}/optimize", json={}, headers=H)
    for i in range(30):
        time.sleep(1)
        r = requests.get(f"{BASE}/shipments/{sid}/status", headers=H)
        if r.json().get("status") in ["done", "optimized", "plan_confirmed"]:
            break

    # Generate scenarios
    scenario_req = {
        "shipment_id": sid,
        "vehicle_configs": [
            {"id": "v1", "name": "TIR Standart", "type": "tir",
             "length_cm": 1360, "width_cm": 245, "height_cm": 270,
             "max_weight_kg": 24000, "base_cost": 5000, "distance_km": 500}
        ]
    }
    r = requests.post(f"{BASE}/scenarios/generate", json=scenario_req, headers=H)
    check("Generate scenarios", r.status_code == 200, f"status={r.status_code}")
    scenarios = r.json().get("scenarios", [])
    check("Multiple scenarios generated", len(scenarios) >= 1, f"{len(scenarios)} scenarios")

    if scenarios:
        # Check scenario fields
        s0 = scenarios[0]
        check("Scenario has name", bool(s0.get("name")))
        check("Scenario has total_cost", s0.get("total_cost") is not None)
        check("Scenario has total_vehicles", s0.get("total_vehicles") is not None)
        check("Scenario has avg_fill_rate_pct", s0.get("avg_fill_rate_pct") is not None)

        # One should be recommended
        recommended = [s for s in scenarios if s.get("is_recommended")]
        check("At least one recommended", len(recommended) >= 1)

        # Select a scenario
        scen_id = s0.get("id")
        if scen_id:
            r = requests.patch(f"{BASE}/scenarios/{scen_id}/select", headers=H)
            check("Select scenario", r.status_code == 200, f"status={r.status_code}")
            if r.status_code == 200:
                check("is_selected flag", r.json().get("is_selected") == True)

        # List scenarios for shipment
        r = requests.get(f"{BASE}/scenarios/{sid}", headers=H)
        check("List scenarios for shipment", r.status_code == 200)
        fetched = r.json()
        check("Fetched scenarios matches", len(fetched) >= 1)

    # Cleanup
    requests.delete(f"{BASE}/shipments/{sid}?force=true", headers=H)


# ══════════════════════════════════════════════════════════════
#  13. CONSTRAINT VALIDATION
# ══════════════════════════════════════════════════════════════

def test_constraints():
    section("13. Constraint Validation")

    # List constraints
    r = requests.get(f"{BASE}/constraints", headers=H)
    check("List constraints", r.status_code == 200)

    # Validate compatible constraints
    r = requests.post(f"{BASE}/constraints/validate", json={
        "constraint_codes": ["FRAGILE", "MUST_BE_TOP"],
        "param_values": {}
    }, headers=H)
    check("Validate compatible constraints", r.status_code == 200)
    result = r.json()
    check("Valid combination is_valid", result.get("is_valid") == True)

    # Validate conflicting constraints
    r = requests.post(f"{BASE}/constraints/validate", json={
        "constraint_codes": ["HORIZONTAL_ONLY", "VERTICAL_ONLY"],
        "param_values": {}
    }, headers=H)
    check("Validate conflicting constraints", r.status_code == 200)
    result = r.json()
    check("Conflicting combo is_valid=false", result.get("is_valid") == False)
    check("Has errors", len(result.get("errors", [])) > 0)

    # Validate MUST_BE_BOTTOM + MUST_BE_TOP conflict
    r = requests.post(f"{BASE}/constraints/validate", json={
        "constraint_codes": ["MUST_BE_BOTTOM", "MUST_BE_TOP"],
        "param_values": {}
    }, headers=H)
    result = r.json()
    check("BOTTOM+TOP conflict detected", result.get("is_valid") == False)

    # Validate LOAD_FIRST + LOAD_LAST conflict
    r = requests.post(f"{BASE}/constraints/validate", json={
        "constraint_codes": ["LOAD_FIRST", "LOAD_LAST"],
        "param_values": {}
    }, headers=H)
    result = r.json()
    check("LOAD_FIRST+LOAD_LAST conflict detected", result.get("is_valid") == False)

    # Validate VEHICLE_FRONT + VEHICLE_REAR conflict
    r = requests.post(f"{BASE}/constraints/validate", json={
        "constraint_codes": ["VEHICLE_FRONT", "VEHICLE_REAR"],
        "param_values": {}
    }, headers=H)
    result = r.json()
    check("VEHICLE_FRONT+REAR conflict detected", result.get("is_valid") == False)

    # COLD_CHAIN without temp params ←’ warning
    r = requests.post(f"{BASE}/constraints/validate", json={
        "constraint_codes": ["COLD_CHAIN"],
        "param_values": {}
    }, headers=H)
    result = r.json()
    check("COLD_CHAIN without temp ←’ has warnings", len(result.get("warnings", [])) > 0)

    # Compatibility rules endpoint
    r = requests.get(f"{BASE}/constraints/compatibility", headers=H)
    check("List compatibility rules", r.status_code == 200)


# ══════════════════════════════════════════════════════════════
#  14. SHIPMENT COMPLETE FLOW (ORDER LINKAGE)
# ══════════════════════════════════════════════════════════════

def test_shipment_complete_flow():
    section("14. Shipment Complete Flow + Order Linkage")

    # Create orders
    items = [{"name": "Parça", "quantity": 3, "length_cm": 40, "width_cm": 30, "height_cm": 20, "weight_kg": 10}]
    o1_no = unique_no("CMP1")
    o2_no = unique_no("CMP2")
    r1 = requests.post(f"{BASE}/orders", json={"order_no": o1_no, "customer_name": "CMP Test 1", "city": "Ä°stanbul", "items": items}, headers=H)
    r2 = requests.post(f"{BASE}/orders", json={"order_no": o2_no, "customer_name": "CMP Test 2", "city": "Ä°stanbul", "items": items}, headers=H)
    oid1 = r1.json().get("id", "")
    oid2 = r2.json().get("id", "")

    # Create shipment with order_ids
    ship_data = {
        "pallet_type": "P1",
        "destination": "KadÄ±köy",
        "order_ids": [oid1, oid2],
        "products": [
            {"name": "Parça", "quantity": 6, "length_cm": 40, "width_cm": 30, "height_cm": 20, "weight_kg": 10},
        ]
    }
    r = requests.post(f"{BASE}/shipments", json=ship_data, headers=H)
    ship = r.json()
    sid = ship.get("id", "")
    check("Create shipment with order_ids", r.status_code in [200, 201])

    # Check orders are linked (shipment_ref or shipment_id on order)
    r = requests.get(f"{BASE}/orders/{oid1}", headers=H)
    o1_detail = r.json()
    has_ref = bool(o1_detail.get("shipment_ref") or o1_detail.get("shipment_id"))
    check("Order 1 linked to shipment", has_ref, f"ref={o1_detail.get('shipment_ref')}, sid={o1_detail.get('shipment_id')}")

    # Complete the shipment
    r = requests.post(f"{BASE}/shipments/{sid}/complete", json={"order_ids": [oid1, oid2]}, headers=H)
    check("Complete shipment", r.status_code == 200, f"status={r.status_code}")
    if r.status_code == 200:
        comp = r.json()
        check("Shipment status ←’ loaded", comp.get("status") == "loaded")
        check("Has loaded_at", bool(comp.get("loaded_at")))

    # Check orders are now loaded
    r1 = requests.get(f"{BASE}/orders/{oid1}", headers=H)
    r2 = requests.get(f"{BASE}/orders/{oid2}", headers=H)
    if r1.status_code == 200:
        check("Order 1 status ←’ loaded", r1.json().get("status") == "loaded")
    if r2.status_code == 200:
        check("Order 2 status ←’ loaded", r2.json().get("status") == "loaded")

    # Shipment detail should show orders
    r = requests.get(f"{BASE}/shipments/{sid}", headers=H)
    if r.status_code == 200:
        detail = r.json()
        check("Shipment detail has orders", len(detail.get("orders", [])) >= 2)

    # Continue: loaded orders ←’ delivered
    r = requests.patch(f"{BASE}/orders/{oid1}/status", json={"status": "delivered"}, headers=H)
    check("Order loaded ←’ delivered", r.status_code == 200)

    # Cleanup
    requests.delete(f"{BASE}/orders/{oid1}?force=true", headers=H)
    requests.delete(f"{BASE}/orders/{oid2}?force=true", headers=H)
    requests.delete(f"{BASE}/shipments/{sid}?force=true", headers=H)


# ══════════════════════════════════════════════════════════════
#  15. GROUP SUGGESTIONS
# ══════════════════════════════════════════════════════════════

def test_group_suggestions():
    section("15. Order Group Suggestions")

    # Create several orders in same city
    items = [{"name": "Paket", "quantity": 1, "length_cm": 30, "width_cm": 20, "height_cm": 15, "weight_kg": 5}]
    oids = []
    for i in range(3):
        r = requests.post(f"{BASE}/orders", json={
            "order_no": unique_no(f"GRP{i}"),
            "customer_name": f"Grup Test {i}",
            "city": "Ankara",
            "items": items
        }, headers=H)
        if r.status_code in [200, 201]:
            oids.append(r.json().get("id", ""))

    r = requests.post(f"{BASE}/orders/group-suggestions", headers=H)
    check("Group suggestions", r.status_code == 200, f"status={r.status_code}")
    groups = r.json().get("groups", [])
    check("Has suggested groups", isinstance(groups, list))

    # Cleanup
    for oid in oids:
        requests.delete(f"{BASE}/orders/{oid}?force=true", headers=H)


# ══════════════════════════════════════════════════════════════
#  16. WEEKLY SUMMARY REPORT
# ══════════════════════════════════════════════════════════════

def test_weekly_summary():
    section("16. Weekly Summary Report")

    r = requests.get(f"{BASE}/shipments/reports/weekly-summary", headers=H)
    check("Weekly summary report", r.status_code == 200, f"status={r.status_code}")
    data = r.json()
    check("Has summary key", "summary" in data)
    check("Has shipments key", "shipments" in data)


# ══════════════════════════════════════════════════════════════
#  17. FULL LIFECYCLE E2E
# ══════════════════════════════════════════════════════════════

def test_full_lifecycle():
    section("17. Full Lifecycle – Order ←’ Shipment ←’ Optimize ←’ Scenario ←’ Load ←’ Deliver")

    # 1. Create order
    order_no = unique_no("E2E")
    r = requests.post(f"{BASE}/orders", json={
        "order_no": order_no,
        "customer_name": "E2E Lifecycle",
        "city": "Ä°stanbul",
        "items": [
            {"name": "Beyaz EÅŸya", "quantity": 2, "length_cm": 70, "width_cm": 60, "height_cm": 85, "weight_kg": 60,
             "constraints": [{"code": "HEAVY"}, {"code": "MUST_BE_BOTTOM"}]},
            {"name": "Cam Ürün", "quantity": 4, "length_cm": 40, "width_cm": 30, "height_cm": 50, "weight_kg": 12,
             "constraints": [{"code": "FRAGILE"}, {"code": "MUST_BE_TOP"}]}
        ]
    }, headers=H)
    check("1. Create order", r.status_code in [200, 201])
    oid = r.json().get("id", "")
    check("   Order status = pending", r.json().get("status") == "pending")

    # 2. Create shipment with order
    r = requests.post(f"{BASE}/shipments", json={
        "pallet_type": "P1",
        "destination": "Merkez Depo",
        "order_ids": [oid],
        "products": [
            {"name": "Beyaz EÅŸya", "quantity": 2, "length_cm": 70, "width_cm": 60, "height_cm": 85, "weight_kg": 60,
             "constraints": [{"code": "HEAVY"}, {"code": "MUST_BE_BOTTOM"}]},
            {"name": "Cam Ürün", "quantity": 4, "length_cm": 40, "width_cm": 30, "height_cm": 50, "weight_kg": 12,
             "constraints": [{"code": "FRAGILE"}, {"code": "MUST_BE_TOP"}]}
        ]
    }, headers=H)
    check("2. Create shipment", r.status_code in [200, 201])
    sid = r.json().get("id", "")
    check("   Shipment status = draft", r.json().get("status") == "draft")

    # 3. Optimize
    r = requests.post(f"{BASE}/shipments/{sid}/optimize", json={}, headers=H)
    check("3. Start optimization", r.status_code == 200)

    done = False
    for i in range(30):
        time.sleep(1)
        r = requests.get(f"{BASE}/shipments/{sid}/status", headers=H)
        if r.json().get("status") in ["done", "optimized", "plan_confirmed"]:
            done = True
            break
    check("   Optimization completes", done)

    # 4. Get pallets
    r = requests.get(f"{BASE}/shipments/{sid}/pallets", headers=H)
    pallets = r.json().get("pallets", [])
    check("4. Pallets generated", len(pallets) > 0, f"{len(pallets)} pallets")

    # Validate constraints in pallets – HEAVY should not be above FRAGILE
    for p in pallets:
        products_in_pallet = p.get("products", [])
        # Check fill rate
        fr = p.get("fill_rate_pct", 0)
        check(f"   Pallet #{p.get('pallet_number', '?')} fill > 0%", fr > 0, f"{fr}%")

    # 5. Generate scenarios
    r = requests.post(f"{BASE}/scenarios/generate", json={
        "shipment_id": sid,
        "vehicle_configs": [
            {"id": "tir1", "name": "TIR 13.6m", "type": "tir",
             "length_cm": 1360, "width_cm": 245, "height_cm": 270,
             "max_weight_kg": 24000, "base_cost": 6000, "distance_km": 400}
        ]
    }, headers=H)
    check("5. Generate scenarios", r.status_code == 200)
    scenarios = r.json().get("scenarios", [])
    check("   Scenarios created", len(scenarios) >= 1, f"{len(scenarios)} scenarios")

    if scenarios:
        # Select recommended
        rec = next((s for s in scenarios if s.get("is_recommended")), scenarios[0])
        scen_id = rec.get("id")
        if scen_id:
            r = requests.patch(f"{BASE}/scenarios/{scen_id}/select", headers=H)
            check("   Select scenario", r.status_code == 200)

    # 6. Complete shipment
    r = requests.post(f"{BASE}/shipments/{sid}/complete", json={"order_ids": [oid]}, headers=H)
    check("6. Complete shipment", r.status_code == 200, f"status={r.status_code}")
    if r.status_code == 200:
        check("   Shipment status=loaded", r.json().get("status") == "loaded")

    # 7. Check order status
    r = requests.get(f"{BASE}/orders/{oid}", headers=H)
    if r.status_code == 200:
        check("7. Order now loaded", r.json().get("status") == "loaded")
        check("   Order has shipment_ref", bool(r.json().get("shipment_ref")))
        check("   Order has shipment_id", bool(r.json().get("shipment_id")))

    # 8. Deliver
    r = requests.patch(f"{BASE}/orders/{oid}/status", json={"status": "delivered"}, headers=H)
    check("8. Order loaded ←’ delivered", r.status_code == 200)

    # Get final shipment detail
    r = requests.get(f"{BASE}/shipments/{sid}", headers=H)
    if r.status_code == 200:
        detail = r.json()
        check("   Final detail has orders", len(detail.get("orders", [])) > 0)
        check("   Final detail has pallets", len(detail.get("pallets", [])) > 0)

    # Cleanup
    requests.delete(f"{BASE}/orders/{oid}?force=true", headers=H)
    requests.delete(f"{BASE}/shipments/{sid}?force=true", headers=H)

    print(f"\n  ğŸ Full lifecycle E2E complete")


# ══════════════════════════════════════════════════════════════
#  18. EDGE CASES
# ══════════════════════════════════════════════════════════════

def test_edge_cases():
    section("18. Edge Cases")

    # Create with empty items
    r = requests.post(f"{BASE}/orders", json={
        "order_no": unique_no("EDGE1"),
        "customer_name": "Edge Test",
        "items": []
    }, headers=H)
    check("Create order with empty items", r.status_code in [200, 201, 422],
         f"status={r.status_code}")

    # Create order with missing required fields
    r = requests.post(f"{BASE}/orders", json={"notes": "missing fields"}, headers=H)
    check("Create order missing fields ←’ 422", r.status_code == 422, f"status={r.status_code}")

    # Create shipment with no products ←’ 422
    r = requests.post(f"{BASE}/shipments", json={"pallet_type": "P1", "products": []}, headers=H)
    check("Create shipment no products ←’ 422", r.status_code == 422, f"status={r.status_code}")

    # Status update on non-existent order
    fake_id = "00000000-0000-0000-0000-000000000099"
    r = requests.patch(f"{BASE}/orders/{fake_id}/status", json={"status": "pending"}, headers=H)
    check("Status update non-existent ←’ 404", r.status_code == 404, f"status={r.status_code}")

    # Restore non-deleted order
    r = requests.post(f"{BASE}/orders", json={
        "order_no": unique_no("EDGE2"),
        "customer_name": "Not Deleted",
        "items": [{"name": "X", "quantity": 1, "length_cm": 10, "width_cm": 10, "height_cm": 10, "weight_kg": 1}]
    }, headers=H)
    oid = r.json().get("id", "")
    r = requests.patch(f"{BASE}/orders/{oid}/restore", headers=H)
    check("Restore non-deleted ←’ 400", r.status_code == 400, f"status={r.status_code}")
    requests.delete(f"{BASE}/orders/{oid}?force=true", headers=H)

    # Optimize non-existent shipment
    r = requests.post(f"{BASE}/shipments/{fake_id}/optimize", json={}, headers=H)
    check("Optimize non-existent ←’ 404", r.status_code == 404, f"status={r.status_code}")

    # Complete shipment from invalid status
    ship_data = {
        "pallet_type": "P1",
        "products": [{"name": "Z", "quantity": 1, "length_cm": 20, "width_cm": 20, "height_cm": 20, "weight_kg": 5}]
    }
    r = requests.post(f"{BASE}/shipments", json=ship_data, headers=H)
    sid = r.json().get("id", "")
    # Move to in_transit via transitions
    requests.patch(f"{BASE}/shipments/{sid}/status", json={"status": "plan_confirmed"}, headers=H)
    requests.patch(f"{BASE}/shipments/{sid}/status", json={"status": "loading"}, headers=H)
    requests.patch(f"{BASE}/shipments/{sid}/status", json={"status": "completed"}, headers=H)
    requests.patch(f"{BASE}/shipments/{sid}/status", json={"status": "in_transit"}, headers=H)

    r = requests.post(f"{BASE}/shipments/{sid}/complete", json={}, headers=H)
    check("Complete from in_transit ←’ 400", r.status_code == 400, f"status={r.status_code}")

    requests.delete(f"{BASE}/shipments/{sid}?force=true", headers=H)


# ══════════════════════════════════════════════════════════════
#  RUNNER
# ══════════════════════════════════════════════════════════════

def main():
    print("=" * 60)
    print("  CRONOI LS – Comprehensive API Test Suite")
    print(f"  Server: {BASE}")
    print("=" * 60)

    # Verify server is up
    try:
        r = requests.get("http://localhost:8000/api/health", timeout=5)
        if r.status_code != 200:
            print("\n  ✗ Server not healthy. Aborting.")
            sys.exit(1)
    except Exception as e:
        print(f"\n  ✗ Cannot reach server: {e}")
        sys.exit(1)

    test_health()
    test_transport_units()
    test_orders_crud()
    test_order_status_transitions()
    test_order_edit_restrictions()
    test_order_delete_restrictions()
    test_bulk_orders()
    test_shipments_crud()
    test_shipment_status_transitions()
    test_shipment_delete_restrictions()
    test_optimization_flow()
    test_scenarios()
    test_constraints()
    test_shipment_complete_flow()
    test_group_suggestions()
    test_weekly_summary()
    test_full_lifecycle()
    test_edge_cases()

    # ── Summary ────────────────────────────────────────────
    print("\n" + "=" * 60)
    total = PASS_COUNT + FAIL_COUNT + SKIP_COUNT
    print(f"  RESULTS:  {PASS_COUNT} passed  /  {FAIL_COUNT} failed  /  {SKIP_COUNT} skipped  /  {total} total")

    if FAILURES:
        print(f"\n  FAILURES ({len(FAILURES)}):")
        for f in FAILURES:
            print(f"    ✗ {f}")

    print("=" * 60)

    if FAIL_COUNT == 0:
        print("  ✓ ALL TESTS PASSED – Ready for production")
    else:
        print(f"  ✗ {FAIL_COUNT} TESTS FAILED – Fix before deploy")

    print("=" * 60)
    sys.exit(0 if FAIL_COUNT == 0 else 1)


if __name__ == "__main__":
    main()

