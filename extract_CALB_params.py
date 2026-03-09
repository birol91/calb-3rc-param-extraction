"""
CALB L148N58A - Mendeley Dataset'ten 3RC ECM Parametre Cikarma
===============================================================
Bu script Mendeley veri setindeki HPPC ve C/20 test verilerinden
her hucre icin R0, R1, R2, R3, tau1, tau2, tau3, Em (OCV) ve kapasite degerlerini cikarir.

Gereksinimler:
    pip install scipy numpy openpyxl

Kullanim:
    python extract_CALB_params.py

Ciktilar:
    - Her hucre icin 3 .mat dosyasi (batteryParameterEstimation_results_3RC_XXdegC.mat)
    - all_cell_params.json (tum parametreler)
    - Konsola detayli tablo + kiyaslama matrisi
    - comparison_table.xlsx (Excel kiyaslama tablosu)

Dogrulama Notlari:
    - Akim konvansiyonu: Negatif = discharge (dogrulandi, HPPC verisinde -58A = discharge)
    - Ornekleme hizi: HPPC pulse baslangicinida 10 Hz (0.1s aralik)
      Ilk veri noktasinda dV = 0.0672V, 0.1s sonra dV = 0.0681V (fark 0.9mV)
      R0 icin RC kontaminasyonu ihmal edilebilir seviyede.
    - Curve fitting bounds: 58Ah prismatik hucrenin dusuk ic direnci nedeniyle
      voltaj genlik ust siniri 0.1V (toplam pulse dV ~ 0.06V)
"""

import scipy.io as sio
import numpy as np
from scipy.optimize import curve_fit
import os
import json
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, Border, Side, PatternFill
import warnings

warnings.filterwarnings('ignore')

# =============================================================================
# KONFIGÜRASYON
# =============================================================================

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATASET_ROOT = os.path.join(
    SCRIPT_DIR,
    'A Dataset for Large Prismatic Lithium-Ion Battery Cells (CALB L148N58A) '
    'Comprehensive Characterization and Real-World Driving Cycles',
    'CALB L148N58A testing campaign',
    'Processed Data'
)

TEMPERATURES = [10, 25, 40]  # degC
TEMP_FOLDERS = ['Temperature_10C', 'Temperature_25C', 'Temperature_40C']

CELL_IDS = [
    '59294', '59485', '59627', '59690', '59861',
    '60031', '60129', '60195', '60403', '60644', '60710'
]

SOC_BREAKPOINTS = [1.0, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1, 0.0]


# =============================================================================
# 3RC RELAXATION MODELI
# =============================================================================

def model_3RC_relax(t_rel, A1, tau1, A2, tau2, A3, tau3):
    """
    Pulse sonrasi voltaj toparlanma (relaxation) modeli.
    dV(t) = A1*exp(-t/tau1) + A2*exp(-t/tau2) + A3*exp(-t/tau3)
    """
    return A1 * np.exp(-t_rel / tau1) + A2 * np.exp(-t_rel / tau2) + A3 * np.exp(-t_rel / tau3)


# =============================================================================
# HPPC PARAMETRE CIKARMA
# =============================================================================

def extract_hppc_params(time_s, voltage, current):
    """
    HPPC verisinden 3RC esdeger devre parametrelerini cikarir.

    HPPC Test Deseni (her SOC noktasinda):
        1) 10s discharge pulse (-58A, 1C)  --> R0 + RC fitting icin
        2) 600s rest
        3) 10s charge pulse (+37.7A)
        4) 600s rest
        5) 360s sustained discharge (SOC'u ~%10 dusurme)
        6) 3600s rest (OCV stabilize)

    R0 Hesabi:
        Pulse basladigi andaki ANI voltaj dususu / pulse akimi
        R0 = (V_before - V_instant_after) / I_pulse
        NOT: 10Hz orneklemede ilk noktadaki RC kontaminasyonu ~0.9mV (ihmal edilebilir)

    R1, R2, R3, tau1, tau2, tau3 Hesabi:
        Pulse bittikten sonraki relaxation (rest) bolgesindeki
        voltaj toparlanma egrisine 3-eksponansiyel curve fitting:
        dV(t) = A1*exp(-t/tau1) + A2*exp(-t/tau2) + A3*exp(-t/tau3)
        Ri = Ai / I_pulse

    Akim konvansiyonu: Negatif = discharge (dogrulandi)
    """
    # ----- Adim 1: Akim sicramalarini tespit et -----
    dI_arr = np.diff(current)
    jump_idx = np.where(np.abs(dI_arr) > 5)[0]

    # ----- Adim 2: Discharge pulse'lari bul -----
    # Negatif akim = discharge (dogrulandi: I<-50A iken V duser)
    pulses = []
    for j in jump_idx:
        if current[j] > -5 and current[j + 1] < -50:
            start = j + 1

            for k in jump_idx:
                if k > start and current[k] < -50 and current[k + 1] > -5:
                    end_idx = k
                    duration = time_s[end_idx] - time_s[start]
                    pulses.append({
                        'start': start,
                        'end': end_idx,
                        'duration': duration,
                        'type': 'short' if duration < 15 else 'long',
                        'V_before': voltage[j],
                        'V_instant': voltage[start],
                        'I_pulse': abs(np.mean(current[start:end_idx + 1]))
                    })
                    break

    # ----- Adim 3: Sadece kisa (10s) pulse'lari sec -----
    short_pulses = [p for p in pulses if p['type'] == 'short']

    R0_vals = []
    R1_vals = []
    R2_vals = []
    R3_vals = []
    tau1_vals = []
    tau2_vals = []
    tau3_vals = []

    for p in short_pulses:
        # ----- R0 Hesabi -----
        dV_instant = p['V_before'] - p['V_instant']
        R0 = dV_instant / p['I_pulse']
        R0_vals.append(R0)

        # ----- RC Fitting (Relaxation Bolgesi) -----
        rest_start = p['end'] + 1

        # Rest bitisi: bir sonraki buyuk akim degisimi
        # Threshold 5A: kucuk akim gurultusu (<2A) filtre edilir,
        # charge pulse baslangici (~37.7A) yakalanir -> rest dogru biter
        rest_end = rest_start
        for j in range(rest_start + 1, min(rest_start + 10000, len(current))):
            if abs(current[j]) > 5:
                rest_end = j - 1
                break
        else:
            rest_end = min(rest_start + 6000, len(current) - 1)

        t_rest = time_s[rest_start:rest_end + 1] - time_s[rest_start]
        V_rest = voltage[rest_start:rest_end + 1]

        if len(t_rest) < 10:
            R1_vals.append(np.nan); R2_vals.append(np.nan); R3_vals.append(np.nan)
            tau1_vals.append(np.nan); tau2_vals.append(np.nan); tau3_vals.append(np.nan)
            continue

        V_inf = V_rest[-1]
        dV = V_inf - V_rest

        try:
            p0 = [
                max(dV[0] * 0.5, 1e-5), 0.5,
                max(dV[0] * 0.3, 1e-5), 5.0,
                max(dV[0] * 0.2, 1e-5), 50.0
            ]
            # Bounds: 58Ah hucre icin toplam pulse dV ~ 0.06V
            # Voltaj genlik ust siniri 0.1V (0.5V'dan dusuruldu, daha stabil fit)
            bounds_lower = [0, 0.01, 0, 0.1, 0, 1.0]
            bounds_upper = [0.1, 10, 0.1, 100, 0.1, 1000]

            popt, _ = curve_fit(
                model_3RC_relax, t_rest, dV,
                p0=p0,
                bounds=(bounds_lower, bounds_upper),
                maxfev=50000
            )

            A1, t1, A2, t2, A3, t3 = popt
            I_p = p['I_pulse']

            R1_vals.append(A1 / I_p)
            R2_vals.append(A2 / I_p)
            R3_vals.append(A3 / I_p)
            tau1_vals.append(t1)
            tau2_vals.append(t2)
            tau3_vals.append(t3)

        except Exception:
            R1_vals.append(np.nan); R2_vals.append(np.nan); R3_vals.append(np.nan)
            tau1_vals.append(np.nan); tau2_vals.append(np.nan); tau3_vals.append(np.nan)

    return (
        np.array(R0_vals), np.array(R1_vals), np.array(R2_vals), np.array(R3_vals),
        np.array(tau1_vals), np.array(tau2_vals), np.array(tau3_vals),
        len(short_pulses)
    )


# =============================================================================
# KAPASITE VE OCV CIKARMA (C/20 Discharge)
# =============================================================================

def extract_capacity_and_ocv(time_s, voltage, current, soc_points):
    """
    C/20 discharge verisinden kapasite ve OCV vs SOC egrisini cikarir.
    C/20 = 2.9A sabit akimla tam desarj. IR drop ~ 0.003V (ihmal edilebilir).
    """
    dt = np.diff(time_s)
    cap_Ah = np.sum(np.abs(current[1:]) * dt) / 3600

    Ah_cum = np.cumsum(np.abs(current[1:]) * dt) / 3600
    Ah_cum = np.insert(Ah_cum, 0, 0)

    SOC = 1 - (Ah_cum / cap_Ah)

    SOC_sorted, idx = np.unique(SOC, return_index=True)
    sort_order = np.argsort(SOC_sorted)
    SOC_asc = SOC_sorted[sort_order]
    V_asc = voltage[idx[sort_order]]

    Em = np.interp(soc_points, SOC_asc, V_asc)

    return cap_Ah, Em


# =============================================================================
# SOC_LUT'A INTERPOLASYON
# =============================================================================

def interpolate_to_soc_lut(values, n_pulses, soc_lut):
    """
    HPPC'den cikan pulse bazli degerleri 11 noktali SOC_LUT'a interpole eder.
    """
    if n_pulses == 10:
        soc_hppc = np.linspace(1.0, 0.1, n_pulses)
    elif n_pulses == 9:
        soc_hppc = np.linspace(1.0, 0.2, n_pulses)
    else:
        soc_hppc = np.linspace(1.0, max(0.0, 1.0 - n_pulses * 0.1), n_pulses)

    soc_lut = np.array(soc_lut)
    interp_vals = np.interp(soc_lut[::-1], soc_hppc[::-1], values[::-1])[::-1]
    return interp_vals


# =============================================================================
# .MAT DOSYASI OLUSTURMA (Simulink Uyumlu)
# =============================================================================

def save_cell_mat_files(cell_id, all_results, output_dir):
    """
    Her hucre icin 3 adet .mat dosyasi olusturur:
      - batteryParameterEstimation_results_3RC_10degC.mat
      - batteryParameterEstimation_results_3RC_25degC.mat
      - batteryParameterEstimation_results_3RC_40degC.mat

    Her .mat dosyasinin icerigi (goruntudeki formatla ayni):
      Em       : OCV vs SOC (V)
      R0       : Terminal direnc vs SOC (Ohm)
      R1       : 1. RC direnc vs SOC (Ohm)
      R2       : 2. RC direnc vs SOC (Ohm)
      R3       : 3. RC direnc vs SOC (Ohm)
      SOC_LUT  : SOC breakpoint'leri
      tau1     : 1. RC zaman sabiti vs SOC (s)
      tau2     : 2. RC zaman sabiti vs SOC (s)
      tau3     : 3. RC zaman sabiti vs SOC (s)
    """
    cell_dir = os.path.join(output_dir, f'Cell_{cell_id}')
    os.makedirs(cell_dir, exist_ok=True)

    for temp in TEMPERATURES:
        key = f"{cell_id}_T{temp}C"
        r = all_results[key]

        mat_data = {
            'Em':      np.array(r['Em'], dtype=np.float64),
            'R0':      np.array(r['R0'], dtype=np.float64),
            'R1':      np.array(r['R1'], dtype=np.float64),
            'R2':      np.array(r['R2'], dtype=np.float64),
            'R3':      np.array(r['R3'], dtype=np.float64),
            'SOC_LUT': np.array(r['SOC_LUT'], dtype=np.float64),
            'tau1':    np.array(r['tau1'], dtype=np.float64),
            'tau2':    np.array(r['tau2'], dtype=np.float64),
            'tau3':    np.array(r['tau3'], dtype=np.float64),
        }

        filename = f'batteryParameterEstimation_results_3RC_{temp}degC.mat'
        filepath = os.path.join(cell_dir, filename)
        sio.savemat(filepath, mat_data)

    return cell_dir


# =============================================================================
# KIYASLAMA MATRISI
# =============================================================================

def print_comparison_matrix(all_results):
    """
    11 hucre arasindaki parametre kiyaslama matrisini yazdirir.
    Her sicaklik icin ayri matris: Kapasite, R0_mean, R1_mean, tau1_mean, vb.
    """
    params_to_compare = [
        ('Capacity (Ah)', lambda r: r['capacity'], '.2f'),
        ('R0_mean (mOhm)', lambda r: np.mean(r['R0']) * 1000, '.3f'),
        ('R1_mean (mOhm)', lambda r: np.mean(r['R1']) * 1000, '.4f'),
        ('R2_mean (mOhm)', lambda r: np.mean(r['R2']) * 1000, '.4f'),
        ('R3_mean (mOhm)', lambda r: np.mean(r['R3']) * 1000, '.4f'),
        ('tau1_mean (s)',   lambda r: np.mean(r['tau1']), '.2f'),
        ('tau2_mean (s)',   lambda r: np.mean(r['tau2']), '.2f'),
        ('tau3_mean (s)',   lambda r: np.mean(r['tau3']), '.1f'),
    ]

    for temp in TEMPERATURES:
        print(f"\n{'=' * 130}")
        print(f"  KIYASLAMA MATRISI - T = {temp}°C")
        print(f"{'=' * 130}")

        # Header
        header = f"  {'Parametre':<20}"
        for cell_id in CELL_IDS:
            header += f" {cell_id:>9}"
        header += f" {'|ORT':>9} {'STD':>9}"
        print(header)
        print(f"  {'-' * 126}")

        for param_name, extract_fn, fmt in params_to_compare:
            line = f"  {param_name:<20}"
            vals = []
            for cell_id in CELL_IDS:
                key = f"{cell_id}_T{temp}C"
                val = extract_fn(all_results[key])
                vals.append(val)
                line += f" {val:>{9}{fmt}}"

            mean_val = np.mean(vals)
            std_val = np.std(vals)
            line += f" |{mean_val:>{8}{fmt}} {std_val:>{9}{fmt}}"
            print(line)

        # Outlier analizi
        print(f"  {'-' * 126}")
        r0_vals = []
        for cell_id in CELL_IDS:
            key = f"{cell_id}_T{temp}C"
            r0_vals.append(np.mean(all_results[key]['R0']) * 1000)
        r0_arr = np.array(r0_vals)
        r0_mean = np.mean(r0_arr)
        r0_std = np.std(r0_arr)
        outliers = [(CELL_IDS[i], r0_arr[i]) for i in range(len(CELL_IDS))
                     if abs(r0_arr[i] - r0_mean) > 2 * r0_std]
        if outliers:
            for cid, val in outliers:
                print(f"  OUTLIER: Cell {cid} R0 = {val:.3f} mOhm "
                      f"(ortalamadan {((val-r0_mean)/r0_mean)*100:+.1f}% sapma)")
        else:
            print(f"  Outlier tespit edilmedi (2-sigma kriteri)")


# =============================================================================
# EXCEL CIKTI
# =============================================================================

def save_comparison_excel(all_results, output_path):
    """
    Kiyaslama matrisini Excel dosyasina kaydeder.
    Her sicaklik icin ayri bir sayfa (sheet) olusturur.
    Ek olarak detayli SOC bazli parametreler icin de sayfalar olusturur.
    """
    wb = Workbook()
    # Varsayilan bos sayfayi kaldir
    wb.remove(wb.active)

    # Stiller
    header_font = Font(bold=True, size=11)
    header_fill = PatternFill(start_color='4472C4', end_color='4472C4', fill_type='solid')
    header_font_white = Font(bold=True, size=11, color='FFFFFF')
    center_align = Alignment(horizontal='center', vertical='center')
    thin_border = Border(
        left=Side(style='thin'),
        right=Side(style='thin'),
        top=Side(style='thin'),
        bottom=Side(style='thin')
    )
    outlier_fill = PatternFill(start_color='FFC7CE', end_color='FFC7CE', fill_type='solid')
    outlier_font = Font(bold=True, color='9C0006')

    params_to_compare = [
        ('Capacity (Ah)', lambda r: r['capacity'], '0.00'),
        ('R0_mean (mOhm)', lambda r: np.mean(r['R0']) * 1000, '0.000'),
        ('R1_mean (mOhm)', lambda r: np.mean(r['R1']) * 1000, '0.0000'),
        ('R2_mean (mOhm)', lambda r: np.mean(r['R2']) * 1000, '0.0000'),
        ('R3_mean (mOhm)', lambda r: np.mean(r['R3']) * 1000, '0.0000'),
        ('tau1_mean (s)', lambda r: np.mean(r['tau1']), '0.00'),
        ('tau2_mean (s)', lambda r: np.mean(r['tau2']), '0.00'),
        ('tau3_mean (s)', lambda r: np.mean(r['tau3']), '0.0'),
    ]

    # =========================================================================
    # Sayfa 1-3: Kiyaslama Matrisi (her sicaklik icin)
    # =========================================================================
    for temp in TEMPERATURES:
        ws = wb.create_sheet(title=f'Comparison_{temp}C')

        # Baslik satiri
        ws.cell(row=1, column=1, value='Parameter')
        ws.cell(row=1, column=1).font = header_font_white
        ws.cell(row=1, column=1).fill = header_fill
        ws.cell(row=1, column=1).alignment = center_align
        ws.cell(row=1, column=1).border = thin_border
        ws.column_dimensions['A'].width = 22

        for ci, cell_id in enumerate(CELL_IDS):
            col = ci + 2
            ws.cell(row=1, column=col, value=f'Cell {cell_id}')
            ws.cell(row=1, column=col).font = header_font_white
            ws.cell(row=1, column=col).fill = header_fill
            ws.cell(row=1, column=col).alignment = center_align
            ws.cell(row=1, column=col).border = thin_border
            ws.column_dimensions[ws.cell(row=1, column=col).column_letter].width = 14

        # Ortalama ve Std Dev sutunlari
        col_mean = len(CELL_IDS) + 2
        col_std = len(CELL_IDS) + 3
        for col, label in [(col_mean, 'Mean'), (col_std, 'Std Dev')]:
            ws.cell(row=1, column=col, value=label)
            ws.cell(row=1, column=col).font = header_font_white
            ws.cell(row=1, column=col).fill = header_fill
            ws.cell(row=1, column=col).alignment = center_align
            ws.cell(row=1, column=col).border = thin_border
            ws.column_dimensions[ws.cell(row=1, column=col).column_letter].width = 12

        # Veri satirlari
        for ri, (param_name, extract_fn, num_fmt) in enumerate(params_to_compare):
            row = ri + 2
            ws.cell(row=row, column=1, value=param_name)
            ws.cell(row=row, column=1).font = header_font
            ws.cell(row=row, column=1).border = thin_border

            vals = []
            for ci, cell_id in enumerate(CELL_IDS):
                key = f"{cell_id}_T{temp}C"
                val = extract_fn(all_results[key])
                vals.append(val)
                cell = ws.cell(row=row, column=ci + 2, value=val)
                cell.number_format = num_fmt
                cell.alignment = center_align
                cell.border = thin_border

            # Ortalama ve Std Dev
            mean_val = np.mean(vals)
            std_val = np.std(vals)
            cell_m = ws.cell(row=row, column=col_mean, value=mean_val)
            cell_m.number_format = num_fmt
            cell_m.alignment = center_align
            cell_m.border = thin_border
            cell_m.font = Font(bold=True)

            cell_s = ws.cell(row=row, column=col_std, value=std_val)
            cell_s.number_format = num_fmt
            cell_s.alignment = center_align
            cell_s.border = thin_border

        # Outlier tespiti (R0 icin)
        r0_vals = []
        for cell_id in CELL_IDS:
            key = f"{cell_id}_T{temp}C"
            r0_vals.append(np.mean(all_results[key]['R0']) * 1000)
        r0_arr = np.array(r0_vals)
        r0_mean = np.mean(r0_arr)
        r0_std = np.std(r0_arr)

        # R0 satirindaki outlier hucreleri isaretle
        r0_row = 3  # R0_mean satirinin row indeksi (2. parametre, row=3)
        for ci in range(len(CELL_IDS)):
            if abs(r0_arr[ci] - r0_mean) > 2 * r0_std:
                cell = ws.cell(row=r0_row, column=ci + 2)
                cell.fill = outlier_fill
                cell.font = outlier_font

        # Outlier notu
        note_row = len(params_to_compare) + 3
        outliers = [(CELL_IDS[i], r0_arr[i]) for i in range(len(CELL_IDS))
                     if abs(r0_arr[i] - r0_mean) > 2 * r0_std]
        if outliers:
            for oi, (cid, val) in enumerate(outliers):
                ws.cell(row=note_row + oi, column=1,
                        value=f'OUTLIER: Cell {cid} R0={val:.3f} mOhm '
                              f'({((val-r0_mean)/r0_mean)*100:+.1f}% from mean)')
                ws.cell(row=note_row + oi, column=1).font = outlier_font

    # =========================================================================
    # Sayfa 4: Ozet Tablo (Kapasite + R0, tum sicakliklar)
    # =========================================================================
    ws_sum = wb.create_sheet(title='Summary')

    headers = ['Cell', 'Cap@10C (Ah)', 'Cap@25C (Ah)', 'Cap@40C (Ah)',
               'R0@10C (mOhm)', 'R0@25C (mOhm)', 'R0@40C (mOhm)']
    for ci, h in enumerate(headers):
        cell = ws_sum.cell(row=1, column=ci + 1, value=h)
        cell.font = header_font_white
        cell.fill = header_fill
        cell.alignment = center_align
        cell.border = thin_border
        ws_sum.column_dimensions[cell.column_letter].width = 16

    for ri, cell_id in enumerate(CELL_IDS):
        row = ri + 2
        ws_sum.cell(row=row, column=1, value=cell_id).border = thin_border
        ws_sum.cell(row=row, column=1).alignment = center_align
        for ti, temp in enumerate(TEMPERATURES):
            key = f"{cell_id}_T{temp}C"
            r = all_results[key]
            cap_cell = ws_sum.cell(row=row, column=ti + 2, value=r['capacity'])
            cap_cell.number_format = '0.00'
            cap_cell.alignment = center_align
            cap_cell.border = thin_border

            r0_cell = ws_sum.cell(row=row, column=ti + 5, value=np.mean(r['R0']) * 1000)
            r0_cell.number_format = '0.000'
            r0_cell.alignment = center_align
            r0_cell.border = thin_border

    # Istatistik satirlari
    stat_row = len(CELL_IDS) + 3
    for si, (stat_name, func) in enumerate([('Mean', np.mean), ('Std Dev', np.std),
                                             ('Min', np.min), ('Max', np.max)]):
        row = stat_row + si
        ws_sum.cell(row=row, column=1, value=stat_name)
        ws_sum.cell(row=row, column=1).font = header_font
        ws_sum.cell(row=row, column=1).border = thin_border
        for ti, temp in enumerate(TEMPERATURES):
            caps = [all_results[f"{cid}_T{temp}C"]['capacity'] for cid in CELL_IDS]
            r0s = [np.mean(all_results[f"{cid}_T{temp}C"]['R0']) * 1000 for cid in CELL_IDS]

            cap_cell = ws_sum.cell(row=row, column=ti + 2, value=func(caps))
            cap_cell.number_format = '0.00'
            cap_cell.alignment = center_align
            cap_cell.border = thin_border
            cap_cell.font = Font(bold=True)

            r0_cell = ws_sum.cell(row=row, column=ti + 5, value=func(r0s))
            r0_cell.number_format = '0.000'
            r0_cell.alignment = center_align
            r0_cell.border = thin_border
            r0_cell.font = Font(bold=True)

    # =========================================================================
    # Sayfa 5-7: SOC Bazli Detayli Parametreler (her sicaklik icin)
    # =========================================================================
    soc_params = [
        ('Em (V)', 'Em', '0.0000'),
        ('R0 (Ohm)', 'R0', '0.000000'),
        ('R1 (Ohm)', 'R1', '0.000000'),
        ('R2 (Ohm)', 'R2', '0.000000'),
        ('R3 (Ohm)', 'R3', '0.000000'),
        ('tau1 (s)', 'tau1', '0.00'),
        ('tau2 (s)', 'tau2', '0.00'),
        ('tau3 (s)', 'tau3', '0.00'),
    ]

    for temp in TEMPERATURES:
        ws_det = wb.create_sheet(title=f'Detail_{temp}C')

        current_row = 1
        for cell_id in CELL_IDS:
            key = f"{cell_id}_T{temp}C"
            r = all_results[key]

            # Hucre basligi
            cell = ws_det.cell(row=current_row, column=1,
                               value=f'Cell {cell_id} - {temp}°C - Cap={r["capacity"]:.2f} Ah')
            cell.font = Font(bold=True, size=12)
            current_row += 1

            # SOC header
            ws_det.cell(row=current_row, column=1, value='Parameter')
            ws_det.cell(row=current_row, column=1).font = header_font_white
            ws_det.cell(row=current_row, column=1).fill = header_fill
            ws_det.cell(row=current_row, column=1).border = thin_border
            ws_det.column_dimensions['A'].width = 14

            for si, soc in enumerate(SOC_BREAKPOINTS):
                col = si + 2
                cell = ws_det.cell(row=current_row, column=col, value=f'SOC={soc}')
                cell.font = header_font_white
                cell.fill = header_fill
                cell.alignment = center_align
                cell.border = thin_border
                ws_det.column_dimensions[cell.column_letter].width = 12
            current_row += 1

            # Parametre satirlari
            for param_name, param_key, num_fmt in soc_params:
                ws_det.cell(row=current_row, column=1, value=param_name)
                ws_det.cell(row=current_row, column=1).font = header_font
                ws_det.cell(row=current_row, column=1).border = thin_border
                for si, val in enumerate(r[param_key]):
                    cell = ws_det.cell(row=current_row, column=si + 2, value=val)
                    cell.number_format = num_fmt
                    cell.alignment = center_align
                    cell.border = thin_border
                current_row += 1

            current_row += 1  # Bosluk

    wb.save(output_path)
    return output_path


# =============================================================================
# ANA HESAPLAMA
# =============================================================================

def main():
    print("=" * 90)
    print("  CALB L148N58A - 3RC Parametre Cikarma")
    print("  Mendeley Dataset -> R0, R1, R2, R3, tau1, tau2, tau3, Em, Kapasite")
    print("=" * 90)

    # Veri seti kontrolu
    if not os.path.isdir(DATASET_ROOT):
        print(f"\nHATA: Veri seti bulunamadi!")
        print(f"Beklenen dizin: {DATASET_ROOT}")
        print("Mendeley'den indirdigin veri setini bu script ile ayni klasore koy.")
        return

    all_results = {}

    for t_idx, (temp, temp_folder) in enumerate(zip(TEMPERATURES, TEMP_FOLDERS)):
        print(f"\n--- {temp}°C isleniyor ---")

        for cell_id in CELL_IDS:
            key = f"{cell_id}_T{temp}C"

            # ========== HPPC Verisi ==========
            hppc_path = os.path.join(DATASET_ROOT, temp_folder, 'HPPC_1C', f'{cell_id}.mat')
            if not os.path.exists(hppc_path):
                print(f"  ATLANDI (HPPC yok): {key}")
                continue

            raw = sio.loadmat(hppc_path)
            data = raw['Data'][0, 0]
            t_h = data['Times'].flatten().astype(float)
            V_h = data['VoltageV'].flatten().astype(float)
            I_h = data['CurrentA'].flatten().astype(float)

            R0, R1, R2, R3, tau1, tau2, tau3, n_pulses = extract_hppc_params(t_h, V_h, I_h)

            # ========== C/20 Discharge Verisi ==========
            c20_path = os.path.join(DATASET_ROOT, temp_folder, 'C20_Discharge', f'{cell_id}.mat')
            if not os.path.exists(c20_path):
                c20_path = os.path.join(DATASET_ROOT, temp_folder, 'C20_discharge', f'{cell_id}.mat')

            cap = np.nan
            Em = np.full(len(SOC_BREAKPOINTS), np.nan)

            if os.path.exists(c20_path):
                raw_c = sio.loadmat(c20_path)
                data_c = raw_c['Data'][0, 0]
                t_c = data_c['Times'].flatten().astype(float)
                V_c = data_c['VoltageV'].flatten().astype(float)
                I_c = data_c['CurrentA'].flatten().astype(float)
                cap, Em = extract_capacity_and_ocv(t_c, V_c, I_c, SOC_BREAKPOINTS)

            # ========== SOC_LUT'a Interpolasyon ==========
            R0_interp = interpolate_to_soc_lut(R0, n_pulses, SOC_BREAKPOINTS)
            R1_interp = interpolate_to_soc_lut(R1, n_pulses, SOC_BREAKPOINTS)
            R2_interp = interpolate_to_soc_lut(R2, n_pulses, SOC_BREAKPOINTS)
            R3_interp = interpolate_to_soc_lut(R3, n_pulses, SOC_BREAKPOINTS)
            tau1_interp = interpolate_to_soc_lut(tau1, n_pulses, SOC_BREAKPOINTS)
            tau2_interp = interpolate_to_soc_lut(tau2, n_pulses, SOC_BREAKPOINTS)
            tau3_interp = interpolate_to_soc_lut(tau3, n_pulses, SOC_BREAKPOINTS)

            # Negatif deger kontrolu
            R0_interp = np.maximum(R0_interp, 1e-6)
            R1_interp = np.maximum(R1_interp, 1e-6)
            R2_interp = np.maximum(R2_interp, 1e-6)
            R3_interp = np.maximum(R3_interp, 1e-6)
            tau1_interp = np.maximum(tau1_interp, 0.01)
            tau2_interp = np.maximum(tau2_interp, 0.1)
            tau3_interp = np.maximum(tau3_interp, 1.0)

            all_results[key] = {
                'cell': cell_id,
                'temp': temp,
                'capacity': float(cap),
                'n_pulses': n_pulses,
                'SOC_LUT': SOC_BREAKPOINTS,
                'Em': Em.tolist(),
                'R0': R0_interp.tolist(),
                'R1': R1_interp.tolist(),
                'R2': R2_interp.tolist(),
                'R3': R3_interp.tolist(),
                'tau1': tau1_interp.tolist(),
                'tau2': tau2_interp.tolist(),
                'tau3': tau3_interp.tolist()
            }

            print(f"  OK: Cell {cell_id} - Cap={cap:.2f} Ah, "
                  f"{n_pulses} pulse, R0_mean={np.mean(R0)*1000:.3f} mOhm")

    # =============================================================================
    # JSON KAYDET
    # =============================================================================
    output_path = os.path.join(SCRIPT_DIR, 'all_cell_params.json')
    with open(output_path, 'w') as fp:
        json.dump(all_results, fp, indent=2)
    print(f"\nJSON kaydedildi: {output_path}")

    # =============================================================================
    # HER HUCRE ICIN .MAT DOSYALARI OLUSTUR
    # =============================================================================
    print("\n" + "=" * 90)
    print("  .MAT DOSYALARI OLUSTURULUYOR")
    print("=" * 90)

    mat_output_dir = os.path.join(SCRIPT_DIR, 'results')
    os.makedirs(mat_output_dir, exist_ok=True)

    for cell_id in CELL_IDS:
        cell_dir = save_cell_mat_files(cell_id, all_results, mat_output_dir)
        print(f"  Cell {cell_id}: {cell_dir}/")
        for temp in TEMPERATURES:
            fname = f'batteryParameterEstimation_results_3RC_{temp}degC.mat'
            print(f"    -> {fname}")

    print(f"\nToplam {len(CELL_IDS) * len(TEMPERATURES)} .mat dosyasi olusturuldu.")

    # =============================================================================
    # KIYASLAMA MATRISI
    # =============================================================================
    print_comparison_matrix(all_results)

    # =============================================================================
    # EXCEL CIKTI
    # =============================================================================
    excel_path = os.path.join(SCRIPT_DIR, 'comparison_table.xlsx')
    save_comparison_excel(all_results, excel_path)
    print(f"\nExcel kaydedildi: {excel_path}")

    # =============================================================================
    # OZET TABLO
    # =============================================================================
    print(f"\n{'=' * 90}")
    print("  OZET: TUM HUCRELER - Kapasite & Ortalama R0")
    print(f"{'=' * 90}")
    print(f"  {'Cell':<8} {'Cap@10C':>8} {'Cap@25C':>8} {'Cap@40C':>8} "
          f"{'R0@10C':>10} {'R0@25C':>10} {'R0@40C':>10}")
    print(f"  {'':>8} {'(Ah)':>8} {'(Ah)':>8} {'(Ah)':>8} "
          f"{'(mOhm)':>10} {'(mOhm)':>10} {'(mOhm)':>10}")
    print(f"  {'-' * 80}")

    for cell_id in CELL_IDS:
        caps = []
        r0s = []
        for temp in TEMPERATURES:
            key = f"{cell_id}_T{temp}C"
            r = all_results[key]
            caps.append(r['capacity'])
            r0s.append(np.mean(r['R0']) * 1000)
        print(f"  {cell_id:<8} {caps[0]:>8.2f} {caps[1]:>8.2f} {caps[2]:>8.2f} "
              f"{r0s[0]:>10.3f} {r0s[1]:>10.3f} {r0s[2]:>10.3f}")

    print(f"  {'-' * 80}")
    for stat_name, func in [('Ortalama', np.mean), ('Std Dev', np.std),
                             ('Min', np.min), ('Max', np.max)]:
        caps_all = [[], [], []]
        r0s_all = [[], [], []]
        for cell_id in CELL_IDS:
            for ti, temp in enumerate(TEMPERATURES):
                key = f"{cell_id}_T{temp}C"
                r = all_results[key]
                caps_all[ti].append(r['capacity'])
                r0s_all[ti].append(np.mean(r['R0']) * 1000)
        caps_stat = [func(c) for c in caps_all]
        r0s_stat = [func(r) for r in r0s_all]
        print(f"  {stat_name:<8} {caps_stat[0]:>8.2f} {caps_stat[1]:>8.2f} {caps_stat[2]:>8.2f} "
              f"{r0s_stat[0]:>10.3f} {r0s_stat[1]:>10.3f} {r0s_stat[2]:>10.3f}")

    # =============================================================================
    # HER HUCRE DETAYLI TABLO
    # =============================================================================
    print(f"\n{'=' * 120}")
    print("  DETAYLI TABLOLAR (Her Hucre x Her Sicaklik)")
    print(f"{'=' * 120}")

    for cell_id in CELL_IDS:
        print(f"\n{'─' * 120}")
        print(f"  CELL {cell_id}")
        print(f"{'─' * 120}")

        for temp in TEMPERATURES:
            key = f"{cell_id}_T{temp}C"
            r = all_results[key]

            print(f"\n  T = {temp}°C | Kapasite = {r['capacity']:.2f} Ah | Pulse = {r['n_pulses']}")
            header = f"  {'Param':<10}"
            for soc in SOC_BREAKPOINTS:
                header += f" {'SOC='+str(soc) if soc == 1.0 else str(soc):>8}"
            print(header)
            print(f"  {'-' * 108}")

            for param_name, param_key, fmt in [
                ('Em (V)',    'Em',   '8.4f'),
                ('R0 (Ohm)', 'R0',   '8.4f'),
                ('R1 (Ohm)', 'R1',   '8.4f'),
                ('R2 (Ohm)', 'R2',   '8.4f'),
                ('R3 (Ohm)', 'R3',   '8.4f'),
                ('tau1 (s)',  'tau1', '8.2f'),
                ('tau2 (s)',  'tau2', '8.2f'),
                ('tau3 (s)',  'tau3', '8.2f'),
            ]:
                line = f"  {param_name:<10}"
                for v in r[param_key]:
                    line += f" {v:{fmt}}"
                print(line)

    print(f"\n{'=' * 90}")
    print(f"  Toplam {len(all_results)} kombinasyon (11 hucre x 3 sicaklik) islendi.")
    print(f"  .mat dosyalari: {mat_output_dir}/")
    print(f"  JSON: {output_path}")
    print(f"{'=' * 90}")


if __name__ == '__main__':
    main()
