"""Generate version-controlled golden evaluation dataset (BE-16 §5).
Ensures >= 100 questions, >= 30% answerable: false across all 4 negative categories.
"""

import json
from pathlib import Path


def generate_golden_set():
    entries = []

    # -------------------------------------------------------------------------
    # Answerable Questions (Total: 65)
    # Topics: Retention, Security SLA, Cloud MSA Uptime, Arbitration, Liability, Torque Specs
    # -------------------------------------------------------------------------
    
    # Policy / Retention
    retention_questions = [
        ("How long must customer account records be retained after account closure?", ["seven", "7 years"], "data-protection-policy-2026.pdf"),
        ("What is the record retention window for signed transaction logs?", ["7 years", "seven"], "data-protection-policy-2026.pdf"),
        ("What standard governs the cryptographic shredding of expired records?", ["NIST SP 800-88", "800-88"], "data-protection-policy-2026.pdf"),
        ("What happens to customer records after the seven-year retention window expires?", ["shredded", "NIST SP 800-88", "cryptographically"], "data-protection-policy-2026.pdf"),
        ("What standard must be followed when destroying secondary backups?", ["NIST SP 800-88"], "data-protection-policy-2026.pdf"),
        ("What is the incident notification SLA for affected clients following a breach?", ["seventy-two", "72 hours"], "data-protection-policy-2026.pdf"),
        ("How quickly must the SOC notify supervisory authorities of a confirmed security breach?", ["72 hours", "seventy-two"], "data-protection-policy-2026.pdf"),
        ("Who is required to comply with the Data Protection Policy?", ["operating divisions", "external service contractors", "mandatory"], "data-protection-policy-2026.pdf"),
        ("What are the three data classification tiers in the Data Protection Policy?", ["Public Information", "Internal Operational", "Customer PII"], "data-protection-policy-2026.pdf"),
        ("What information is considered Customer PII under the security policy?", ["government identifiers", "banking coordinates", "biometric"], "data-protection-policy-2026.pdf"),
        ("Are biometric templates classified as Customer PII?", ["biometric templates", "Customer PII", "Highly Confidential"], "data-protection-policy-2026.pdf"),
        ("Are banking coordinates treated as Highly Confidential Customer PII?", ["banking coordinates", "Customer PII"], "data-protection-policy-2026.pdf"),
        ("Does the Data Protection Policy apply to external contractors?", ["external service contractors", "mandatory"], "data-protection-policy-2026.pdf"),
        ("What triggers the 72-hour incident notification clock?", ["verified or suspected", "incident confirmation"], "data-protection-policy-2026.pdf"),
        ("What team is responsible for breach notification under the policy?", ["Security Operations Center", "SOC"], "data-protection-policy-2026.pdf"),
    ]
    for q, ans, doc in retention_questions:
        entries.append({
            "id": f"gs-{len(entries)+1:03d}",
            "question": q,
            "answerable": True,
            "expected_document": doc,
            "expected_answer_contains": ans,
            "category": "policy_retention",
            "difficulty": "easy" if len(entries) % 2 == 0 else "medium",
        })

    # Vendor Agreement / MSA
    msa_questions = [
        ("What monthly uptime service level does the cloud vendor guarantee?", ["99.95%"], "cloud_services_vendor_agreement.docx"),
        ("What service credit is Customer entitled to if monthly availability is between 99.0% and 99.95%?", ["15%", "15 percent"], "cloud_services_vendor_agreement.docx"),
        ("What credit is awarded if availability falls below 99.0%?", ["30%", "30 percent"], "cloud_services_vendor_agreement.docx"),
        ("Where must arbitration proceedings take place under the vendor agreement?", ["New York City", "New York"], "cloud_services_vendor_agreement.docx"),
        ("Which organization administers dispute arbitration for the vendor agreement?", ["American Arbitration Association", "AAA"], "cloud_services_vendor_agreement.docx"),
        ("What arbitration rules apply to dispute resolution under the cloud contract?", ["Commercial Arbitration Rules"], "cloud_services_vendor_agreement.docx"),
        ("What is the aggregate liability cap under the Master Services Agreement?", ["twelve (12) months", "total fees paid"], "cloud_services_vendor_agreement.docx"),
        ("Are breaches of confidentiality subject to the standard liability cap?", ["Except for breaches of confidentiality", "gross negligence"], "cloud_services_vendor_agreement.docx"),
        ("What are the exceptions to the twelve-month liability limitation?", ["confidentiality", "gross negligence"], "cloud_services_vendor_agreement.docx"),
        ("Who are the two parties to the Master Cloud Services Agreement?", ["CloudProvider Corp", "ACME Global Enterprise"], "cloud_services_vendor_agreement.docx"),
        ("What services are covered under the vendor agreement?", ["compute infrastructure", "API hosting"], "cloud_services_vendor_agreement.docx"),
        ("How is binding arbitration administered under the MSA?", ["American Arbitration Association", "Commercial Arbitration Rules"], "cloud_services_vendor_agreement.docx"),
        ("How is the liability cap calculated under the cloud services contract?", ["total fees paid", "12 months"], "cloud_services_vendor_agreement.docx"),
        ("Does gross negligence bypass the aggregate liability cap?", ["gross negligence", "Except for"], "cloud_services_vendor_agreement.docx"),
        ("What is the uptime credit percentage for 98.5% availability?", ["30%"], "cloud_services_vendor_agreement.docx"),
    ]
    for q, ans, doc in msa_questions:
        entries.append({
            "id": f"gs-{len(entries)+1:03d}",
            "question": q,
            "answerable": True,
            "expected_document": doc,
            "expected_answer_contains": ans,
            "category": "legal_contracts",
            "difficulty": "medium",
        })

    # Engineering / Hardware Manual
    eng_questions = [
        ("What is the required bolt torque specification for the Model XR-4400 industrial gateway?", ["45 Newton-meters", "45 Nm"], "hardware_maintenance_manual_xr4400.pdf"),
        ("What tool must be used to tighten the XR-4400 primary mounting flange bolts?", ["calibrated digital wrench"], "hardware_maintenance_manual_xr4400.pdf"),
        ("What is the operating ambient temperature range for the XR-4400 gateway?", ["-20 degrees", "+65 degrees"], "hardware_maintenance_manual_xr4400.pdf"),
        ("What is the maximum operating temperature for the Model XR-4400?", ["+65 degrees", "65"], "hardware_maintenance_manual_xr4400.pdf"),
        ("What is the minimum operating temperature for Model XR-4400?", ["-20 degrees", "-20"], "hardware_maintenance_manual_xr4400.pdf"),
        ("Which component on the XR-4400 requires 45 Nm torque tightening?", ["primary mounting flange bolts", "flange"], "hardware_maintenance_manual_xr4400.pdf"),
        ("What model industrial gateway is described in the hardware manual?", ["Model XR-4400", "XR-4400"], "hardware_maintenance_manual_xr4400.pdf"),
        ("Does the XR-4400 manual require periodic calibration?", ["periodic calibration", "requires"], "hardware_maintenance_manual_xr4400.pdf"),
        ("Can the XR-4400 operate at 0 degrees Celsius?", ["between -20", "+65"], "hardware_maintenance_manual_xr4400.pdf"),
        ("Can the XR-4400 gateway operate at 50 degrees Celsius?", ["between -20", "+65"], "hardware_maintenance_manual_xr4400.pdf"),
    ]
    for q, ans, doc in eng_questions:
        entries.append({
            "id": f"gs-{len(entries)+1:03d}",
            "question": q,
            "answerable": True,
            "expected_document": doc,
            "expected_answer_contains": ans,
            "category": "engineering_manual",
            "difficulty": "easy" if len(entries) % 2 == 0 else "medium",
        })

    # Additional diverse answerable paraphrased variations to reach 65 answerable
    extra_answerable = [
        ("What is the retention rule for signed customer transaction logs?", ["7 years", "seven"], "data-protection-policy-2026.pdf"),
        ("How many hours does the SOC have to notify authorities after confirming a breach?", ["72 hours", "seventy-two"], "data-protection-policy-2026.pdf"),
        ("What happens when account closure occurs regarding customer records?", ["retained for exactly seven", "7 years"], "data-protection-policy-2026.pdf"),
        ("What is the credit for 99.2% uptime under the CloudProvider contract?", ["15%"], "cloud_services_vendor_agreement.docx"),
        ("Where will contract disputes with CloudProvider Corp be settled?", ["New York City", "New York"], "cloud_services_vendor_agreement.docx"),
        ("What torque value is mandated for Model XR-4400 flange bolts?", ["45 Nm", "45 Newton-meters"], "hardware_maintenance_manual_xr4400.pdf"),
        ("What is the high temperature ceiling for the XR-4400?", ["+65 degrees", "65"], "hardware_maintenance_manual_xr4400.pdf"),
        ("Are primary billing addresses considered Customer PII?", ["Customer PII", "billing addresses"], "data-protection-policy-2026.pdf"),
        ("Does ACME policy classify operational telemetry as Public Information?", ["three strict security tiers", "Internal Operational Telemetry"], "data-protection-policy-2026.pdf"),
        ("What shredding standard is used for expired records?", ["NIST SP 800-88"], "data-protection-policy-2026.pdf"),
        ("What is the uptime SLA threshold for obtaining a 15% credit?", ["99.95%", "99.0%"], "cloud_services_vendor_agreement.docx"),
        ("Under the vendor agreement, which city hosts the binding arbitration?", ["New York City"], "cloud_services_vendor_agreement.docx"),
        ("What is the liability period used to compute the fee cap under the vendor agreement?", ["twelve (12) months", "12 months"], "cloud_services_vendor_agreement.docx"),
        ("What tool is specified for torque measurement in the maintenance manual?", ["calibrated digital wrench"], "hardware_maintenance_manual_xr4400.pdf"),
        ("What is the sub-zero limit for operating the XR-4400 gateway?", ["-20 degrees"], "hardware_maintenance_manual_xr4400.pdf"),
        ("What records must be destroyed per NIST SP 800-88 after 7 years?", ["primary storage keys", "secondary backups"], "data-protection-policy-2026.pdf"),
        ("What is the availability target for production API gateways?", ["99.95%"], "cloud_services_vendor_agreement.docx"),
        ("Which division must handle client notifications during a security incident?", ["Security Operations Center", "SOC"], "data-protection-policy-2026.pdf"),
        ("Is the Data Protection Policy optional for contractors?", ["mandatory", "external service contractors"], "data-protection-policy-2026.pdf"),
        ("What is the torque specification in Newton-meters for XR-4400?", ["45 Newton-meters", "45 Nm"], "hardware_maintenance_manual_xr4400.pdf"),
        ("What type of arbitration rules govern the vendor contract?", ["Commercial Arbitration Rules"], "cloud_services_vendor_agreement.docx"),
        ("How are expired cryptographic keys disposed of?", ["cryptographically shredded", "NIST SP 800-88"], "data-protection-policy-2026.pdf"),
        ("What is the service credit for 99.4% monthly availability?", ["15%"], "cloud_services_vendor_agreement.docx"),
        ("What is the service credit when uptime drops below 99.0%?", ["30%"], "cloud_services_vendor_agreement.docx"),
        ("What is the upper temperature rating for XR-4400 in Celsius?", ["+65 degrees", "65"], "hardware_maintenance_manual_xr4400.pdf"),
    ]
    for q, ans, doc in extra_answerable:
        entries.append({
            "id": f"gs-{len(entries)+1:03d}",
            "question": q,
            "answerable": True,
            "expected_document": doc,
            "expected_answer_contains": ans,
            "category": "general",
            "difficulty": "medium",
        })

    # -------------------------------------------------------------------------
    # Unanswerable Questions (Total: 35 -> 35% unanswerable, meeting >=30% BE-16-R8)
    # Covering all 4 required negative categories (BE-16-R9)
    # -------------------------------------------------------------------------
    
    # 1. Adjacent topic
    adj_unanswerable = [
        "What is the record retention period for internal employee HR files?",
        "How long are job applicant resumes retained after an interview?",
        "What is the retention schedule for corporate tax filings and invoices?",
        "What is the retention period for server syslogs and firewall audit trails?",
        "How long must physical badge access logs be archived in corporate security?",
        "What is the encryption standard for internal employee Slack messages?",
        "What is the data retention policy for vendor financial audit reports?",
        "How long are marketing email subscriber lists retained after unsubscribing?",
        "What is the retention requirement for board meeting minutes?",
    ]
    for q in adj_unanswerable:
        entries.append({
            "id": f"gs-{len(entries)+1:03d}",
            "question": q,
            "answerable": False,
            "category": "unanswerable_adjacent_topic",
            "difficulty": "hard",
        })

    # 2. Plausible but absent
    plausible_unanswerable = [
        "What is the financial penalty or fine for late security breach notification under the policy?",
        "What is the hourly fee charged for emergency SOC breach response support?",
        "What is the interest rate applied to overdue SLA service credits from the vendor?",
        "What is the maximum number of arbitrators appointed under the vendor agreement?",
        "What brand of digital torque wrench is certified for Model XR-4400 maintenance?",
        "How many spare flange bolts are included in the XR-4400 replacement kit?",
        "What is the minimum insurance coverage required for CloudProvider Corp?",
        "What is the severance compensation for data protection compliance officers?",
        "How often must the XR-4400 digital wrench be recalibrated by the manufacturer?",
    ]
    for q in plausible_unanswerable:
        entries.append({
            "id": f"gs-{len(entries)+1:03d}",
            "question": q,
            "answerable": False,
            "category": "unanswerable_plausible_absent",
            "difficulty": "hard",
        })

    # 3. Right document, wrong fact
    right_doc_unanswerable = [
        "Who signed the Data Protection and Customer Record Retention Policy 2026 on behalf of executive leadership?",
        "What is the email address of the Chief Information Security Officer in the Data Protection Policy?",
        "What is the physical corporate address of CloudProvider Corp listed in the MSA?",
        "Who is the designated account manager for ACME in the CloudProvider agreement?",
        "What is the serial number of the first manufactured Model XR-4400 gateway?",
        "What is the weight in kilograms of the Model XR-4400 industrial gateway?",
        "What revision letter is stamped on the XR-4400 maintenance manual cover?",
        "On what date was the Data Protection Policy approved by the Board of Directors?",
        "What is the governing law jurisdiction clause in Section 8 of the vendor agreement?",
    ]
    for q in right_doc_unanswerable:
        entries.append({
            "id": f"gs-{len(entries)+1:03d}",
            "question": q,
            "answerable": False,
            "category": "unanswerable_right_doc_wrong_fact",
            "difficulty": "hard",
        })

    # 4. Genuinely off-corpus
    off_corpus_unanswerable = [
        "What is the capital city of France?",
        "How many kilometers is the distance between the Earth and the Moon?",
        "Who was the first person to walk on the moon in 1969?",
        "What is the chemical formula for photosynthesis in green plants?",
        "Who wrote the play Hamlet in English literature?",
        "What is the speed of light in a vacuum in meters per second?",
        "Which football team won the FIFA World Cup in 2022?",
        "What is the recipe for baking traditional Italian sourdough bread?",
    ]
    for q in off_corpus_unanswerable:
        entries.append({
            "id": f"gs-{len(entries)+1:03d}",
            "question": q,
            "answerable": False,
            "category": "unanswerable_off_corpus",
            "difficulty": "easy",
        })

    out_file = Path(__file__).parent.parent / "eval" / "golden_set.jsonl"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    
    with open(out_file, "w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")

    print(f"Generated {len(entries)} golden set entries in {out_file}.")
    unanswerable_count = sum(1 for e in entries if not e["answerable"])
    print(f"Total: {len(entries)}, Unanswerable: {unanswerable_count} ({unanswerable_count/len(entries):.1%})")


if __name__ == "__main__":
    generate_golden_set()
