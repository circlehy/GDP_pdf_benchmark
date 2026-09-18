# pdfsft_1ef2a218c4a76a94f3cc

- Domain: `aerospace_battery_safety`
- Primary evidence: `text_reasoning`
- Generator: `zai-org/GLM-5.3-Flash` / `generator_v2+sha256:501586c5f1ef+policy:007d1fc3`
- Static checks: `True`
- Independent verifier: `needs_review`
- Eligible for difficulty: `False`
- Original PDF: [8ee157a5465ef564105839ef5cedf8c511917057d76adb85e7642d21fa8e8c57.pdf](/mnt/weka/home/yuan.huang/GDP_pdf_benchmark/raw_pdfs/8ee157a5465ef564105839ef5cedf8c511917057d76adb85e7642d21fa8e8c57.pdf)
- Sample review decision: [sample_review_decision.json](/mnt/weka/home/yuan.huang/GDP_pdf_benchmark/reports/golden_v0_single_pdf_battery/review_pack/artifacts/pdfsft_1ef2a218c4a76a94f3cc/sample_review_decision.json)

## Question

You are the payload power engineer responsible for 20 zinc-air coin cells, each containing 5 grams of zinc, that must be stored for 12 months in open-circuit stand before installation in a Shuttle experiment. Using this handbook: (a) compute the hydrogen evolution rate of the battery at 21 degrees C and at 31 degrees C, and state how the rate behaves during discharge; (b) specify the storage conditions the handbook says will maintain at least 85 percent of initial capacity over the storage period, and identify the anomalous data point that must be excluded from that conclusion; (c) state the required storage orientation and the failure mechanism it prevents; (d) explain why the storage container cannot be sealed or purged with nitrogen, and name the applicable hydrogen control; and (e) describe how flight-packaged spare multicell batteries are packaged differently from the long-term storage practice.

## Gold answer

(a) The handbook gives 0.01 cc of hydrogen per hour per gram of zinc for zinc-air cells on open-circuit stand at 21 degrees C, with the rate approximately doubled for each 10 degrees C rise and halved for each 10 degrees C drop; during discharge the evolution is less. For 20 cells x 5 g = 100 g of zinc: 100 x 0.01 = 1.0 cc/hr at 21 degrees C, and 2.0 cc/hr at 31 degrees C. (b) Capacities exceeding 85 percent of initial values are maintained for up to 18 months with: (1) a 4 degrees C (commercial refrigerator) storage environment, (2) all air holes taped over with tape impermeable to oxygen and water vapor, and (3) taped cells stored in sealed bags. The 18-month untaped/4 degrees C data point (zero A-h) must be excluded because the sealed bag was found slit, an unintended variable that dried the cells out. (c) Cells must not be stored holes-down: free electrolyte runs onto the air diffusion membrane, blocks the air access holes, hydrogen from zinc corrosion (Zn + 2KOH -> K2ZnO2 + H2) builds pressure until electrolyte is forced out the positive-terminal perforations. Store all cells on their edge so some perforations always stay open to vent hydrogen. (d) The battery case cannot be sealed because oxygen is necessary for operation, and for that reason it also cannot be purged with nitrogen; the most applicable control is adequate ventilation. (e) Spare multicell batteries packaged for immediate flight storage do not have sealed air holes; they are sealed in an inner bag of Film-Pak 1177 (Ludlow, Holyoke, MA) per specification MIL-B-22191C, whereas long-term storage uses hole taping (e.g., 3M type 92 / Kapton) plus sealed bags.

## Independent reconstruction

(a) Hydrogen evolution rate. Subsection 5.3.7.5 states the open‑circuit rate at 21 °C (70 °F) is 0.01 cc H2 per hour per gram of zinc, and that the rate is approximately doubled (or halved) for each 10 °C (18 °F) the temperature is raised (or lowered). Total zinc in the battery = 20 cells × 5 g = 100 g. At 21 °C: 100 g × 0.01 cc/h/g = 1.0 cc H2/h (equivalently 0.05 cc/h per cell × 20 cells). At 31 °C (a +10 °C step): 1.0 × 2 = 2.0 cc H2/h. During discharge the handbook notes the hydrogen evolution is less (reduced), because elemental zinc at the electrode–electrolyte interface is consumed/oxidized, so the on‑stand rate is the worst case.

(b) Storage conditions for ≥85% capacity and the excluded point. Subsection 5.3.6 / Figure 5‑8 (model 796, 1.2 A‑h cells) concludes that, using the remaining data, capacities exceeding 85% of initial values are maintained for up to 18 months (which covers the 12‑month requirement) when ALL of the following are met: (a) a 4 °C (commercial refrigerator) storage environment; (b) all air holes on the cells/batteries taped over with tape impermeable to oxygen and water vapor (3M type 92 adhesive‑backed 0.07‑mm tape, or equivalent DuPont Kapton); and (c) the taped cells/batteries stored in sealed bags (0.15‑mm‑thick polyethylene heat‑sealed bags). The anomalous data point that must be excluded is the 18‑month, air‑holes‑UNTAPED, 4 °C sample whose sealed bag was found to be SLIT on removal; the slit let the cells dry out, so discharge voltages were below 0.9 V initially and did not recover (the 'Zero A‑h; slit in bag' point in Figure 5‑8). This was an unintended variable, not a true storage‑condition result.

(c) Required storage orientation and the failure mechanism it prevents. Subsection 5.3.7.6: cells must NOT be stored with their air holes facing down; where a battery has some stacks holes‑down and some holes‑up, the battery must be stored so that ALL cells are on their EDGE. In the holes‑down position, free electrolyte runs down from the saturated porous zinc anode onto the air‑diffusion membrane and can pool across the cell, blocking the air‑access holes. Hydrogen keeps evolving (Zn + 2KOH → K2ZnO2 + H2), pressure builds inside the cell, and liquid electrolyte is then forced through the membrane and leaks out of the positive‑terminal perforations. Storing on edge keeps at least some perforations open so hydrogen can escape, preventing the internal pressure rise and the resulting electrolyte leakage.

(d) Why the container cannot be sealed or N2‑purged, and the applicable hydrogen control. Subsection 5.3.7.5: the battery case cannot be sealed because OXYGEN is necessary for the cell's operation (the cathode reaction consumes O2 from the air); for the same reason it cannot be purged with nitrogen, which would remove the required oxygen. The most applicable hydrogen control for zinc‑air cells is therefore ADEQUATE (continuous) VENTILATION, to dilute the evolved hydrogen below its flammability level (rather than the sealing/purging controls used for other chemistries).

(e) Flight‑packaged spare multicell batteries vs. long‑term storage. Long‑term storage practice (per (b)) tapes the air holes with O2/water‑vapor‑impermeable tape and stores the taped cells in sealed 0.15‑mm polyethylene bags at 4 °C. By contrast, spare multicell batteries packaged for IMMEDIATE flight storage do NOT have their air holes sealed/taped; instead they are sealed in an inner bag of Film‑Pak 1177 (manufactured by Ludlow, Holyoke, MA, per specification MIL‑B‑22191C).

## Independent audit

- Gold supported: `True`
- Input complete: `True`
- Requires human review: `False`
- Verified claims: `c1, c2, c3, c4, c5, c6`
- Disputed claims: `none`
- Failure reasons: `none`

## Atomic rubric

| ID | Type | Severity | Criterion |
|---|---|---|---|
| r1 | primary_intent | major | Computes the open-circuit hydrogen evolution rate as 1.0 cc/hr at 21 C and 2.0 cc/hr at 31 C for the 100-g zinc battery. |
| r2 | dodged_bullet | major | Cites the 0.01 cc/hr per gram of zinc rate at 21 C and the doubling/halving per 10 degrees C rule, and notes the rate is lower during discharge. |
| r3 | dodged_bullet | major | Lists all three storage conditions for >=85 percent capacity retention to 18 months: 4 C environment, air holes taped with oxygen/water-vapor-impermeable tape, and sealed bags. |
| r4 | dodged_bullet | major | Identifies the slit-bag 18-month untaped/4 C data point (zero A-h, voltage below 0.9 V, no recovery) as an unintended variable that must be excluded from the 85 percent conclusion. |
| r5 | dodged_bullet | major | States cells must be stored on edge (not holes-down) and explains the mechanism: electrolyte pools on the air diffusion membrane, blocks air holes, hydrogen pressure builds, and electrolyte is forced out the positive-terminal perforations. |
| r6 | dodged_bullet | major | States the case cannot be sealed (oxygen needed) and cannot be nitrogen-purged, and names adequate ventilation as the applicable hydrogen control. |
| r7 | dodged_bullet | minor | Distinguishes flight-packaged spares (unsealed air holes inside a Film-Pak 1177 inner bag per MIL-B-22191C) from the long-term taping practice (e.g., 3M type 92 / Kapton plus sealed bags). |

## Bbox repair review

These are deterministic suggestions only. They do not mutate the evidence graph.

- Machine-readable suggestions: [bbox_repair_suggestions.json](/mnt/weka/home/yuan.huang/GDP_pdf_benchmark/reports/golden_v0_single_pdf_battery/review_pack/artifacts/pdfsft_1ef2a218c4a76a94f3cc/bbox_repair_suggestions.json)
- Record the human decision in `bbox_repair_decisions.json` beside that file.

### Evidence `e2` · PDF page 49

- Alignment: `misaligned`
- Confidence: `high`
- Original bbox: `(0.0800, 0.4000, 0.9200, 0.5500)`
- Suggested bbox: `(0.0902, 0.6783, 0.8776, 0.8612)`
- Coverage: `0.0556` → `1.0000`
- Matched blocks: `p49_b6`
- Reason: Suggested bbox is the union of the highest-scoring contiguous LiteParse block window. Human acceptance is required before mutation.
- Excerpt: The battery case cannot be sealed, as oxygen is necessary for its operation. For that reason, it also cannot be purged with nitrogen... The most applicable control is adequate ventilation.
- Dependent claims:
  - c4: The zinc-air battery case cannot be sealed (oxygen is required) and cannot be nitrogen-purged; adequate ventilation is the applicable hydrogen control.

Original crop:

![Original crop for e2](/mnt/weka/home/yuan.huang/GDP_pdf_benchmark/reports/golden_v0_single_pdf_battery/review_pack/artifacts/pdfsft_1ef2a218c4a76a94f3cc/original_crops/001_e2_page_0049_92f043ec2c03.png)

Suggested crop:

![Suggested crop for e2](/mnt/weka/home/yuan.huang/GDP_pdf_benchmark/reports/golden_v0_single_pdf_battery/review_pack/artifacts/pdfsft_1ef2a218c4a76a94f3cc/suggested_crops/001_e2_page_0049_a58ff34403ed.png)

- [ ] Accept suggested bbox
- [ ] Reject or replace with a manual bbox

### Evidence `e6` · PDF page 44

- Alignment: `misaligned`
- Confidence: `high`
- Original bbox: `(0.0800, 0.1200, 0.9200, 0.3000)`
- Suggested bbox: `(0.1656, 0.4372, 0.9059, 0.5038)`
- Coverage: `0.1333` → `1.0000`
- Matched blocks: `p44_b7`
- Reason: Suggested bbox is the union of the highest-scoring contiguous LiteParse block window. Human acceptance is required before mutation.
- Excerpt: new cells are received with an adhesive-backed film seal covering the holes to minimize capacity loss from admission of air and loss of water
- Dependent claims:
  - c6: New cells ship with adhesive film seals over the holes; long-term storage uses taping plus sealed bags, while flight-packaged spares use unsealed air holes inside a Film-Pak 1177 inner bag per MIL-B-22191C.

Original crop:

![Original crop for e6](/mnt/weka/home/yuan.huang/GDP_pdf_benchmark/reports/golden_v0_single_pdf_battery/review_pack/artifacts/pdfsft_1ef2a218c4a76a94f3cc/original_crops/002_e6_page_0044_62005ce64c8d.png)

Suggested crop:

![Suggested crop for e6](/mnt/weka/home/yuan.huang/GDP_pdf_benchmark/reports/golden_v0_single_pdf_battery/review_pack/artifacts/pdfsft_1ef2a218c4a76a94f3cc/suggested_crops/002_e6_page_0044_c897575e26f0.png)

- [ ] Accept suggested bbox
- [ ] Reject or replace with a manual bbox


## Evidence pages

### PDF page 44

![PDF page 44](/mnt/weka/home/yuan.huang/GDP_pdf_benchmark/parsed/8ee157a5465ef564105839ef5cedf8c511917057d76adb85e7642d21fa8e8c57/page_0044.png)

- `e6` · role `footnote` · key `True` · bbox `(0.080, 0.120, 0.920, 0.300)`
  - new cells are received with an adhesive-backed film seal covering the holes to minimize capacity loss from admission of air and loss of water

### PDF page 47

![PDF page 47](/mnt/weka/home/yuan.huang/GDP_pdf_benchmark/parsed/8ee157a5465ef564105839ef5cedf8c511917057d76adb85e7642d21fa8e8c57/page_0047.png)

- `e3` · role `threshold` · key `True` · bbox `(0.080, 0.300, 0.920, 0.620)`
  - The sealed bag... was found to be slit... Discharge voltages were below 0.9 V initially and did not recover... capacities exceeding 85 percent of the initial values are maintained for up to 18 months under: a. A 4C storage environment b. All air holes... taped over with tape that is impermeable to oxygen and water vapor c. Taped cells or batteries stored in sealed bags
- `e4` · role `footnote` · key `True` · bbox `(0.080, 0.620, 0.920, 0.880)`
  - A sealing tape that has been used is 3M type 92... Spare multicell batteries packaged for immediate flight storage do not have sealed air holes, but rather are sealed in an inner bag of Film-Pak 1177... per specification MIL-B-22191C.

### PDF page 49

![PDF page 49](/mnt/weka/home/yuan.huang/GDP_pdf_benchmark/parsed/8ee157a5465ef564105839ef5cedf8c511917057d76adb85e7642d21fa8e8c57/page_0049.png)

- `e1` · role `definition` · key `True` · bbox `(0.080, 0.550, 0.920, 0.850)`
  - The rate of hydrogen evolution by zinc-air cells standing open circuit at 21C (70F) is 0.01 cc of hydrogen per hour per gram of zinc... approximately doubled or halved for each 10C... When the cell is being discharged, the hydrogen evolution is less.
- `e2` · role `exception` · key `True` · bbox `(0.080, 0.400, 0.920, 0.550)`
  - The battery case cannot be sealed, as oxygen is necessary for its operation. For that reason, it also cannot be purged with nitrogen... The most applicable control is adequate ventilation.

### PDF page 50

![PDF page 50](/mnt/weka/home/yuan.huang/GDP_pdf_benchmark/parsed/8ee157a5465ef564105839ef5cedf8c511917057d76adb85e7642d21fa8e8c57/page_0050.png)

- `e5` · role `definition` · key `True` · bbox `(0.080, 0.300, 0.920, 0.780)`
  - free electrolyte runs down onto the air diffusion membrane... blocking the air access holes. Hydrogen continues to be generated... Zn + 2KOH -> K2ZnO2 + H2... cells should not be stored with their holes facing down... the batteries should be stored so that all cells are on their edge

## Claims and derivations

- `c1`: Zinc-air cells on open-circuit stand at 21 degrees C evolve 0.01 cc H2 per hour per gram of zinc; the rate doubles per +10 degrees C and halves per -10 degrees C, and is less during discharge.
  - Supported by: `e1`
- `c2`: For 100 g of zinc (20 cells x 5 g), the open-circuit hydrogen rate is 1.0 cc/hr at 21 degrees C and 2.0 cc/hr at 31 degrees C.
  - Supported by: `c1`
- `c3`: At least 85 percent of initial capacity is retained up to 18 months with 4 degrees C storage, air holes taped with oxygen/water-vapor-impermeable tape, and sealed bags; the slit-bag 18-month untaped data point is an unintended variable and is excluded.
  - Supported by: `e3`
- `c4`: The zinc-air battery case cannot be sealed (oxygen is required) and cannot be nitrogen-purged; adequate ventilation is the applicable hydrogen control.
  - Supported by: `e2, e1`
- `c5`: Cells must not be stored holes-down; storing on edge keeps perforations open so hydrogen escapes, preventing pressure buildup and electrolyte leakage.
  - Supported by: `e5`
- `c6`: New cells ship with adhesive film seals over the holes; long-term storage uses taping plus sealed bags, while flight-packaged spares use unsealed air holes inside a Film-Pak 1177 inner bag per MIL-B-22191C.
  - Supported by: `e6, e4, c3`

### Derivations

- `c2` = `20 cells x 5 g/cell = 100 g Zn; 100 g x 0.01 cc/hr/g = 1.0 cc/hr at 21 C; x2 for +10 C -> 2.0 cc/hr at 31 C`
  - Inputs: `c1`
