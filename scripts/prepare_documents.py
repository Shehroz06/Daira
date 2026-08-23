"""Prepare the Daira legal document corpus.

Produces data/documents.json — a list of legal document *chunks*, each with
rich metadata (jurisdiction, domain, authority level, status, dates...).

The corpus here is a small demonstration knowledge base. Text entries are
simplified/paraphrased summaries of well-known statutes, clearly marked in
the `source` field — they are NOT verbatim statutory text. Chunking follows
the legal hierarchy (Act -> Section -> Subsection) and every chunk keeps its
parent context so it is understandable on its own.

Run:  python scripts/prepare_documents.py
"""

from __future__ import annotations

import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def doc(
    id: str,
    title: str,
    text: str,
    *,
    jurisdiction: str | None = None,
    province_or_state: str | None = None,
    legal_domain: str | None = None,
    document_type: str = "statute",
    authority_level: str = "primary",
    year: int | None = None,
    status: str = "active",
    source: str = "simplified summary",
    source_url: str = "",
    section: str | None = None,
    subsection: str | None = None,
    parent_document: str | None = None,
    effective_date: str | None = None,
    last_verified: str | None = None,
) -> dict:
    return {
        "id": id,
        "title": title,
        "text": text,
        "jurisdiction": jurisdiction,
        "province_or_state": province_or_state,
        "legal_domain": legal_domain,
        "document_type": document_type,
        "authority_level": authority_level,
        "year": year,
        "status": status,
        "source": source,
        "source_url": source_url,
        "section": section,
        "subsection": subsection,
        "parent_document": parent_document or title,
        "effective_date": effective_date,
        "last_verified": last_verified,
    }


DOCUMENTS: list[dict] = [
    # ------------------------------------------------------------------
    # Landlord–tenant — Punjab, Pakistan
    # ------------------------------------------------------------------
    doc(
        "prpa-2009-section-5",
        "Punjab Rented Premises Act 2009 — Section 5 (Tenancy Agreement)",
        "Punjab Rented Premises Act 2009, Section 5: A landlord and tenant must "
        "execute a written tenancy agreement. The agreement must state the rent, "
        "the amount of any advance or security deposit, the period of tenancy, and "
        "the date of commencement. The tenancy agreement is required to be "
        "registered with the Rent Registrar of the area where the premises are "
        "situated.",
        jurisdiction="Pakistan",
        province_or_state="Punjab",
        legal_domain="landlord_tenant",
        year=2009,
        section="5",
    ),
    doc(
        "prpa-2009-section-8",
        "Punjab Rented Premises Act 2009 — Section 8 (Security Deposit / Advance)",
        "Punjab Rented Premises Act 2009, Section 8: Any advance or security "
        "deposit paid by the tenant to the landlord must be recorded in the "
        "tenancy agreement. On termination of the tenancy, the landlord is "
        "required to refund the security deposit to the tenant after lawful "
        "deductions, if any, for outstanding rent or damage to the premises "
        "beyond normal wear and tear. A tenant whose deposit is wrongfully "
        "withheld may apply to the Rent Tribunal for recovery.",
        jurisdiction="Pakistan",
        province_or_state="Punjab",
        legal_domain="landlord_tenant",
        year=2009,
        section="8",
    ),
    doc(
        "prpa-2009-section-15",
        "Punjab Rented Premises Act 2009 — Section 15 (Eviction Grounds)",
        "Punjab Rented Premises Act 2009, Section 15: A landlord may seek eviction "
        "of a tenant only on grounds specified in the Act, including default in "
        "payment of rent, subletting without consent, using premises for a purpose "
        "other than agreed, causing material damage, or the landlord's genuine "
        "personal need. Eviction requires an application to the Rent Tribunal; a "
        "landlord may not evict a tenant by force or by cutting off utilities.",
        jurisdiction="Pakistan",
        province_or_state="Punjab",
        legal_domain="landlord_tenant",
        year=2009,
        section="15",
    ),
    doc(
        "prpa-2009-section-22",
        "Punjab Rented Premises Act 2009 — Section 22 (Rent Tribunal Procedure)",
        "Punjab Rented Premises Act 2009, Section 22: The Rent Tribunal has "
        "jurisdiction over disputes between landlords and tenants concerning "
        "rented premises, including recovery of rent, refund of security deposit, "
        "and eviction. The Tribunal is required to decide cases expeditiously. An "
        "appeal against a final order of the Rent Tribunal lies to the District "
        "Court within thirty days.",
        jurisdiction="Pakistan",
        province_or_state="Punjab",
        legal_domain="landlord_tenant",
        year=2009,
        section="22",
    ),
    doc(
        "rent-tribunal-judgment-2018",
        "Rent Tribunal Appeal — Deposit Refund Precedent (2018)",
        "In a 2018 appellate decision concerning the Punjab Rented Premises Act "
        "2009, the court held that a landlord bears the burden of proving lawful "
        "grounds for withholding a tenant's security deposit. Deductions for "
        "damage must be supported by evidence of the condition of the premises at "
        "commencement and termination of the tenancy. Absent such evidence, the "
        "full deposit must be refunded with the tenant entitled to apply for "
        "costs.",
        jurisdiction="Pakistan",
        province_or_state="Punjab",
        legal_domain="landlord_tenant",
        document_type="judgment",
        authority_level="judicial",
        year=2018,
        source="case summary",
    ),
    # ------------------------------------------------------------------
    # Employment — Pakistan
    # ------------------------------------------------------------------
    doc(
        "powa-1936-section-4",
        "Payment of Wages Act 1936 — Section 4 (Wage Periods)",
        "Payment of Wages Act 1936, Section 4: An employer must fix wage periods "
        "for the payment of wages. No wage period may exceed one month. Wages "
        "must be paid regularly for each wage period.",
        jurisdiction="Pakistan",
        legal_domain="employment",
        year=1936,
        section="4",
    ),
    doc(
        "powa-1936-section-5",
        "Payment of Wages Act 1936 — Section 5 (Time of Payment)",
        "Payment of Wages Act 1936, Section 5: Wages must be paid before the "
        "expiry of the seventh day after the last day of the wage period in "
        "establishments with fewer than one thousand workers, and before the "
        "expiry of the tenth day in other establishments. Where employment is "
        "terminated, wages earned must be paid before the expiry of the second "
        "working day after termination.",
        jurisdiction="Pakistan",
        legal_domain="employment",
        year=1936,
        section="5",
    ),
    doc(
        "powa-1936-section-7",
        "Payment of Wages Act 1936 — Section 7 (Lawful Deductions)",
        "Payment of Wages Act 1936, Section 7: Deductions from wages are "
        "permitted only as authorized by the Act, such as fines imposed under "
        "approved rules, deductions for absence from duty, for damage or loss "
        "caused by the worker's neglect or default, for house accommodation "
        "provided by the employer, and for recovery of advances. Unauthorized "
        "deductions are unlawful and the worker may claim a refund before the "
        "authority appointed under the Act.",
        jurisdiction="Pakistan",
        legal_domain="employment",
        year=1936,
        section="7",
    ),
    doc(
        "powa-1936-section-15",
        "Payment of Wages Act 1936 — Section 15 (Claims for Unpaid Wages)",
        "Payment of Wages Act 1936, Section 15: A worker whose wages have been "
        "delayed or from whose wages unauthorized deductions have been made may "
        "apply to the authority appointed under the Act for a direction to the "
        "employer to pay the wages due, together with compensation. Applications "
        "should ordinarily be made within a prescribed limitation period from the "
        "date the wages fell due.",
        jurisdiction="Pakistan",
        legal_domain="employment",
        year=1936,
        section="15",
    ),
    doc(
        "labour-guidance-unpaid-wages",
        "Labour Department Guidance — Unpaid Wages Complaints",
        "Provincial labour department guidance: A worker who has not been paid "
        "may first make a written demand to the employer, keeping a copy. If the "
        "employer still refuses to pay, the worker may file a complaint with the "
        "local labour office or the wages authority. Workers should keep "
        "employment contracts, attendance records, pay slips, and any written "
        "communication as evidence. Trade unions and labour lawyers can assist "
        "with claims.",
        jurisdiction="Pakistan",
        legal_domain="employment",
        document_type="guidance",
        authority_level="guidance",
        source="government guidance summary",
    ),
    # ------------------------------------------------------------------
    # Consumer protection — Punjab, Pakistan
    # ------------------------------------------------------------------
    doc(
        "pcpa-2005-section-4",
        "Punjab Consumer Protection Act 2005 — Section 4 (Defective Products)",
        "Punjab Consumer Protection Act 2005, Section 4: A manufacturer or "
        "supplier is liable for damage proximately caused by a defective product. "
        "A product is defective when it does not conform to mandatory safety "
        "standards, or is otherwise unfit for the purpose for which it is "
        "ordinarily used.",
        jurisdiction="Pakistan",
        province_or_state="Punjab",
        legal_domain="consumer_law",
        year=2005,
        section="4",
    ),
    doc(
        "pcpa-2005-section-10",
        "Punjab Consumer Protection Act 2005 — Section 10 (Faulty Services)",
        "Punjab Consumer Protection Act 2005, Section 10: A provider of services "
        "is liable for damage proximately caused by providing a service that is "
        "faulty — that is, not conforming to the quality and manner of "
        "performance that the consumer was entitled to expect under the contract "
        "or by law.",
        jurisdiction="Pakistan",
        province_or_state="Punjab",
        legal_domain="consumer_law",
        year=2005,
        section="10",
    ),
    doc(
        "pcpa-2005-section-28",
        "Punjab Consumer Protection Act 2005 — Section 28 (Consumer Court Claims)",
        "Punjab Consumer Protection Act 2005, Section 28: A consumer may file a "
        "claim before the Consumer Court within thirty days of the arising of the "
        "cause of action, after first serving a written notice of the defect or "
        "fault on the supplier. The Consumer Court may order repair, replacement, "
        "refund, or compensation for damages.",
        jurisdiction="Pakistan",
        province_or_state="Punjab",
        legal_domain="consumer_law",
        year=2005,
        section="28",
    ),
    # ------------------------------------------------------------------
    # Contract law — Pakistan
    # ------------------------------------------------------------------
    doc(
        "contract-act-1872-section-10",
        "Contract Act 1872 — Section 10 (What Agreements Are Contracts)",
        "Contract Act 1872, Section 10: All agreements are contracts if they are "
        "made by the free consent of parties competent to contract, for a lawful "
        "consideration and with a lawful object, and are not expressly declared "
        "void. Competence requires the age of majority and sound mind.",
        jurisdiction="Pakistan",
        legal_domain="contract_law",
        year=1872,
        section="10",
    ),
    doc(
        "contract-act-1872-section-14",
        "Contract Act 1872 — Section 14 (Free Consent)",
        "Contract Act 1872, Section 14: Consent is free when it is not caused by "
        "coercion, undue influence, fraud, misrepresentation, or mistake. When "
        "consent to an agreement is caused by coercion, fraud, or "
        "misrepresentation, the agreement is a contract voidable at the option of "
        "the party whose consent was so caused.",
        jurisdiction="Pakistan",
        legal_domain="contract_law",
        year=1872,
        section="14",
    ),
    doc(
        "contract-act-1872-section-23",
        "Contract Act 1872 — Section 23 (Unlawful Consideration and Object)",
        "Contract Act 1872, Section 23: The consideration or object of an "
        "agreement is unlawful if it is forbidden by law, would defeat the "
        "provisions of any law, is fraudulent, involves injury to a person or "
        "property, or is regarded as immoral or opposed to public policy. Every "
        "agreement of which the object or consideration is unlawful is void.",
        jurisdiction="Pakistan",
        legal_domain="contract_law",
        year=1872,
        section="23",
    ),
    doc(
        "contract-act-1872-section-74",
        "Contract Act 1872 — Section 74 (Penalty Clauses and Liquidated Damages)",
        "Contract Act 1872, Section 74: When a contract is broken and a sum is "
        "named in the contract as the amount payable on breach, or the contract "
        "contains any other stipulation by way of penalty, the aggrieved party is "
        "entitled to reasonable compensation not exceeding the amount named, "
        "whether or not actual damage is proved. Courts may reduce an excessive "
        "penalty to reasonable compensation.",
        jurisdiction="Pakistan",
        legal_domain="contract_law",
        year=1872,
        section="74",
    ),
    # ------------------------------------------------------------------
    # Constitutional — Pakistan
    # ------------------------------------------------------------------
    doc(
        "constitution-pk-article-4",
        "Constitution of Pakistan — Article 4 (Protection of Law)",
        "Constitution of Pakistan, Article 4: It is the inalienable right of "
        "every citizen, wherever they may be, and of every other person for the "
        "time being within Pakistan, to enjoy the protection of law and to be "
        "treated in accordance with law. No action detrimental to the life, "
        "liberty, body, reputation or property of any person may be taken except "
        "in accordance with law.",
        jurisdiction="Pakistan",
        legal_domain="constitutional_law",
        document_type="constitution",
        authority_level="constitutional",
        year=1973,
        section="Article 4",
    ),
    doc(
        "constitution-pk-article-10a",
        "Constitution of Pakistan — Article 10A (Right to Fair Trial)",
        "Constitution of Pakistan, Article 10A: For the determination of civil "
        "rights and obligations, or in any criminal charge against a person, that "
        "person is entitled to a fair trial and due process. This right was "
        "inserted by the Eighteenth Amendment in 2010.",
        jurisdiction="Pakistan",
        legal_domain="constitutional_law",
        document_type="constitution",
        authority_level="constitutional",
        year=1973,
        section="Article 10A",
    ),
    # ------------------------------------------------------------------
    # Jurisdiction contrast — India (Punjab) tenancy
    # ------------------------------------------------------------------
    doc(
        "india-punjab-rent-act-section-13",
        "East Punjab Urban Rent Restriction Act 1949 (India) — Eviction Protections",
        "East Punjab Urban Rent Restriction Act 1949 (India), summary: In the "
        "Indian state of Punjab, a tenant of an urban rented building may be "
        "evicted only through an application to the Rent Controller on specified "
        "grounds such as non-payment of rent, subletting without written consent, "
        "or the landlord's bona fide requirement. This Indian law is distinct "
        "from Pakistani tenancy law and applies only in the relevant Indian "
        "state.",
        jurisdiction="India",
        province_or_state="Punjab",
        legal_domain="landlord_tenant",
        year=1949,
        section="13",
    ),
    # ------------------------------------------------------------------
    # Superseded document example (for date/status ranking)
    # ------------------------------------------------------------------
    doc(
        "punjab-rent-ordinance-1959-section-13",
        "West Pakistan Urban Rent Restriction Ordinance 1959 — Section 13 (Repealed in Punjab)",
        "West Pakistan Urban Rent Restriction Ordinance 1959, Section 13 "
        "(historical): This ordinance formerly governed eviction of tenants in "
        "urban areas of Punjab. It was repealed and replaced in Punjab by the "
        "Punjab Rented Premises Act 2009 for the areas to which that Act "
        "applies. It remains relevant only for historical questions or "
        "proceedings begun under the old law.",
        jurisdiction="Pakistan",
        province_or_state="Punjab",
        legal_domain="landlord_tenant",
        year=1959,
        status="repealed",
        section="13",
    ),
    # ------------------------------------------------------------------
    # Secondary commentary example
    # ------------------------------------------------------------------
    doc(
        "commentary-security-deposits",
        "Legal Commentary — Security Deposits in Pakistani Tenancy Practice",
        "Academic commentary: In practice, security deposits in Pakistani "
        "tenancies commonly range from one to three months' rent. Commentators "
        "note that disputes usually arise because the deposit and its conditions "
        "were not recorded in a registered tenancy agreement. Best practice for "
        "tenants is to obtain a receipt for the deposit, record it in the written "
        "agreement, and document the condition of the premises at move-in and "
        "move-out.",
        jurisdiction="Pakistan",
        legal_domain="landlord_tenant",
        document_type="commentary",
        authority_level="secondary",
        source="academic commentary summary",
    ),
]


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    out = DATA_DIR / "documents.json"
    with out.open("w", encoding="utf-8") as f:
        json.dump(DOCUMENTS, f, ensure_ascii=False, indent=2)
    print(f"Wrote {len(DOCUMENTS)} document chunks to {out}")


if __name__ == "__main__":
    main()
