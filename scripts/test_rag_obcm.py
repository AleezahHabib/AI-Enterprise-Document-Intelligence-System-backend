import asyncio
import time
import httpx
import fitz  # PyMuPDF

def create_obcm_pdf() -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    text = """PPN 004: Open Book Contract Management (OBCM) Guidance

1. Executive Summary and Definition
Open Book Contract Management (OBCM) is a structured commercial management approach that provides the client with auditable visibility and transparency into the supplier's actual costs, overheads, and profit margins.

2. Core Objectives of PPN-004
The primary objective of PPN-004 Open Book Contract Management is to ensure value for money in public sector contracts by verifying allowable costs, preventing excess margins, and establishing collaborative commercial relationships. Under OBCM principles, suppliers must maintain transparent accounting records and grant contract authorities reasonable access to examine financial books and operational records throughout the contract lifecycle.

3. Applicable Scenarios
OBCM is mandated for high-value or critical public sector contracts where cost structures are complex or variable.
"""
    page.insert_text((50, 50), text, fontsize=11)
    pdf_bytes = doc.write()
    doc.close()
    return pdf_bytes

async def test_flow():
    client = httpx.AsyncClient(timeout=30.0)
    session_id = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    headers = {"X-Session-Id": session_id}
    
    print("1. Uploading PPN-004 document...")
    pdf_bytes = create_obcm_pdf()
    files = {"file": ("PPN-004_Open_Book_Contract_Management.pdf", pdf_bytes, "application/pdf")}
    data = {"title": "PPN-004 Open Book Contract Management"}
    
    res = await client.post("http://localhost:8000/api/v1/documents", headers=headers, files=files, data=data)
    print("Upload status:", res.status_code)
    assert res.status_code in (200, 202), f"Upload failed: {res.text}"
    doc_id = res.json()["id"]
    print("Uploaded document ID:", doc_id)
    
    print("2. Polling for document to become READY...")
    for _ in range(20):
        doc_res = await client.get(f"http://localhost:8000/api/v1/documents/{doc_id}", headers=headers)
        status = doc_res.json()["status"]
        print("Current status:", status)
        if status == "ready":
            break
        await asyncio.sleep(1)
    
    assert status == "ready", f"Document failed to reach ready status: {doc_res.json()}"
    print(f"Document {doc_id} is READY with {doc_res.json().get('chunk_count')} chunks.")
    
    print("3. Querying: 'What is Open Book Contract Management (OBCM)?'...")
    query_payload = {
        "question": "What is Open Book Contract Management (OBCM)?",
        "scope": "mine",
        "include_retrieval": True
    }
    q_res = await client.post("http://localhost:8000/api/v1/query", headers=headers, json=query_payload)
    print("Query status code:", q_res.status_code)
    assert q_res.status_code == 200, f"Query failed: {q_res.text}"
    q_data = q_res.json()
    print("Response Status:", q_data["status"])
    print("Answer text:", q_data.get("answer"))
    print("Claims count:", len(q_data.get("claims") or []))
    retrieval_chunks = q_data.get("retrieval", {}).get("chunks") or []
    print("Retrieved chunks:", len(retrieval_chunks))
    for c in retrieval_chunks:
        print(f" - Doc: {c['document_title']} | Similarity: {c['similarity']:.3f} | Score: {c['rrf_score']:.4f}")
    
    assert q_data["status"] == "answered", f"Expected answered status, got {q_data['status']}"
    assert "Open Book Contract Management" in (q_data.get("answer") or "") or "OBCM" in (q_data.get("answer") or "")
    
    print("\n4. Testing Unrelated Query Insufficient Context Fallback...")
    unrelated_payload = {
        "question": "What is the quantum teleportation wavelength of lithium ions in deep space?",
        "scope": "mine",
        "include_retrieval": True
    }
    un_res = await client.post("http://localhost:8000/api/v1/query", headers=headers, json=unrelated_payload)
    un_data = un_res.json()
    print("Unrelated Query Status:", un_data["status"])
    assert un_data["status"] == "insufficient_context", f"Expected insufficient_context, got {un_data['status']}"
    print("Refusal Reason:", un_data.get("refusal", {}).get("reason"))
    print("\n>>> ALL TEST VERIFICATIONS PASSED SUCCESSFULLY! <<<")

if __name__ == "__main__":
    asyncio.run(test_flow())
