# Due Diligence Extractor (ddx)

The **Due Diligence Extractor** (`ddx`) is a production-ready pipeline for extracting structured technical and financial information from project documents. It is designed for renewable energy due diligence, but the architecture is generalizable to other domains.

The pipeline is built around a **map → reduce orchestration pattern**:
- **map**: Run LLM prompts independently over each document (with OCR fallback if needed).
- **reduce**: Apply deterministic reducers and normalization rules to consolidate evidence across multiple documents.
- **orchestrator**: Manages end-to-end execution, caching results, and persisting outputs.

Production‑ready layout with clean separation of concerns:
- **ingestion/**: PDF/KMZ reading and OCR fallback
- **prompts/**: map (single doc) and reduce (synthesizer) prompt builders
- **reducer/**: deterministic policy reducer and normalization helpers
- **llm/**: provider‑agnostic LLM client (OpenAI implemented)
- **storage/**: JSON snapshot writers
- **config/**: field config loader + registry synthesis
- **orchestrator.py**: end‑to‑end map→reduce pipeline
- **scripts/ai_doc_reader.py**: thin CLI wrapper

---

## How the Pipeline Works

1. **Configuration (`fields.json`)**  
   Each field in `config/fields.json` describes what information to extract.  
   Example:
   ```json
   "existing_electrical_system.energy_bills_12_months.average_monthly_consumption": {
     "doc_category": "Energy Bills",
     "unit": "kWh",
     "extraction_contract": { ... }
   }```
2. **Document Input (examples/)**
  Documents are organized by category (e.g. energy_bills/, electrical_design/). The CLI takes a directory path and processes all documents inside.

3. **Mapping Step**
  Each document is parsed (with OCR if necessary) and passed through an LLM prompt defined for the field.

4. **Reduction Step**
  The orchestrator consolidates intermediate answers across documents into a final output using deterministic rules (true_if_any, mean, etc.).

5. **Outputs (store/)**
  store/runs/<project_id>/<timestamp>.json → snapshot of the run.
  store/fields/<project_id>/<field>.latest.json → latest output per field.
  store/fields/<project_id>/<field>.history.jsonl → history of extractions.

--- 

## Quick Start

Run the following install

```bash
pip install -e .
```
followed by a command, e.g.

```bash
# env
export OPENAI_API_KEY=sk-...
export TAVILY_API_KEY=tvly-....
export LLM_MODEL=gpt-4o-mini

python scripts/ai_doc_reader.py \
  --field-config ./config/fields.json \
  --docs-dir ./examples/energy_bills \
  --fields existing_electrical_system.energy_bills_12_months.average_monthly_consumption \
           existing_electrical_system.energy_bills_12_months.average_existing_energy_rate \
  --provider openai --model "${LLM_MODEL}" \
  --ocr --ocr-lang "spa+eng" --ocr-dpi 300 \
  --store-dir ./store --project-id default_project \
  --progress
```

**Field-to-Example Mapping**

The tables below explain which fields map to which document categories in examples/.
Each row shows the field key, what it extracts, and the command to run.

### A) Energy Bills

**Directory:** `examples/energy_bills/`

| Field key | Extracts | Example command |
|-----------|----------|-----------------|
| `existing_electrical_system.energy_bills_12_months.average_monthly_consumption` | Avg monthly consumption | ```bash python scripts/ai_doc_reader.py --docs-dir ./examples/energy_bills --field-config ./config/fields.json --fields existing_electrical_system.energy_bills_12_months.average_monthly_consumption --store-dir ./store --project-id default_project --progress``` |
| `existing_electrical_system.energy_bills_12_months.average_existing_energy_rate` | Avg energy rate (USD/kWh) | ```bash python scripts/ai_doc_reader.py --docs-dir ./examples/energy_bills --field-config ./config/fields.json --fields existing_electrical_system.energy_bills_12_months.average_existing_energy_rate --store-dir ./store --project-id default_project --progress ``` |

### B) Electrical Design

**Directory:** `examples/electrical_design/`

| Field key | Extracts | Example command |
|-----------|----------|-----------------|
| `electrical_design.unifilar_diagram.presence_of_inverter_meter_transformer_protection` | Dict of 4 booleans | ```bash
python scripts/ai_doc_reader.py --docs-dir ./examples/electrical_design --field-config ./config/fields.json --fields electrical_design.unifilar_diagram.presence_of_inverter_meter_transformer_protection --store-dir ./store --project-id default_project --progress``` |
| `electrical_design.unifilar_diagram.voltage_levels_labeled` | DC/AC/MV labels present | ```bash python scripts/ai_doc_reader.py --docs-dir ./examples/electrical_design --field-config ./config/fields.json --fields electrical_design.unifilar_diagram.voltage_levels_labeled --store-dir ./store --project-id default_project --progress ``` |
| `electrical_design.georeferenced_plans.kmz_polygon_present` | Polygon presence in KMZ | ```bash python scripts/ai_doc_reader.py --docs-dir ./examples/electrical_design --field-config ./config/fields.json --fields electrical_design.georeferenced_plans.kmz_polygon_present --store-dir ./store --project-id default_project --progress ``` |
| `electrical_design.cable_sizing.parameters` | Cable sizing parameters | ```bash python scripts/ai_doc_reader.py --docs-dir ./examples/electrical_design --field-config ./config/fields.json --fields electrical_design.cable_sizing.parameters --store-dir ./store --project-id default_project --progress ``` |
| `electrical_design.voltage_drop.percentage` | Voltage drop checks | ```bash python scripts/ai_doc_reader.py --docs-dir ./examples/electrical_design --field-config ./config/fields.json --fields electrical_design.voltage_drop.percentage --store-dir ./store --project-id default_project --progress ``` |
| `electrical_design.grounding_layout.resistance` | Grounding resistance | ```bash python scripts/ai_doc_reader.py --docs-dir ./examples/electrical_design --field-config ./config/fields.json --fields electrical_design.grounding_layout.resistance --store-dir ./store --project-id default_project --progress ``` |

### C) Mechanical Design

**Directory:** `examples/mechanical_design/`

| Field key | Extracts | Example command |
|-----------|----------|-----------------|
| `mechanical_design.infrastructure_report.present` | Infrastructure report presence | ```bash python scripts/ai_doc_reader.py --docs-dir ./examples/mechanical_design --field-config ./config/fields.json --fields mechanical_design.infrastructure_report.present --store-dir ./store --project-id default_project --progress ``` |
| `mechanical_design.panel_layout.diagram_present` | Panel layout diagram | ```bash python scripts/ai_doc_reader.py --docs-dir ./examples/mechanical_design --field-config ./config/fields.json --fields mechanical_design.panel_layout.diagram_present --store-dir ./store --project-id default_project --progress ``` |
| `mechanical_design.roof_reinforcement.studies_present` | Roof reinforcement studies | ```bash python scripts/ai_doc_reader.py --docs-dir ./examples/mechanical_design --field-config ./config/fields.json --fields mechanical_design.roof_reinforcement.studies_present --store-dir ./store --project-id default_project --progress ``` |
| `mechanical_design.civil_site_studies.reports_present` | Civil site studies | ```bash python scripts/ai_doc_reader.py --docs-dir ./examples/mechanical_design --field-config ./config/fields.json --fields mechanical_design.civil_site_studies.reports_present --store-dir ./store --project-id default_project --progress ``` |

### D) Mounting Structures

**Directory:** `examples/mounting_structures/`

| Field key | Extracts | Directory | Example command |
|-----------|----------|-----------|-----------------|
| `mounting_structures.mounting_layout.type_defined` | Layout type (roof/ground/floating) | `mounting_layout/` | ```bash python scripts/ai_doc_reader.py --docs-dir ./examples/mounting_structures/mounting_layout --field-config ./config/fields.json --fields mounting_structures.mounting_layout.type_defined --store-dir ./store --project-id default_project --progress ``` |
| `mounting_structures.site_corrosion_category.classification_present` | Corrosion category ISO 9223–6 | `site_corrosion_report/` | ```bash python scripts/ai_doc_reader.py --docs-dir ./examples/mounting_structures/site_corrosion_report --field-config ./config/fields.json --fields mounting_structures.site_corrosion_category.classification_present --store-dir ./store --project-id default_project --progress ``` |
| `mounting_structures.structural_calculation.report_stamped_present` | Structural calcs stamped | `structural_calculation_report/` | ```bash python scripts/ai_doc_reader.py --docs-dir ./examples/mounting_structures/structural_calculation_report --field-config ./config/fields.json --fields mounting_structures.structural_calculation.report_stamped_present --store-dir ./store --project-id default_project --progress ``` |
| `mounting_structures.coating_certification.certification_present` | Coating certification | root | ```bash python scripts/ai_doc_reader.py --docs-dir ./examples/mounting_structures --field-config ./config/fields.json --fields mounting_structures.coating_certification.certification_present --store-dir ./store --project-id default_project --progress ``` |
| `mounting_structures.warranty_certificate.warranty_present` | Warranty presence | root | ```bash python scripts/ai_doc_reader.py --docs-dir ./examples/mounting_structures --field-config ./config/fields.json --fields mounting_structures.warranty_certificate.warranty_present --store-dir ./store --project-id default_project --progress ``` |

### E) Inverters

**Directory:** `examples/inverters/`

| Field key | Extracts | Example command |
|-----------|----------|-----------------|
| `inverters.warranty_certificate.warranty_years` | Inverter warranty period | ```bash python scripts/ai_doc_reader.py --docs-dir ./examples/inverters --field-config ./config/fields.json --fields inverters.warranty_certificate.warranty_years --store-dir ./store --project-id default_project --progress ``` |

### F) Photovoltaic Modules

**Directory:** `examples/pv/`

| Field key | Extracts | Example command |
|-----------|----------|-----------------|
| `photovoltaic_modules.warranty_certificate.product` | Product warranty (years) | ```bash python scripts/ai_doc_reader.py --docs-dir ./examples/pv --field-config ./config/fields.json --fields photovoltaic_modules.warranty_certificate.product --store-dir ./store --project-id default_project --progress ``` |
| `photovoltaic_modules.warranty_certificate.performance` | Performance/power warranty | ```bash python scripts/ai_doc_reader.py --docs-dir ./examples/pv --field-config ./config/fields.json --fields photovoltaic_modules.warranty_certificate.performance --store-dir ./store --project-id default_project --progress ``` |


### G) SCADA Systems

**Directory:** `examples/scada_systems/`

| Field key | Extracts | Example command |
|-----------|----------|-----------------|
| `scada.architecture.diagram_present` | SCADA topology diagram | ```bash python scripts/ai_doc_reader.py --docs-dir ./examples/scada_systems --field-config ./config/fields.json --fields scada.architecture.diagram_present --store-dir ./store --project-id default_project --progress ``` |
| `scada.communication.protocol_and_taglist_present` | Protocol + taglist | ```bash python scripts/ai_doc_reader.py --docs-dir ./examples/scada_systems --field-config ./config/fields.json --fields scada.communication.protocol_and_taglist_present --store-dir ./store --project-id default_project --progress ``` |
| `scada.meteorological_station.included_calibrated_sensors` | Calibrated met station sensors | ```bash python scripts/ai_doc_reader.py --docs-dir ./examples/scada_systems --field-config ./config/fields.json --fields scada.meteorological_station.included_calibrated_sensors --store-dir ./store --project-id default_project --progress ``` |

