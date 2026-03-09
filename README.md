# CALB L148N58A - 3RC Equivalent Circuit Model Parameter Extraction

Extracts 3RC equivalent circuit model parameters from HPPC and C/20 test data for **11 CALB L148N58A (58 Ah nominal, NMC 811)** large-format prismatic lithium-ion cells using the Mendeley dataset.

## Dataset

**Source:** [Mendeley Data - CALB L148N58A Testing Campaign](https://data.mendeley.com/datasets/ycx459r5c3/1)

| Property | Value |
|---|---|
| Chemistry | NMC 811 (Graphite anode) |
| Nominal Capacity | 58 Ah |
| Voltage Range | 2.5 - 4.2 V |
| Dimensions (L x W x H) | 148 x 27 x 106 mm |
| Weight | 0.926 kg |
| Number of Cells | 11 |
| Test Temperatures | 10°C, 25°C, 40°C |

### Dataset Structure

```
A Dataset for Large Prismatic Lithium-Ion Battery Cells (CALB L148N58A).../
└── CALB L148N58A testing campaign/
    ├── Raw Data/           (.xlsx files)
    └── Processed Data/     (.mat files) <-- used by this script
        ├── Temperature_10C/
        ├── Temperature_25C/
        └── Temperature_40C/
            ├── C20_Charge/       C/20 charge data
            ├── C20_Discharge/    C/20 discharge data (capacity + OCV)
            ├── HPPC_1C/          1C HPPC pulse test (R0, RC parameters)
            ├── HPPC_C3/          C/3 HPPC pulse test
            ├── EIS_test/         Electrochemical impedance spectroscopy
            ├── DV_UDDS/          UDDS driving cycle
            ├── DV_WLTP/          WLTP driving cycle
            └── DV_US06/          US06 driving cycle
```

## 3RC Equivalent Circuit Model

```
        R0          R1          R2          R3
  o───/\/\/──┬──/\/\/──┬──/\/\/──┬──/\/\/──┬──o
             │         │         │         │
  I(t) →     │    C1 ──┤    C2 ──┤    C3 ──┤
             │  (tau1)  │  (tau2) │  (tau3) │
             │         │         │         │
  o──────────┴─────────┴─────────┴─────────┴──o
             +                                -
                      Em(SOC)
```

- **Em(SOC):** Open-circuit voltage as a function of SOC
- **R0:** Ohmic resistance (instantaneous voltage drop)
- **R1, tau1:** Fast RC branch (tau ~ 2-4 s)
- **R2, tau2:** Medium RC branch (tau ~ 15-30 s)
- **R3, tau3:** Slow RC branch (tau ~ 50-200 s)

## Methodology

### 1. Capacity (C/20 Discharge)

Full discharge at C/20 rate (2.9 A). Capacity is the total discharged Ah:

```
Capacity = integral(|I(t)| * dt) / 3600   [Ah]
```

**Note on measured vs. nominal capacity:** The nominal capacity is 58 Ah (datasheet), but the measured C/20 capacity is 53-54 Ah. This is because:

1. **Incomplete initial charge:** The discharge starts at 4.192 V instead of 4.200 V, meaning the cell was not fully charged to 100% SOC before the test. This accounts for approximately 1-1.5 Ah.
2. **Nominal vs. actual:** Datasheet capacity is measured under ideal conditions. Real-world C/20 tests typically yield 90-95% of nominal capacity.
3. **Cell aging:** A few formation/conditioning cycles may have been performed before testing.

The measured values (53-54 Ah) are used in the model because they represent the **actual tested capacity** of these specific cells, which is more accurate for simulation than the nominal value.

### 2. OCV / Em (C/20 Discharge)

At C/20, the current is low enough that the IR drop is negligible (~0.003 V for 2.9 A x ~0.001 Ohm). The measured voltage is therefore approximately equal to the OCV. Interpolation is performed at the SOC breakpoints:

```
SOC(t) = 1 - (cumulative_Ah(t) / total_capacity)
Em = interp(SOC_LUT, SOC, Voltage)
```

### 3. R0 (HPPC 1C Pulse Test)

Instantaneous voltage drop at the start of each 10s discharge pulse:

```
R0 = (V_before_pulse - V_instant_after) / I_pulse
```

> **Sampling rate verification:** HPPC data is sampled at 10 Hz (0.1 s interval) at pulse onset.
> At the first sample: dV = 67.2 mV; at 0.1 s later: dV = 68.1 mV. The RC contamination is only 0.9 mV, which is negligible.

### 4. R1, R2, R3, tau1, tau2, tau3 (Curve Fitting)

Three-exponential fit to the 600s voltage relaxation curve after each pulse:

```
dV(t) = V_inf - V_rest(t)
dV(t) = A1*exp(-t/tau1) + A2*exp(-t/tau2) + A3*exp(-t/tau3)
Ri = Ai / I_pulse
```

Fitting bounds (optimized for 58 Ah prismatic cell with low internal resistance):
- Voltage amplitude upper bound: 0.1 V (total pulse dV ~ 0.06 V)
- tau1 range: 0.01 - 10 s
- tau2 range: 0.1 - 100 s
- tau3 range: 1 - 1000 s

### HPPC Test Pattern

At each SOC point (from 100% to 0%, in ~10% steps):

```
Voltage
  |    V_before
  |    ──────┐
  |          |← dV_instant (R0 = dV / I)
  |          V1
  |           \
  |            \← Exponential decay (R1,R2,R3 + tau1,tau2,tau3)
  |             \_____ V_end
  |                    |
  |                    |← Current removed
  |                    V2
  |                   /
  |                  / ← Recovery (3RC relaxation -> curve fitting)
  |                 /
  |          ──────  V_inf
  └──────────────────────── Time
```

Sequence per SOC point: 10s discharge pulse → 600s rest → 10s charge pulse → 600s rest → 360s discharge (SOC step-down) → 3600s rest

### Verification Checks Performed

| Check | Result |
|---|---|
| Current sign convention | Negative = discharge (verified: V drops when I < -50 A) |
| HPPC sampling rate at pulse onset | 10 Hz (0.1 s) — RC contamination only 0.9 mV |
| Rest region end detection | 5 A threshold correctly captures charge pulse onset |
| Curve fitting convergence | RMSE < 0.1 mV for all fits |

## Installation and Usage

### Requirements

```bash
pip install -r requirements.txt
```

### Run

```bash
python extract_CALB_params.py
```

> Place the Mendeley dataset in the same directory as `extract_CALB_params.py`.

### Outputs

```
calb/
├── extract_CALB_params.py          Main script
├── all_cell_params.json            All parameters (JSON)
├── comparison_table.xlsx           Comparison table (Excel)
└── results/
    ├── Cell_59294/
    │   ├── batteryParameterEstimation_results_3RC_10degC.mat
    │   ├── batteryParameterEstimation_results_3RC_25degC.mat
    │   └── batteryParameterEstimation_results_3RC_40degC.mat
    ├── Cell_59485/
    │   └── ... (same 3 files)
    ├── ...
    └── Cell_60710/
        └── ...
```

Each `.mat` file contains:

| Variable | Description | Size |
|---|---|---|
| `Em` | OCV vs SOC (V) | 1x11 |
| `R0` | Terminal resistance vs SOC (Ohm) | 1x11 |
| `R1` | 1st RC resistance vs SOC (Ohm) | 1x11 |
| `R2` | 2nd RC resistance vs SOC (Ohm) | 1x11 |
| `R3` | 3rd RC resistance vs SOC (Ohm) | 1x11 |
| `SOC_LUT` | SOC breakpoints | 1x11 |
| `tau1` | 1st RC time constant vs SOC (s) | 1x11 |
| `tau2` | 2nd RC time constant vs SOC (s) | 1x11 |
| `tau3` | 3rd RC time constant vs SOC (s) | 1x11 |

## Results

### Capacity and R0 Summary (11-Cell Average)

| Temperature | Measured Capacity (Ah) | Nominal Capacity (Ah) | Ratio | R0 Mean (mOhm) |
|---|---|---|---|---|
| 10°C | 53.36 ± 0.49 | 58 | 92.0% | 1.958 ± 0.105 |
| 25°C | 53.63 ± 0.38 | 58 | 92.5% | 1.147 ± 0.078 |
| 40°C | 54.19 ± 0.43 | 58 | 93.4% | 0.835 ± 0.071 |

### Cell-by-Cell Comparison (25°C)

| Cell | Capacity (Ah) | R0 (mOhm) | R1 (mOhm) | R2 (mOhm) | tau1 (s) | tau2 (s) | tau3 (s) |
|---|---|---|---|---|---|---|---|
| 59294 | 53.29 | 1.189 | 0.128 | 0.187 | 3.07 | 24.67 | 141.6 |
| 59485 | 53.38 | 1.155 | 0.127 | 0.185 | 3.01 | 24.15 | 136.8 |
| 59627 | 53.44 | 1.065 | 0.145 | 0.200 | 3.09 | 25.17 | 151.6 |
| 59690 | 53.59 | 1.157 | 0.124 | 0.180 | 3.04 | 24.52 | 140.9 |
| 59861 | 53.81 | 1.165 | 0.122 | 0.184 | 3.06 | 23.82 | 137.1 |
| 60031 | 54.14 | 1.123 | 0.140 | 0.201 | 3.15 | 24.50 | 147.0 |
| 60129 | 54.17 | 1.086 | 0.136 | 0.201 | 3.07 | 24.50 | 150.5 |
| 60195 | 54.04 | 1.100 | 0.126 | 0.174 | 3.08 | 25.21 | 142.6 |
| **60403** | **52.96** | **1.359** | **0.192** | **0.209** | **3.15** | **23.01** | **148.5** |
| 60644 | 53.88 | 1.062 | 0.131 | 0.184 | 3.15 | 23.38 | 142.2 |
| 60710 | 53.30 | 1.154 | 0.160 | 0.201 | 3.20 | 23.26 | 152.9 |

> **Cell 60403** is an outlier: lowest capacity and highest R0 (+18.5% above mean). This likely indicates cell-to-cell manufacturing variation.

### Key Observations

- **Temperature dependence:** R0 decreases with increasing temperature (Arrhenius behavior). From 10°C to 40°C, R0 drops by 57%.
- **Capacity:** Slightly increases with temperature (10°C: 53.4 Ah → 40°C: 54.2 Ah).
- **Cell-to-cell variation:** R0 varies by ±6-7% across cells (excluding Cell 60403).
- **Fit quality:** 3RC curve fitting RMSE < 0.1 mV across all SOC points and temperatures.

## Simulink Integration

To replace the Kokam model parameters in Simulink with CALB L148N58A parameters:

```matlab
% Old (Kokam):
% results.T5C  = load('batteryParameterEstimation_results_3RC_5degC.mat');
% results.T20C = load('batteryParameterEstimation_results_3RC_20degC.mat');
% results.T40C = load('batteryParameterEstimation_results_3RC_40degC.mat');

% New (CALB L148N58A - e.g., Cell 59294):
results.T10C = load('results/Cell_59294/batteryParameterEstimation_results_3RC_10degC.mat');
results.T25C = load('results/Cell_59294/batteryParameterEstimation_results_3RC_25degC.mat');
results.T40C = load('results/Cell_59294/batteryParameterEstimation_results_3RC_40degC.mat');

% Update temperature LUT:
Battery(idx).Temperature_LUT = [10 25 40] + 273.15;  % Kelvin

% Update physical properties:
cell_thickness = 0.027;   % m
cell_width     = 0.148;   % m
cell_height    = 0.106;   % m
Battery(idx).cell_mass = 0.926; % kg

% Use measured capacity (NOT nominal 58 Ah):
Battery(idx).Capacity_LUT = [53.4 53.6 54.2]; % Ah (per temperature)
```

## Project Structure

```
calb/
├── README.md                       This file
├── requirements.txt                Python dependencies
├── extract_CALB_params.py          Parameter extraction script
├── all_cell_params.json            All results (JSON)
├── comparison_table.xlsx           Cell comparison table (Excel)
├── results/                        Simulink-compatible .mat outputs
│   ├── Cell_59294/                 (11 cells, 3 .mat files each)
│   ├── Cell_59485/
│   ├── Cell_59627/
│   ├── Cell_59690/
│   ├── Cell_59861/
│   ├── Cell_60031/
│   ├── Cell_60129/
│   ├── Cell_60195/
│   ├── Cell_60403/
│   ├── Cell_60644/
│   └── Cell_60710/
└── A Dataset for .../              Mendeley raw dataset
    └── CALB L148N58A testing campaign/
        ├── Raw Data/
        └── Processed Data/
```
