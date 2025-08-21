# Fields Framework Documentation
 
Each field represents a specific piece of due diligence information to be extracted from project documents. See https://docs.google.com/spreadsheets/d/1F0Qlpd5aZ4hmClElRaYD1L_NPmwZwI-jT5rIHvCW-mA/edit?pli=1&gid=1562771826#gid=1562771826 for the original document.

---

## How to Read a Field Definition

Each field in `fields.json` contains:

- **Field Key**: Hierarchical identifier (e.g. `electrical_design.unifilar_diagram.presence_of_inverter_meter_transformer_protection`)  
- **Category / Subcategory**: Logical grouping (e.g. Electrical Design → Unifilar Diagram)  
- **Unit**: Expected unit or type (`kWh`, `MWh/month`, `boolean`, etc.)  
- **Extraction Contract**: Defines the required values to be extracted per document  
- **Reducer Policy**: Defines how to consolidate multiple document-level values into a single output  
- **Min Documents**: Minimum number of documents required for a valid extraction  

---

# Existing Electrical System

### 1. Average Monthly Consumption
- **Key:** `existing_electrical_system.energy_bills_12_months.average_monthly_consumption`  
- **Category:** Existing Electrical System → Energy Bills  
- **Unit:** MWh/month  
- **What it extracts:** The average monthly energy consumption across the last 12 months of bills.  
- **Reducer Policy:**  
  - Strategy: `average`  
  - Instruction: Compute the average of all `monthly_kwh` values and normalize to MWh/month.  
- **Min Documents:** 10 (requires a full year of bills)

---

### 2. Average Existing Energy Rate
- **Key:** `existing_electrical_system.energy_bills_12_months.average_existing_energy_rate`  
- **Category:** Existing Electrical System → Energy Bills  
- **Unit:** USD/kWh  
- **What it extracts:** The average electricity rate charged in the bills.  
- **Reducer Policy:**  
  - Strategy: `average`  
  - Instruction: Average the `rate_usd_per_kwh` field across bills.  
- **Min Documents:** 10

---

# Photovoltaic Modules

### 3. Product Warranty
- **Key:** `photovoltaic_modules.warranty_certificate.product`  
- **Category:** PV Modules → Warranty Certificate  
- **Unit:** years  
- **What it extracts:** Number of years of product warranty offered by the module supplier.  
- **Reducer Policy:**  
  - Strategy: `single_value`  
  - Instruction: Select the explicit warranty period.  
- **Min Documents:** 1

---

### 4. Performance Warranty
- **Key:** `photovoltaic_modules.warranty_certificate.performance`  
- **Category:** PV Modules → Warranty Certificate  
- **Unit:** years  
- **What it extracts:** Performance/power warranty duration (typically 25–30 years).  
- **Reducer Policy:**  
  - Strategy: `single_value`  
  - Instruction: Extract the warranty years explicitly.  
- **Min Documents:** 1

---

# Inverters

### 5. Inverter Warranty
- **Key:** `inverters.warranty_certificate.warranty_years`  
- **Category:** Inverters → Warranty Certificate  
- **Unit:** years  
- **What it extracts:** Inverter warranty period in years.  
- **Reducer Policy:**  
  - Strategy: `single_value`  
- **Min Documents:** 1

---

# Mounting Structures

### 6. Coating Certification
- **Key:** `mounting_structures.coating_certification.certification_present`  
- **Category:** Mounting Structures  
- **Unit:** boolean  
- **What it extracts:** Whether coating certification (anti-corrosion) is present.  
- **Reducer Policy:**  
  - Strategy: `true_if_any`  
- **Min Documents:** 1

---

### 7. Warranty
- **Key:** `mounting_structures.warranty_certificate.warranty_present`  
- **Category:** Mounting Structures  
- **Unit:** boolean  
- **What it extracts:** Whether a mounting structure warranty is present.  
- **Reducer Policy:**  
  - Strategy: `true_if_any`  
- **Min Documents:** 1

---

### 8. Site Corrosion Category
- **Key:** `mounting_structures.site_corrosion_category.classification_present`  
- **Category:** Mounting Structures → Site Corrosion Report  
- **Unit:** classification (ISO 9223–9226)  
- **What it extracts:** The corrosivity classification of the project site.  
- **Reducer Policy:**  
  - Strategy: `synthesis`  
  - Instruction: Report ISO 9223/9224/9225/9226 class if present.  
- **Min Documents:** 1

---

### 9. Structural Calculation Report
- **Key:** `mounting_structures.structural_calculation.report_stamped_present`  
- **Category:** Mounting Structures → Structural Calcs  
- **Unit:** boolean  
- **What it extracts:** Whether a stamped & signed structural calculation report is included.  
- **Reducer Policy:**  
  - Strategy: `true_if_any`  
- **Min Documents:** 1

---

### 10. Mounting Layout Type
- **Key:** `mounting_structures.mounting_layout.type_defined`  
- **Category:** Mounting Structures → Mounting Layout  
- **Unit:** string (roof, ground, floating)  
- **What it extracts:** Mounting type as defined in layout docs.  
- **Reducer Policy:**  
  - Strategy: `single_value`  
- **Min Documents:** 1

---

# Electrical Design

### 11. Presence of Inverter/Meter/Transformer/Protection
- **Key:** `electrical_design.unifilar_diagram.presence_of_inverter_meter_transformer_protection`  
- **Category:** Electrical Design → Unifilar Diagram  
- **Unit:** dict of booleans  
- **What it extracts:** Whether inverter, meter, transformer, and protection devices are present in diagrams.  
- **Reducer Policy:**  
  - Strategy: `dict_aggregate`  
  - Rules: `true_if_any` per key  
- **Min Documents:** 1

---

### 12. Voltage Levels Labeled
- **Key:** `electrical_design.unifilar_diagram.voltage_levels_labeled`  
- **Category:** Electrical Design → Unifilar Diagram  
- **Unit:** boolean  
- **What it extracts:** Whether diagrams label DC, AC, MV voltage levels.  
- **Reducer Policy:**  
  - Strategy: `true_if_any`  
- **Min Documents:** 1

---

### 13. KMZ Polygon Present
- **Key:** `electrical_design.georeferenced_plans.kmz_polygon_present`  
- **Category:** Electrical Design → Georeferenced Plans  
- **Unit:** boolean  
- **What it extracts:** Whether the KMZ contains a polygon boundary.  
- **Reducer Policy:**  
  - Strategy: `true_if_any`  
- **Min Documents:** 1

---

### 14. Cable Sizing Parameters
- **Key:** `electrical_design.cable_sizing.parameters`  
- **Category:** Electrical Design → Cable Sizing  
- **Unit:** dict (cross-section, current, etc.)  
- **What it extracts:** Cable sizing parameters from the design.  
- **Reducer Policy:**  
  - Strategy: `synthesis`  
- **Min Documents:** 1

---

### 15. Voltage Drop Percentage
- **Key:** `electrical_design.voltage_drop.percentage`  
- **Category:** Electrical Design → Voltage Drop  
- **Unit:** %  
- **What it extracts:** Voltage drop values.  
- **Reducer Policy:**  
  - Strategy: `single_value`  
- **Min Documents:** 1

---

### 16. Grounding Layout Resistance
- **Key:** `electrical_design.grounding_layout.resistance`  
- **Category:** Electrical Design → Grounding Layout  
- **Unit:** ohms  
- **What it extracts:** Grounding resistance.  
- **Reducer Policy:**  
  - Strategy: `single_value`  
- **Min Documents:** 1

---

# Mechanical Design

### 17. Infrastructure Report Present
- **Key:** `mechanical_design.infrastructure_report.present`  
- **Category:** Mechanical Design  
- **Unit:** boolean  
- **What it extracts:** Presence of an infrastructure report.  
- **Reducer Policy:**  
  - Strategy: `true_if_any`  
- **Min Documents:** 1

---

### 18. Panel Layout Diagram Present
- **Key:** `mechanical_design.panel_layout.diagram_present`  
- **Category:** Mechanical Design  
- **Unit:** boolean  
- **What it extracts:** Presence of a panel layout drawing.  
- **Reducer Policy:**  
  - Strategy: `true_if_any`  
- **Min Documents:** 1

---

### 19. Roof Reinforcement Studies Present
- **Key:** `mechanical_design.roof_reinforcement.studies_present`  
- **Category:** Mechanical Design  
- **Unit:** boolean  
- **What it extracts:** Presence of roof reinforcement study reports.  
- **Reducer Policy:**  
  - Strategy: `true_if_any`  
- **Min Documents:** 1

---

### 20. Civil Site Studies Present
- **Key:** `mechanical_design.civil_site_studies.reports_present`  
- **Category:** Mechanical Design  
- **Unit:** boolean  
- **What it extracts:** Presence of civil/hydrological/geotechnical studies.  
- **Reducer Policy:**  
  - Strategy: `true_if_any`  
- **Min Documents:** 1

---

# SCADA Systems

### 21. SCADA Architecture Diagram Present
- **Key:** `scada.architecture.diagram_present`  
- **Category:** SCADA Systems  
- **Unit:** boolean  
- **What it extracts:** Whether an architecture diagram is included.  
- **Reducer Policy:**  
  - Strategy: `true_if_any`  
- **Min Documents:** 1

---

### 22. Communication Protocol and Taglist Present
- **Key:** `scada.communication.protocol_and_taglist_present`  
- **Category:** SCADA Systems  
- **Unit:** boolean  
- **What it extracts:** Whether communication protocols and tag lists are documented.  
- **Reducer Policy:**  
  - Strategy: `true_if_any`  
- **Min Documents:** 1

---

### 23. Meteorological Station Sensors
- **Key:** `scada.meteorological_station.included_calibrated_sensors`  
- **Category:** SCADA Systems  
- **Unit:** list of sensors  
- **What it extracts:** Whether calibrated meteorological sensors are included (wind, irradiance, temp).  
- **Reducer Policy:**  
  - Strategy: `synthesis`  
- **Min Documents:** 1

---