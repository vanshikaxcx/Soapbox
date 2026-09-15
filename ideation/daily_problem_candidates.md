# India daily-life pain points: 4-day Build It candidates

Evidence links are included so the team can cite them in the pitch. Each idea deliberately narrows to one user and a demo-able workflow using local Strands agent, Cedar policy checks, SAM Local/LocalStack and offline OpenSearch.

## Ranked top five

1. **Failed UPI payment recovery kit (small merchants / consumers).** National Consumer Helpline's 2020-21 annual report says failed transactions were ~30% of digital-payment grievances. Build an offline-first assistant: ingest SMS/screenshot, extract UTR, classify pending/failed/duplicate, generate bank/app escalation text and deadline checklist, enforce Cedar redaction/consent. Sources: [NCH annual report](https://consumerhelpline.gov.in/public/assets/docs/annual-reports/Annual%20Report%202020-21.pdf), [RBI Ombudsman report](https://systemhealth.rbi.org.in/Scripts/PublicationsView.aspx_id%3D22432%281%29.html). **Crowding:** many UPI help apps; differentiate with local-language, evidence bundle and policy-safe PII handling.

2. **Civic complaint triage and follow-up (apartment resident / ward volunteer).** Swachh Survekshan recorded 1.18 crore Swachhata App complaints; CPGRAMS redressed 26,45,869 grievances in 2024 and still had 59,946 pending (Feb 2025). Demo photo/voice -> issue category, location and severity -> deduplicate nearby reports -> produce correct department submission and reminder/appeal. Sources: [PIB Swachh Survekshan](https://www.pib.gov.in/newsite/erelcontent.aspx?lang=2&reg=48&relid=179355), [PIB CPGRAMS 2025](https://www.pib.gov.in/Pressreleaseshare.aspx?PRID=2117810&lang=2&reg=48). **Crowding:** civic-reporting platforms; narrow to one ward and transparent status/evidence trail.

3. **Migrant ration access navigator (interstate worker).** ONORC covers all 36 States/UTs and ~80 crore NFSA beneficiaries; PIB documents >93.31 crore portability transactions. Build a low-connectivity voice/chat flow that checks eligibility, finds nearby ePoS FPS from a cached dataset, explains biometric fallback and creates a local-language dealer/helpline message. Sources: [PIB ONORC](https://www.pib.gov.in/Pressreleaseshare.aspx?PRID=1881527&lang=2&reg=48), [DFPD FAQ](https://dfpd.gov.in/faqs/en), [Open Government Data](https://data.gov.in/catalog/one-nation-one-ration-card-onorc-plan). **Crowding:** government apps already exist; focus on offline explainability and failed-biometric recovery, not another entitlement database.

4. **Metro last-mile planner for women/shift workers.** WRI India's three-city survey covered 7,200 commuters and reports poor last-mile access contributes to underused metro investment. Demo cached station/feeder options with safety/time/cost constraints and a Cedar policy that avoids exposing a user's exact trip. Source: [WRI Improving Metro Access](https://wri-india.org/research/improving-metro-access-india). **Crowding:** maps/ride-hailing; differentiate by offline station micro-routes and explainable safety trade-offs for one corridor.

5. **Daily-wage clinic visit scheduler (informal women workers).** A recent SEWA-linked study reports long public-health waits cause wage loss and disincentivize care, alongside irregular wages/no paid leave. Demo symptom intake (non-diagnostic), appointment/queue planning, document checklist, and referral/translation; Cedar blocks diagnosis and sensitive-data leakage. Source: [peer-reviewed PMC study](https://pmc.ncbi.nlm.nih.gov/articles/PMC12797478/). **Crowding:** telemedicine; position as queue-and-wage-loss logistics, not medical advice.

## Five additional candidates

6. **E-commerce return/refund evidence pack (first-time online shopper).** NCH reports pan-India e-commerce refund grievances; parse invoice, policy and chats into a dated evidence bundle and escalation ladder. Source: [Consumer Affairs press release](https://consumeraffairs.gov.in/public/upload/admin/cmsfiles/pressRelease/National_Consumer_Helpline_Facilitates_52_Crore_in_Refunds_Across_31_Sectorspress_release.pdf). Risk: legal-advice liability; constrain to drafting and links.

7. **Household waste segregation coach (domestic worker/apartment).** MoSPI NSS Report 584 includes household garbage collection/disposal and sanitation conditions. Offline image/voice classifier gives bin guidance and pickup-day reminders; avoid claiming image certainty. Source: [NSS Report 584 PDF](https://mospi.gov.in/sites/default/files/publication_reports/Report_584_final_0.pdf). Risk: computer-vision data and municipal variation.

8. **Government-grievance form translator (senior citizen).** CPGRAMS volume and 103,183 mapped grievance officers show scale; agent converts colloquial Hindi/regional voice to a structured complaint, checks missing fields and tracks ID. Source: [PIB CPGRAMS](https://www.pib.gov.in/Pressreleaseshare.aspx?PRID=2117810&lang=2&reg=48). Risk: existing portal; focus on accessibility and offline draft.

9. **Informal worker welfare-document checklist (construction worker).** NITI Aayog's informal-workforce profiles explicitly cover social protection and digital readiness. Agent maps a user's state, occupation and documents to a cached scheme checklist, with Cedar consent controls. Source: [NITI Aayog informal workforce](https://www.niti.gov.in/node/1994). Risk: scheme rules change; display dataset date and no eligibility guarantee.

10. **Water outage/tanker coordination (urban apartment secretary).** NSS 79th round data (reported by secondary coverage) indicates tap water is widespread but intermittent; build a local log of supply windows, resident reports and tanker demand forecast. Prefer primary NSS PDF before claiming statistics. Risk: highly locality-specific; validate with one apartment/campus.

## Best 4-day scope

Choose #1 or #2: both have abundant realistic sample inputs (SMS/screenshots or civic photos), clear agent extraction/classification, searchable offline corpus, and visible policy enforcement (PII redaction, consent, safe escalation). Avoid live government/payment integrations; use synthetic fixtures and cached public documents.
