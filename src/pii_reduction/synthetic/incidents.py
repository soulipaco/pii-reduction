"""Incident work-note templates: an over-redaction stress corpus (ADR-0022).

This is **not** a public-dataset pack and must never be published as one. It is
generated, so its prose says nothing about how the pipeline performs on text nobody
wrote for us — that claim belongs to `demo/packs/` and to `docs/15_PROVIDERS.md`.

What it does test is the one thing a generated corpus can test honestly. Operational
identifier formats are *conventions* — ``INC00100037``, ``CHG0030017``, ``AST-B90029``
— and `is_identifier_shaped` judges a surface by its token structure rather than by
its meaning. Whether we or a real service desk wrote the sentence around an asset tag
does not change whether the tag survives reduction.

It exists because the over-redaction gate was thinly supported. Measured before this
corpus was built:

| corpus | protected tokens | per document | distinct kinds |
|---|---|---|---|
| committed benchmark corpus | 102 | 1.00 | 5 |
| `support_tickets` pack | 56 | 0.28 | 1 |
| `multilingual_utterances` pack | **0** | 0.00 | 0 |

So a 0.000 over-redaction rate rested almost entirely on one corpus carrying one
identifier per document — while ADR-0021's span extension leans on the identifier
guard to stay there. These documents carry six or seven identifiers each, across seven
kinds, sitting directly beside the names, emails and phone numbers a reducer is
supposed to remove.

Tiers are reused from `docs/02_PUBLIC_DATA_STRATEGY.md` rather than invented: tier 3
is the structured incident header, tier 4 the timestamped work-note history. Both are
deliberately dense; neither is a claim about how common that density is.
"""

from __future__ import annotations

from pii_reduction.synthetic.errors import CorpusError
from pii_reduction.synthetic.templates import TemplateSpec

#: Tier 3 — the incident header. Every line is a field label beside a value, which is
#: the shape that made English tier-3 PERSON recall 0.333 before ADR-0016, and which
#: puts operational identifiers immediately next to sensitive ones.
_HEADER_EN = (
    "Incident: {TICKET}\n"
    "Configuration item: {MACHINE}\n"
    "Related change: {CHANGE}\n"
    "Raised by: {PERSON}\n"
    "Contact: {EMAIL}\n"
    "Callback: {PHONE}\n"
    "Asset tag: {ASSET}\n"
    "Knowledge article: {KB}\n"
    "Agent build: {VERSION}\n"
)
_HEADER_DE = (
    "Vorfall: {TICKET}\n"
    "Konfigurationselement: {MACHINE}\n"
    "Zugehoerige Aenderung: {CHANGE}\n"
    "Gemeldet von: {PERSON}\n"
    "Kontakt: {EMAIL}\n"
    "Rueckruf: {PHONE}\n"
    "Inventarnummer: {ASSET}\n"
    "Wissensartikel: {KB}\n"
    "Agentenversion: {VERSION}\n"
)
_HEADER_EL = (
    "Περιστατικό: {TICKET}\n"
    "Στοιχείο διαμόρφωσης: {MACHINE}\n"
    "Σχετική αλλαγή: {CHANGE}\n"
    "Καταγράφηκε από: {PERSON}\n"
    "Επικοινωνία: {EMAIL}\n"
    "Τηλέφωνο: {PHONE}\n"
    "Κωδικός παγίου: {ASSET}\n"
    "Άρθρο γνώσης: {KB}\n"
    "Έκδοση πράκτορα: {VERSION}\n"
)

#: Tier 4 — the work-note history. Timestamp and author are structure; the note body
#: is eligible text. Unlike the benchmark corpus's transcripts these notes are written
#: *about* a system, so identifiers and names appear in the same clause rather than in
#: separate turns.
_NOTES_EN = (
    "Incident {TICKET} — work notes\n"
    "2026-04-03 09:12:04 - {PERSON}: Alert confirmed on {MACHINE}; opened {REQUEST}.\n"
    "2026-04-03 10:44:19 - Automation: Applied {VERSION} under change {CHANGE}.\n"
    "2026-04-03 11:31:52 - {PERSON_SHORT}: Caller reachable on {PHONE}; see {KB}.\n"
    "2026-04-03 12:05:40 - Service Desk: Asset {ASSET} returned. Notify {EMAIL}.\n"
)
_NOTES_DE = (
    "Vorfall {TICKET} — Arbeitsnotizen\n"
    "2026-04-03 09:12:04 - {PERSON}: Meldung auf {MACHINE} bestaetigt; {REQUEST} eroeffnet.\n"
    "2026-04-03 10:44:19 - Automatisierung: {VERSION} unter Aenderung {CHANGE} verteilt.\n"
    "2026-04-03 11:31:52 - {PERSON_SHORT}: Anrufer erreichbar unter {PHONE}; siehe {KB}.\n"
    "2026-04-03 12:05:40 - Service Desk: Inventar {ASSET} zurueck. Info an {EMAIL}.\n"
)
_NOTES_EL = (
    "Περιστατικό {TICKET} — σημειώσεις εργασίας\n"
    "2026-04-03 09:12:04 - {PERSON}: Επιβεβαιώθηκε στο {MACHINE}· ανοίχτηκε {REQUEST}.\n"
    "2026-04-03 10:44:19 - Αυτοματισμός: Εφαρμόστηκε {VERSION} με αλλαγή {CHANGE}.\n"
    "2026-04-03 11:31:52 - {PERSON_SHORT}: Τηλέφωνο {PHONE}· δείτε {KB}.\n"
    "2026-04-03 12:05:40 - Γραφείο: Το πάγιο {ASSET} επιστράφηκε. Ενημέρωση {EMAIL}.\n"
)

INCIDENT_TEMPLATES: dict[str, tuple[TemplateSpec, ...]] = {
    "en": (
        TemplateSpec(tier=3, document_type="plain", template=_HEADER_EN),
        TemplateSpec(tier=4, document_type="transcript", template=_NOTES_EN),
    ),
    "de": (
        TemplateSpec(tier=3, document_type="plain", template=_HEADER_DE),
        TemplateSpec(tier=4, document_type="transcript", template=_NOTES_DE),
    ),
    "el": (
        TemplateSpec(tier=3, document_type="plain", template=_HEADER_EL),
        TemplateSpec(tier=4, document_type="transcript", template=_NOTES_EL),
    ),
}


def incident_templates(language: str) -> tuple[TemplateSpec, ...]:
    """Templates for one language, in the shape ``build_corpus`` expects."""
    try:
        return INCIDENT_TEMPLATES[language]
    except KeyError:
        raise CorpusError(
            f"no incident templates for language {language!r} "
            f"(have: {', '.join(sorted(INCIDENT_TEMPLATES))})"
        ) from None
