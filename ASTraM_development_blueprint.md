# ASTraM: Automated Smart Traffic Management System
## Initial Comprehensive Development Blueprint

---

### 1. Project Overview & Core Objectives

The **ASTraM (Automated Smart Traffic Management)** system is designed to solve hyper-local traffic congestion and bottlenecking at the MIT World Peace University (MIT-WPU) campus grid. By representing campus road segments as directed graph edges and intersections as system nodes, ASTraM models traffic using fundamental linear algebra principles—specifically conservation of flow, bounded system equations, Markov transition matrices, and Bureau of Public Roads (BPR) delay penalties.

#### Core Project Goals
*   **Mathematical Flow Conservation:** Model the campus road network as an augmented matrix $A X = B$, enforcing incoming flow equals outgoing flow at all internal junctions.
*   **Capacitated Flow Bounds:** Prevent gridlock by applying inequality constraints ($0 \le x_i \le C_{i,\max}$) on narrow campus roads.
*   **Dynamic Congestion Pricing / Travel Delay:** Apply the Bureau of Public Roads (BPR) travel time function to continuously update edge costs as traffic approaches physical capacity.
*   **Signal Timing Optimization:** Automatically adjust green-light phase allocations based on real-time link saturation ratios.
*   **Interactive Simulation & Map Matching:** Provide a localized web-based GIS interface featuring snapped GPS tracking and interactive traffic volume inputs.

---

### 2. Network Graph Modeling & Linear Algebra Framework

#### 2.1 Graph Definition
The MIT-WPU campus grid is represented as a directed graph $G = (V, E)$:
*   **Nodes ($V$):** Campus intersections, main entry gates (e.g., Gate 1, Gate 3, Paud Road Entrance), and parking lots.
*   **Edges ($E$):** Directed road segments $e_i = (u, v)$ with flow variable $x_i \ge 0$.

#### 2.2 Conservation of Flow Matrix ($A X = B$)
For every internal intersection node $i \in V$, conservation of flow dictates:
$$\sum_{k \in \text{In}(i)} x_k + b_i^{\text{in}} = \sum_{m \in \text{Out}(i)} x_m + b_i^{\text{out}}$$

In matrix form:
$$A X = B$$
Where:
*   $A \in \mathbb{R}^{|V| \times |E|}$ is the node-edge incidence matrix.
*   $X \in \mathbb{R}^{|E| \times 1}$ is the vector of unknown edge traffic flows ($x_1, x_2, \dots, x_n$).
*   $B \in \mathbb{R}^{|V| \times 1}$ is the net boundary flow vector (measured counts at entry/exit points).

#### 2.3 Capacitated Inequality Constraints
To model physical road limits in dense campus settings, each road segment $e_i$ is bound by its physical capacity $C_i$:
$$0 \le x_i \le C_{i,\max} \quad \forall i \in \{1, 2, \dots, |E|\}$$

#### 2.4 Bureau of Public Roads (BPR) Delay Function
The travel time $T_i$ on road segment $i$ is calculated dynamically as flow $x_i$ increases:
$$T_i(x_i) = T_{0, i} \left( 1 + \alpha \left( \frac{x_i}{C_{i,\max}} \right)^\beta \right)$$
*   $T_{0, i}$: Free-flow travel time (distance divided by speed limit).
*   $\alpha = 0.15$, $\beta = 4.0$ (standard transportation engineering calibration constants).

#### 2.5 Markov Turning Transition Matrix
For multi-lane junctions, turning movements are governed by a row-stochastic matrix $P$:
$$P = \begin{pmatrix} p_{11} & p_{12} & p_{13} \\ p_{21} & p_{22} & p_{23} \\ p_{31} & p_{32} & p_{33} \end{pmatrix}, \quad \text{where } \sum_{j} p_{ij} = 1$$
$p_{ij}$ represents the probability of a vehicle from incoming edge $i$ making a turn onto outgoing edge $j$.

#### 2.6 Signal Timing Optimization Formula
Green phase duration $g_i$ for approach $i$ in a signal cycle $G_{\text{cycle}}$:
$$g_i = G_{\text{min}} + (G_{\text{cycle}} - N \cdot G_{\text{min}}) \times \frac{\max\left(0, \frac{x_i}{C_{i,\max}}\right)}{\sum_{k \in \text{Phases}} \frac{x_k}{C_{k,\max}}}$$

---

### 3. Tech Stack & Software Architecture

To guarantee rapid setup and reliable offline execution during evaluation, the architecture uses a unified full-stack Python application.

*   **Backend Framework:** Python 3.11+ with FastAPI / Flask.
*   **Scientific Computing Engine:** NumPy, SciPy (Optimization & Sparse Linear Algebra), NetworkX.
*   **Geospatial Processing:** GeoPandas, Shapely.
*   **Frontend UI:** Single Page Application with HTML5, Tailwind CSS, Leaflet.js (GIS Map rendering).
*   **Data Format:** Custom GeoJSON (`mit_wpu_roads.geojson`) containing network geometry, edge capacities, and node definitions.

```
+-----------------------------------------------------------------+
|                       Browser Interface                         |
|  - Leaflet.js Campus Map Rendering                              |
|  - Real-time Heatmap Overlay & Flow Control Panel               |
|  - Interactive Node/Edge Inspector                              |
+-----------------------------------------------------------------+
                                |  REST API / WebSockets
                                v
+-----------------------------------------------------------------+
|                     ASTraM Python Backend                       |
|  +-----------------------+   +-------------------------------+  |
|  | GeoJSON Network Parser|   | Map-Matching Engine           |  |
|  +-----------------------+   +-------------------------------+  |
|  | Bounded System Solver |   | BPR Congestion & Signal Optimizer|
|  +-----------------------+   +-------------------------------+  |
+-----------------------------------------------------------------+
```

---

### 4. GeoJSON Data Schema (`mit_wpu_roads.geojson`)

```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "id": "edge_1",
      "geometry": {
        "type": "LineString",
        "coordinates": [[73.8181, 18.5178], [73.8192, 18.5185]]
      },
      "properties": {
        "id": "e1",
        "name": "Gate 1 Main Avenue",
        "source": "node_1",
        "target": "node_2",
        "capacity": 120,
        "free_flow_time_sec": 25,
        "lanes": 2
      }
    }
  ]
}
```

---

### 5. Development Phase Plan

1.  **Phase 1: Geospatial Digitation & Data Modeling:** Digitizing campus nodes, entry/exit points, and edges into GeoJSON format.
2.  **Phase 2: Core Linear Algebra Engine:** Implementing $AX=B$ creation, RREF, and Scipy convex optimization for bounded flow solving.
3.  **Phase 3: Congestion & Signal Control Modules:** BPR travel time updates, Markov turning calculations, and dynamic green-time allocators.
4.  **Phase 4: Map-Matching Engine:** Cross-track distance calculation and vector heading matching algorithm.
5.  **Phase 5: Single-Page Visual Interface:** Leaflet.js interactive canvas, vehicle simulator, and dynamic heatmap dashboard.
6.  **Phase 6: Verification & Demonstration Assembly:** Local test script generation and end-to-end integration testing.
