"""End-to-end test: order → shipment → optimize → pallets"""
import requests, time, json

BASE = 'http://localhost:8000/api/v1'

# 1) Server check
try:
    r = requests.get('http://localhost:8000/api/health', timeout=3)
    print('Server:', r.json())
except:
    print('ERROR: Server not running!'); exit(1)

# 2) Create order with items with weight
order_payload = {
    'order_no': 'TEST-WEIGHT-001',
    'project_code': 'TEST',
    'customer_name': 'Test Customer',
    'city': 'Istanbul',
    'items': [
        {'name': 'Kanepe', 'sku': 'KNP-01', 'quantity': 3, 'length_cm': 180, 'width_cm': 80, 'height_cm': 75, 'weight_kg': 42.5, 'constraints': []},
        {'name': 'Sehpa', 'sku': 'SHP-01', 'quantity': 5, 'length_cm': 60, 'width_cm': 60, 'height_cm': 45, 'weight_kg': 12.0, 'constraints': []},
    ]
}
r = requests.post(f'{BASE}/orders', json=order_payload)
print(f'\n=== CREATE ORDER: {r.status_code} ===')
order = r.json()
order_id = order['id']
print(f"Order ID: {order_id}")
for item in order.get('items', []):
    wk = item.get('weight_kg', 'MISSING')
    print(f"  Item: {item['name']} qty={item['quantity']} weight_kg={wk}")

# 3) Fetch orders (like frontend does on Siparisler page)
r = requests.get(f'{BASE}/orders')
all_orders = r.json()
our_order = next((o for o in all_orders if o['id'] == order_id), None)
print(f'\n=== FETCH ORDER: weight_kg in items? ===')
if our_order:
    for item in our_order.get('items', []):
        wk = item.get('weight_kg', 'MISSING')
        print(f"  Item: {item['name']} weight_kg={wk}")
else:
    print('  Order not found in list!')

# 4) Create shipment from order (simulating _processProductsAPI)
ship_payload = {
    'pallet_type': 'P1',
    'order_ids': [order_id],
    'products': [
        {
            'name': item['name'],
            'quantity': item['quantity'],
            'length_cm': item['length_cm'],
            'width_cm': item['width_cm'],
            'height_cm': item['height_cm'],
            'weight_kg': item['weight_kg'],
            'constraints': [],
        }
        for item in our_order['items']
    ]
}
r = requests.post(f'{BASE}/shipments', json=ship_payload)
print(f'\n=== CREATE SHIPMENT: {r.status_code} ===')
shipment = r.json()
ship_id = shipment['id']
print(f"Shipment ID: {ship_id}")
for p in shipment.get('products', []):
    wk = p.get('weight_kg', 'MISSING')
    print(f"  Product: {p['name']} qty={p['quantity']} weight_kg={wk}")

# 5) Optimize
r = requests.post(f'{BASE}/shipments/{ship_id}/optimize', json={})
print(f'\n=== OPTIMIZE: {r.status_code} ===')
print(f"Response: {r.json()}")

# 6) Poll until done
for i in range(20):
    time.sleep(1.5)
    r = requests.get(f'{BASE}/shipments/{ship_id}/status')
    s = r.json()
    print(f"Poll {i+1}: status={s['status']} pct={s['progress_pct']} msg={s['message']}")
    if s['status'] == 'done':
        break
    if s['status'] == 'failed':
        print('OPTIMIZATION FAILED!'); break

# 7) Get pallets
r = requests.get(f'{BASE}/shipments/{ship_id}/pallets')
print(f'\n=== PALLETS: {r.status_code} ===')
pd = r.json()
pallets = pd.get('pallets', [])
print(f"Total pallets: {len(pallets)}")
for pal in pallets:
    print(f"  Pallet #{pal['pallet_number']} type={pal['pallet_type']} total_weight={pal['total_weight_kg']}kg")
    for prod in pal.get('products', []):
        wk = prod.get('weight_kg', 'MISSING')
        print(f"    -> {prod['name']} qty={prod['quantity']} weight_kg={wk}")

if not pallets:
    print('!!!!! NO PALLETS GENERATED !!!!!')
else:
    print(f'\nSUCCESS: {len(pallets)} pallet(s) generated with weight data')

# Cleanup
requests.delete(f'{BASE}/shipments/{ship_id}')
requests.delete(f'{BASE}/orders/{order_id}')
print('Cleanup done.')
