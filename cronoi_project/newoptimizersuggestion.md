# EXECUTIVE TECHNICAL SPECIFICATION & IMPLEMENTATION PROMPT: OPTIMIZER V10
# Target AI: Claude Code / Gemini Pro
# Focus: Modular Evolution to State-of-the-Art Meta-Heuristic Engine
# Project: Cronoi Logistics Masterpiece Optimizer

## 1. OBJECTIVE & VISION
[cite_start]The objective is to evolve the current Cronoi LS v9.0 optimizer  into a production-grade, sustainable, world-class Hybrid Meta-Heuristic Optimization Engine (V10). [cite_start]The final product must achieve a 92-96% fill rate while executing deterministic, physically stable, and highly custom operations[cite: 361, 362]. 

[cite_start]CRITICAL MANTRA: Do NOT destroy or rewrite the core data models (ProductItem, PalletConfig, PackedItem, OptimizedPallet, VehicleConfig)[cite: 25, 31, 35, 286]. [cite_start]Evolve the code by introducing decoupled managers, structural space representations, and advanced local searches[cite: 328, 334].

---

## 2. THE THREE OPERATIONAL CORE MODES (ARCHITECTURE FLEXIBILITY)
The V10 engine must support three explicit pipeline paths dynamically selected via configuration:

### Mode A: Standard Palletized Flow (Items → Pallets → Vehicles)
- [cite_start]Aggregates `ProductItem` inputs, groups or mixes them into intermediate `OptimizedPallet` layouts[cite: 56, 116, 252].
- [cite_start]Dispatches packed pallets into the vehicle fleet using floor-aware placement strategies[cite: 292, 295].

### Mode B: Fleet Optimization Only (Pre-Packed Pallets → Vehicles)
- [cite_start]Bypasses the palletization engine[cite: 292].
- [cite_start]Accepts existing structured pallets (with footprint_w_cm, footprint_l_cm, phys_height_cm) and executes pure 3D/2D floor-aware fleet assignment[cite: 36, 295, 296].

### Mode C: Loose/Bulk Cargo Flow (Loose Items → Vehicles Directly)
- Bypasses intermediate pallets completely.
- [cite_start]Treats the `VehicleConfig` cargo hold as a giant 3D bounding box container[cite: 286].
- [cite_start]Packs heterogenous or homogenous items directly onto the truck/container floor using 3D extreme points and advanced stability metrics[cite: 61, 140, 146].

---

## 3. NEW INDUSTRIAL CONSTRAINTS TO ENFORCE

### A. Destination Facility Profiles ("No Unloading Ramp" Constraint)
- **Problem**: If a customer's receiving warehouse or delivery address lacks a standard industrial unloading dock/ramp, containers/trailers cannot be filled to the roof line. Forklifts or manual operators working from ground level require structural headroom to reach inside and pull out top-tier items safely.
- [cite_start]**Implementation**: Introduce a `DestinationProfile` attribute to the pipeline or map it via `delivery_address`[cite: 26, 35]. If `has_unloading_ramp = False`, the engine must inject a dynamic `top_clearance_margin_cm` (e.g., 40cm to 60cm parameterizable) [cite: 9] [cite_start]that clamps the `_effective_max_height` of the container space manager across either the entire vehicle or designated unloading zones[cite: 51, 52].

### B. Dynamic Stackability Framework
- [cite_start]Items must strictly obey multi-attribute layer classification[cite: 61].
- [cite_start]Separate absolute structural constraints (`ConstraintType.NO_STACK`, `ConstraintType.MUST_BOTTOM`) from dynamic vertical pressure tolerances based on compression metrics[cite: 5, 30].

---

## 4. ALGORITHMIC ARCHITECTURE UPGRADES

### Step 1: Maximal Empty Spaces (EMS) Space Manager
- [cite_start]Replace the legacy Rect-Skyline approach for volume tracking[cite: 336].
- [cite_start]Maintain an `EMSManager` that keeps track of all overlapping maximal empty boxes inside a pallet or vehicle container[cite: 336, 337].
- When an item is committed, intersect its bounding box with all active EMS instances, split into new maximal boundaries, and execute non-maximal elimination (remove spaces entirely swallowed by larger empty volumes).

### Step 2: Metric Normalization Scoring Engine
- [cite_start]Replace static, hardcoded scoring constants (e.g., score += 200) with a completely normalized Multi-Objective Scoring Scheme[cite: 345, 346].
- [cite_start]Every sub-score (Floor Utilization, Height Utilization, Contact Area, Support Ratio, CoG Alignment, Order Sequence Alignment) must scale strictly between 0.0 and 1.0[cite: 138, 146, 346].
- [cite_start]Dynamically alter weight vectors based on the `BindingDimension`[cite: 1]. (e.g., If Weight limits the vehicle, optimize for layout symmetry and low CoG; if Volume limits it, optimize for void reduction) [cite_start][cite: 1, 138, 348].

### Step 3: Adaptive Large Neighborhood Search (ALNS) Loop
[cite_start]Wrap the initial solution with a iterative meta-heuristic loop operating within the `max_optimization_time_sec` budget[cite: 11, 50, 339]:
- **Destroy Operators**:
  - [cite_start]`WorstPlacementDestroy`: Evicts the $k$ items that have the lowest individual placement scores[cite: 339].
  - [cite_start]`TopLayerDestroy`: Evicts items sitting in the upper zone of the Z-axis to remedy fragmented empty spaces[cite: 339, 341].
  - [cite_start]`ClusterDestroy`: Evicts items closely bound to a randomized 3D spatial coordinate[cite: 339].
- **Repair Operators**:
  - [cite_start]`BestInsertionRepair`: Uses the normalized Scoring Engine to re-insert evictees into optimal EMS boundaries[cite: 339].
  - [cite_start]`RegretInsertion`: Evaluates the score difference between the absolute best EMS slot and the second-best slot, prioritizing items that suffer most if not placed immediately[cite: 339].

### Step 4: Deterministic Randomization
- Ensure that every meta-heuristic choice, shuffle, or randomized operator uses a locally seeded pseudo-random number generator instance.
- [cite_start]Running the V10 engine twice with identical constraints and inputs MUST produce bitwise identical layout patterns[cite: 331, 362].

---

## 5. REFACTORING ROADMAP FOR CLAUDE CODE
When modifying the codebase, follow these implementation rules:
1. [cite_start]**Zero Model Breakage**: Do not rewrite existing dataclass fields unless extending them via optional, default-assigned parameters[cite: 4, 31].
2. [cite_start]**Encapsulation**: Create distinct modules or private classes for `EMSManager`, `ALNSOptimizer`, and `ConstraintValidator`[cite: 358].
3. [cite_start]**Fallback Gracefulness**: If the ALNS search process or time budget triggers early termination, seamlessly fall back to the cleanest structurally sound layout found so far[cite: 54, 120].