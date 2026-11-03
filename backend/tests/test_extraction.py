"""Tests for the entity extraction pipeline and reference-range flagging.

These verify the acceptance criteria:
  - Diagnoses extracted from a prescription
  - Medications (drug/dose/freq) extracted from an Indian prescription format
  - Lab values extracted and abnormals flagged from a lab report
  - Date extraction for chronological ordering
"""

from datetime import date

from app.services.entity_extraction import extract_entities
from app.services.reference_ranges import flag_abnormal

# ---------------------------------------------------------------------------
# Sample documents (realistic Indian formats)
# ---------------------------------------------------------------------------

SAMPLE_PRESCRIPTION = """
Dr. Rajesh Gupta, MBBS, MD
Reg No: MCI-12345
Clinic: 42, MG Road, Delhi

Date: 15/08/2025

Patient: Ramesh Kumar, M/45

Diagnosis: Type 2 Diabetes Mellitus, Hypertension

Rx:
1. Tab Metformin 500mg 1-0-1
2. Tab Amlodipine 5mg 0-0-1
3. Tab Aspirin 75mg 0-1-0

Advice: Low salt diet, walk 30 min daily
Follow-up after 1 month
"""

SAMPLE_LAB_REPORT = """
ABC Pathology Laboratory
NABL Accredited

Date: 22/07/2025
Patient: Priya Sharma, F/32

COMPLETE BLOOD COUNT (CBC)

Test                  Result      Unit        Reference Range
Hemoglobin            9.5         g/dL        12.0 - 15.5
RBC                   3.8         million/uL  4.0 - 5.0
WBC                   12500       cells/uL    4000 - 11000
Platelet Count        250000      cells/uL    150000 - 400000

LIPID PROFILE

Total Cholesterol     245         mg/dL       < 200
LDL                   160         mg/dL       < 100
HDL                   42          mg/dL       > 50
Triglycerides         180         mg/dL       < 150

BLOOD SUGAR

Fasting Glucose       135         mg/dL       70 - 100
HbA1c                 7.2         %           4.0 - 5.6
"""

SAMPLE_DISCHARGE = """
City Hospital, Mumbai
DISCHARGE SUMMARY

Date of Admission: 01/03/2025
Date of Discharge: 05/03/2025

Patient: Anil Verma, M/60

Diagnosis: Acute Myocardial Infarction (Anterior Wall)

Procedure: Percutaneous Coronary Intervention (PCI) with stent

Medications at Discharge:
Tab Clopidogrel 75mg 1-0-0
Tab Atorvastatin 40mg 0-0-1
Tab Metoprolol 25mg 1-0-1
Inj Enoxaparin 60mg SC BD x 5 days
"""


# ---------------------------------------------------------------------------
# Prescription tests
# ---------------------------------------------------------------------------


class TestPrescriptionExtraction:
    def test_extracts_diagnosis(self):
        result = extract_entities(SAMPLE_PRESCRIPTION, gender="male")
        diagnoses = [e for e in result.entities if e.entity_type == "diagnosis"]
        diag_texts = [e.value["diagnosis"].lower() for e in diagnoses]
        assert any("diabetes" in d for d in diag_texts)
        assert any("hypertension" in d for d in diag_texts)

    def test_extracts_medications(self):
        result = extract_entities(SAMPLE_PRESCRIPTION, gender="male")
        meds = [e for e in result.entities if e.entity_type == "medication"]
        drug_names = [e.value["drug"].lower() for e in meds]
        assert "metformin" in drug_names
        assert "amlodipine" in drug_names
        assert "aspirin" in drug_names

    def test_medication_has_dose(self):
        result = extract_entities(SAMPLE_PRESCRIPTION, gender="male")
        meds = [e for e in result.entities if e.entity_type == "medication"]
        metformin = next(m for m in meds if "metformin" in m.value["drug"].lower())
        assert "500" in metformin.value["dose"]

    def test_extracts_date(self):
        result = extract_entities(SAMPLE_PRESCRIPTION, gender="male")
        assert result.document_date == date(2025, 8, 15)

    def test_infers_prescription_type(self):
        result = extract_entities(SAMPLE_PRESCRIPTION, gender="male")
        assert result.doc_type == "prescription"


# ---------------------------------------------------------------------------
# Lab report tests
# ---------------------------------------------------------------------------


class TestLabReportExtraction:
    def test_extracts_investigation_values(self):
        result = extract_entities(SAMPLE_LAB_REPORT, gender="female")
        invs = [e for e in result.entities if e.entity_type == "investigation_value"]
        assert len(invs) >= 4  # at least hemoglobin, RBC, WBC, platelets

    def test_flags_low_hemoglobin_in_female(self):
        result = extract_entities(SAMPLE_LAB_REPORT, gender="female")
        invs = [e for e in result.entities if e.entity_type == "investigation_value"]
        hb = next((e for e in invs if "hemoglobin" in e.value["test"].lower()), None)
        assert hb is not None
        assert hb.is_abnormal is True  # 9.5 < 12.0

    def test_flags_high_fasting_glucose(self):
        result = extract_entities(SAMPLE_LAB_REPORT, gender="female")
        invs = [e for e in result.entities if e.entity_type == "investigation_value"]
        glucose = next(
            (
                e
                for e in invs
                if "fasting" in e.value["test"].lower() or "glucose" in e.value["test"].lower()
            ),
            None,
        )
        # 135 > 100
        assert glucose is not None
        assert glucose.is_abnormal is True

    def test_extracts_date(self):
        result = extract_entities(SAMPLE_LAB_REPORT, gender="female")
        assert result.document_date == date(2025, 7, 22)

    def test_infers_lab_report_type(self):
        result = extract_entities(SAMPLE_LAB_REPORT, gender="female")
        assert result.doc_type == "lab_report"


# ---------------------------------------------------------------------------
# Discharge summary tests
# ---------------------------------------------------------------------------


class TestDischargeExtraction:
    def test_extracts_diagnosis_from_discharge(self):
        result = extract_entities(SAMPLE_DISCHARGE, gender="male")
        diagnoses = [e for e in result.entities if e.entity_type == "diagnosis"]
        assert len(diagnoses) >= 1
        assert any("myocardial" in d.value["diagnosis"].lower() for d in diagnoses)

    def test_extracts_procedure(self):
        result = extract_entities(SAMPLE_DISCHARGE, gender="male")
        procs = [e for e in result.entities if e.entity_type == "procedure"]
        assert len(procs) >= 1
        assert any(
            "pci" in p.value["procedure"].lower() or "coronary" in p.value["procedure"].lower()
            for p in procs
        )

    def test_extracts_discharge_medications(self):
        result = extract_entities(SAMPLE_DISCHARGE, gender="male")
        meds = [e for e in result.entities if e.entity_type == "medication"]
        drug_names = [m.value["drug"].lower() for m in meds]
        assert "clopidogrel" in drug_names or "atorvastatin" in drug_names

    def test_infers_discharge_summary_type(self):
        result = extract_entities(SAMPLE_DISCHARGE, gender="male")
        assert result.doc_type == "discharge_summary"


# ---------------------------------------------------------------------------
# Reference range / abnormal flag tests
# ---------------------------------------------------------------------------


class TestReferenceRanges:
    def test_normal_hemoglobin_male(self):
        assert flag_abnormal("hemoglobin", 14.5, "male") is False

    def test_low_hemoglobin_female(self):
        assert flag_abnormal("hemoglobin", 9.5, "female") is True

    def test_high_fasting_glucose(self):
        assert flag_abnormal("fasting_glucose", 135, None) is True

    def test_normal_fasting_glucose(self):
        assert flag_abnormal("fasting_glucose", 85, None) is False

    def test_high_ldl(self):
        assert flag_abnormal("ldl", 160, None) is True

    def test_unknown_test_returns_none(self):
        assert flag_abnormal("some_obscure_test", 42, None) is None

    def test_high_wbc(self):
        assert flag_abnormal("wbc", 12500, None) is True

    def test_normal_wbc(self):
        assert flag_abnormal("wbc", 7000, None) is False
