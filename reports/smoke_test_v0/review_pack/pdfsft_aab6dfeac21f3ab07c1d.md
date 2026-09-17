# pdfsft_aab6dfeac21f3ab07c1d

- Domain: `Spacecraft radiation-hardness assurance and reliability engineering`
- Primary evidence: `visual_spatial`
- Generator: `gpt-6-astra` / `generator_v0+manual_review_fix_001`
- Static checks: `True`
- Independent verifier: `passed`
- Eligible for difficulty: `True`
- Original PDF: [7111746b33b7a23a1ac4d983b15970525d4c9bd79206f20afb79bd9342f9bc4b.pdf](/mnt/weka/home/yuan.huang/GDP_pdf_benchmark/raw_pdfs/7111746b33b7a23a1ac4d983b15970525d4c9bd79206f20afb79bd9342f9bc4b.pdf)

## Question

Prepare a preliminary shielding trade note for an SFT2907A bipolar-transistor application being extended from a one-year GEO mission to a ten-year GEO mission. Use the handbook’s Figure 18 example and a maximum cumulative-radiation failure probability of 20%.

For each mission duration, select the smallest aluminum shield thickness among the plotted GEO markers that meets the limit; do not interpolate between markers. Report its approximate failure probability and the immediately preceding, thinner marked point that fails the limit. Calculate the absolute and percentage increase in selected shielding for the extension.

Also assess the proposed alternative of retaining the one-year shielding and adding an identical, unpowered cold spare under the same radiation exposure. Explain whether the handbook supports that substitution and identify its stated redundancy exception. Finish with the applicability condition that must be checked before carrying this illustrative trade into the actual mission assessment. Cite PDF page numbers.

## Gold answer

### Preliminary shielding trade
Using Figure 18’s diamond markers for one-year GEO and triangle markers for ten-year GEO (PDF p. 64):

| GEO duration | Immediately thinner marked point—fails 20% limit | Smallest marked thickness meeting limit |
|---|---|---|
| 1 year | 125 mils: Pf ≈ 0.48 | **150 mils: Pf ≈ 0.15** |
| 10 years | 200 mils: Pf ≈ 0.64 | **250 mils: Pf ≈ 0.14** |

The extension requires **100 mils more aluminum**, an increase of **66.7%**: 250 − 150 = 100 mils; 100/150 × 100 ≈ 66.7%. These are selections among illustrated markers, not interpolated continuous minima.

**The identical cold spare does not justify retaining the one-year shielding.** The handbook states that cumulative radiation effects can accrue even while semiconductor devices are off, so ordinary cold sparing/redundancy is not an effective mitigation. Its stated redundancy exception is a functionally equivalent backup using a different design and different semiconductor parts; tolerance to parametric degradation is another possible system-level masking approach (PDF p. 70).

This is an illustrative SFT2907A trade, not a generic shielding qualification. Before applying it, confirm that suitable ground-based TID/TNID/DDD data exist for the actual device parameter or radiation-sensitive application (PDF p. 64), and assess the specific mission environment, application, and lifetime (PDF p. 69).

## Independent reconstruction

### Preliminary shielding trade note — SFT2907A GEO application

Using the **20% maximum cumulative-radiation failure probability** and selecting only plotted GEO markers—without interpolation—the Figure 18 results are:

| Mission | Smallest marked aluminum thickness meeting limit | Approx. failure probability | Immediately preceding thinner marker (fails) |
|---|---:|---:|---:|
| GEO, 1 year | **150 mils** | **≈0.15 (15%)** | **125 mils: ≈0.48 (48%)** |
| GEO, 10 years | **250 mils** | **≈0.15 (15%)** | **200 mils: ≈0.64 (64%)** |

These are approximate graphical readings from the handbook’s illustrative SFT2907A curves. Both selected points satisfy the requirement, while their immediately preceding markers exceed 20%. (PDF p. 64)

**Shielding increase for the mission extension:**
- Absolute increase: **250 − 150 = 100 mils**
- Percentage increase relative to the one-year selection: **100/150 × 100 ≈ 66.7%**

### Cold-spare alternative
Retaining the one-year shielding and adding an **identical, unpowered cold spare under the same radiation exposure is not supported as an equivalent substitution**. The handbook states that cold sparing or redundancy is ineffective for cumulative effects because those effects can accrue in semiconductor devices even while they are off. Thus, the spare can experience cumulative parametric degradation along with the active device. (PDF p. 70)

The stated redundancy exception is **diverse redundancy**: functional backup provided by a different design performing the same function but using different semiconductor parts. The handbook also identifies system tolerance to parametric degradation or drift as a possible form of system masking. (PDF p. 70)

### Applicability condition
Before using this illustrative trade in the actual mission assessment, confirm that the failure determination is performed for the **specific mission environment, application, and lifetime** (PDF p. 69), and that applicable ground-based TID/TNID/DDD data exist for the device/application; the handbook characterizes the transistor example as simplified. (PDF p. 64)

## Independent audit

- Gold supported: `True`
- Input complete: `True`
- Requires human review: `False`
- Verified claims: `c1, c2, c3, c4, c5, c6, c7`
- Disputed claims: `none`
- Failure reasons: `none`

## Atomic rubric

| ID | Type | Severity | Criterion |
|---|---|---|---|
| r1 | primary_intent | certain_dealbreaker | Selects 150 mils as the smallest eligible plotted one-year GEO marker. |
| r2 | primary_intent | certain_dealbreaker | Selects 250 mils as the smallest eligible plotted ten-year GEO marker. |
| r3 | supporting_detail | major | Correctly binds diamonds to one-year GEO and triangles to ten-year GEO, rather than using either LEO series. |
| r4 | supporting_detail | major | For one-year GEO, reports the selected-point probability near 0.15 and the immediately thinner marker at 125 mils with probability near 0.48; accepts approximate readings of 0.13–0.17 and 0.45–0.51, respectively. |
| r5 | supporting_detail | major | For ten-year GEO, reports the selected-point probability near 0.14 and the immediately thinner marker at 200 mils with probability near 0.64; accepts approximate readings of 0.12–0.17 and 0.60–0.68, respectively. |
| r6 | supporting_detail | major | Calculates the absolute increase as 250 − 150 = 100 mils, preserving the chart’s thickness unit. |
| r7 | supporting_detail | major | Calculates approximately 66.7% growth using the one-year selection, 150 mils, as the denominator. |
| r8 | dodged_bullet | certain_dealbreaker | Rejects the identical cold-spare substitution on the handbook’s stated ground that cumulative radiation effects can accrue in the off state; does not assume the spare is protected simply because it is unpowered. |
| r9 | supporting_detail | major | Identifies the redundancy exception as a different design using different semiconductor parts to perform the same function, rather than merely adding another identical device. |
| r10 | dodged_bullet | major | States both applicability gates: suitable ground-based TID/TNID/DDD data must exist for the actual device parameter or radiation-sensitive application, and the determination must use the specific mission environment, application, and lifetime. |
| r11 | dodged_bullet | major | Keeps the recommendation restricted to plotted marker choices rather than replacing them with interpolated threshold crossings. |
| r12 | supporting_detail | minor | Cites PDF page 64 for Figure 18, page 70 for the cold-spare rule and exception, and page 69 for mission-specific applicability. |

## Evidence pages

### PDF page 64

![PDF page 64](/mnt/weka/home/yuan.huang/GDP_pdf_benchmark/parsed/7111746b33b7a23a1ac4d983b15970525d4c9bd79206f20afb79bd9342f9bc4b/page_0064.png)

- `e_chart` · role `base_value` · key `True` · bbox `(0.150, 0.435, 0.850, 0.770)`
  - Figure 18. Failure Probabilities for the SFT2907A Bipolar Transistor ... Aluminum Shield Thickness (mils). GEO markers support approximately (125, 0.48), (150, 0.15) for 1 year and (200, 0.64), (250, 0.14) for 10 years.
- `e_legend` · role `legend` · key `False` · bbox `(0.596, 0.460, 0.818, 0.552)`
  - Diamond: GEO, 1 Yr. Triangle: GEO, 10 Yrs.
- `e_ground_data` · role `qualifier` · key `True` · bbox `(0.105, 0.765, 0.895, 0.855)`
  - The simplified transistor example can determine success for a device parameter or sensitive application if ground-based TID/TNID/DDD data exist.

### PDF page 69

![PDF page 69](/mnt/weka/home/yuan.huang/GDP_pdf_benchmark/parsed/7111746b33b7a23a1ac4d983b15970525d4c9bd79206f20afb79bd9342f9bc4b/page_0069.png)

- `e_mission_scope` · role `qualifier` · key `True` · bbox `(0.018, 0.455, 0.984, 0.540)`
  - For any radiation likelihood ... the determination must be done for the specific mission environment, application, and lifetime.

### PDF page 70

![PDF page 70](/mnt/weka/home/yuan.huang/GDP_pdf_benchmark/parsed/7111746b33b7a23a1ac4d983b15970525d4c9bd79206f20afb79bd9342f9bc4b/page_0070.png)

- `e_cold_spare` · role `exception` · key `True` · bbox `(0.020, 0.055, 0.980, 0.170)`
  - Cold sparing or redundancy is not an effective mitigation because cumulative effects can accrue even in the off state ... diverse redundancy ... a different design ... different semiconductor parts.

## Claims and derivations

- `c1`: Figure 18 identifies one-year GEO with diamond markers and ten-year GEO with triangle markers.  
  Supported by: `e_legend`
- `c2`: For one-year GEO, the immediately preceding thinner marker is approximately 125 mils at Pf 0.48, while the smallest marked thickness meeting Pf ≤ 0.20 is 150 mils at approximately Pf 0.15.  
  Supported by: `c1, e_chart`
- `c3`: For ten-year GEO, the immediately preceding thinner marker is approximately 200 mils at Pf 0.64, while the smallest marked thickness meeting Pf ≤ 0.20 is 250 mils at approximately Pf 0.14.  
  Supported by: `c1, e_chart`
- `c4`: The selected shielding increases by 100 mils, or approximately 66.7% relative to the one-year selection.  
  Supported by: `c2, c3`
- `c5`: An identical unpowered cold spare under the same exposure does not provide the handbook-supported mitigation needed to substitute for additional cumulative-radiation shielding, because cumulative effects can accrue in the off state.  
  Supported by: `e_cold_spare`
- `c6`: The handbook identifies diverse redundancy using a different design and different semiconductor parts performing the same function as an exception; it also identifies tolerance to parametric degradation or drift as system masking.  
  Supported by: `e_cold_spare`
- `c7`: The plotted result is an SFT2907A example; applying the approach requires suitable ground-based TID/TNID/DDD data for the actual device parameter or radiation-sensitive application, and an actual radiation-likelihood determination must use the specific mission environment, application, and lifetime.  
  Supported by: `e_chart, e_ground_data, e_mission_scope`

### Derivations

- `c2` = `Limit = 20/100 = 0.20. On the diamond-marked GEO, 1 Yr curve: Pf(125 mils) ≈ 0.48 > 0.20; Pf(150 mils) ≈ 0.15 ≤ 0.20. Select the minimum eligible plotted marker: 150 mils.`  
  Inputs: `c1, e_chart`
- `c3` = `On the triangle-marked GEO, 10 Yrs curve: Pf(200 mils) ≈ 0.64 > 0.20; Pf(250 mils) ≈ 0.14 ≤ 0.20. Select the minimum eligible plotted marker: 250 mils.`  
  Inputs: `c1, e_chart`
- `c4` = `Δshield = 250 − 150 = 100 mils; percentage increase = (250 − 150)/150 × 100 ≈ 66.7%.`  
  Inputs: `c2, c3`
- `c5` = `Identical unpowered spare under the same exposure falls under ordinary cold sparing, not the different-design/different-semiconductor exception; cumulative effects can accrue while off, so the proposed substitution is not supported.`  
  Inputs: `e_cold_spare`
- `c7` = `Scope of Figure 18 = SFT2907A example with specified orbit and duration. Apply the radiation-summary requirement for mission-specific environment, application, and lifetime before transferring its likelihoods to the actual mission.`  
  Inputs: `e_chart, e_mission_scope`
