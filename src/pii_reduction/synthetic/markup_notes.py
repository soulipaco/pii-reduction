"""Markup-bearing note templates: the corpus ADR-0027 had no measurement on.

ADR-0027 shipped a detection change — a span clipped out of machine syntax at the
provider boundary, and an output check that blocks a run when a tag disappears — with
**zero corpus support**. Every corpus in this repository is markup-free: the committed
benchmark corpus, all three demo packs, and the incident stress corpus. So the failure
class the guard exists for had no number attached anywhere, which is exactly the state
that let three leaks through the guard's own first draft (recorded in ADR-0027).

This corpus is that number. It is the third profile over
:func:`pii_reduction.synthetic.corpus.build_corpus`, after the benchmark corpus and
the incident-notes stress corpus (ADR-0022), and it reuses every invariant that
generator already enforces rather than growing a parallel one.

**It is not a pack and carries no realism claim.** Its prose is ours, so it says
nothing about how the pipeline performs on text nobody wrote for us — that claim
belongs to `demo/packs/`. What a generated corpus *can* say honestly is whether
machine syntax survives reduction, because markup dialects are conventions: whether we
or a service desk wrote the sentence around a ``<div>`` does not change whether the
tag comes through intact.

**Every markup shape here is one the reference implementation measured being
destroyed** (`docs/20_ALTERNATIVE_RECONCILIATION.md`), not a shape invented to be
easy:

* ``[code]<div class=…>`` — the exact adjacency spaCy returned as a PERSON at 0.85,
  and the single most damaging failure in their catalogue;
* a URL beside a name, which came back as a location span that ate the leading
  bracket;
* a name inside an anchor's ``title`` attribute, which is legitimately redacted and
  must not read as a lost tag;
* BBCode blocks, which their ServiceNow journals carry;
* ``&nbsp;`` runs and a zero-width space, which a model attaches to a neighbouring
  span.

Tiers follow `docs/02_PUBLIC_DATA_STRATEGY.md` as the other two profiles do: tier 3 is
the structured note with quoted markup, tier 4 the timestamped history whose bodies
carry it. Both are deliberately dense in markup; neither is a claim about how common
that density is. The reference corpus profile recorded markup in **72% of non-empty
cells** on its largest ServiceNow journal column, so dense is not unrealistic — but
that is their measurement on their data, and it is quoted here as context rather than
as a target.

The placeholder vocabulary is shared with the other two profiles, so the same
identifiers are protected and the same PII becomes ground truth. That matters: this
corpus measures *both* directions at once — a tag destroyed is a fidelity failure, an
asset tag destroyed is over-redaction, and a name left behind is leakage.
"""

from __future__ import annotations

from pii_reduction.synthetic.errors import CorpusError
from pii_reduction.synthetic.templates import PLAIN, TRANSCRIPT, TemplateSpec

__all__ = ["MARKUP_TEMPLATES", "markup_templates"]

#: Tier 3 — a note whose body carries quoted HTML, the shape a ServiceNow journal gets
#: when someone pastes a rendered mail. The `[code]<div` adjacency on the second line
#: is the measured failure, reproduced exactly.
_NOTE_EN = (
    "Incident {TICKET} — customer correspondence\n"
    "[code]<div class='mail'>\n"
    "<b>From:</b> {PERSON} &lt;{EMAIL}&gt;<br>\n"
    "<b>Callback:</b> {PHONE}<br>\n"
    "<b>Asset:</b> {ASSET} on {MACHINE}<br>\n"
    "</div>[/code]\n"
    "Knowledge article {KB} was sent; see <a href='https://support.example.test/kb'>the "
    "article</a>.\n"
)
_NOTE_DE = (
    "Vorfall {TICKET} — Kundenkorrespondenz\n"
    "[code]<div class='mail'>\n"
    "<b>Von:</b> {PERSON} &lt;{EMAIL}&gt;<br>\n"
    "<b>Rueckruf:</b> {PHONE}<br>\n"
    "<b>Inventar:</b> {ASSET} auf {MACHINE}<br>\n"
    "</div>[/code]\n"
    "Wissensartikel {KB} wurde gesendet; siehe <a href='https://support.example.test/kb'>den "
    "Artikel</a>.\n"
)
_NOTE_EL = (
    "Περιστατικό {TICKET} — αλληλογραφία πελάτη\n"
    "[code]<div class='mail'>\n"
    "<b>Από:</b> {PERSON} &lt;{EMAIL}&gt;<br>\n"
    "<b>Επιστροφή κλήσης:</b> {PHONE}<br>\n"
    "<b>Πάγιο:</b> {ASSET} στο {MACHINE}<br>\n"
    "</div>[/code]\n"
    "Το άρθρο {KB} στάλθηκε· δείτε <a href='https://support.example.test/kb'>το άρθρο</a>.\n"
)

#: Tier 3, second shape — a name inside an anchor attribute. Redacting it there is
#: **correct**, and the output check must not read the resulting `<a title='<PERSON>'>`
#: as a lost tag. That is why the check compares tag names and strips redaction labels
#: from both sides (ADR-0027); this template is what would catch it if it stopped.
_ATTRIBUTE_EN = (
    "Ticket: {TICKET}\n"
    "Owner: <a href='https://directory.example.test/u/1' title='{PERSON}'>profile</a>\n"
    "Contact: {EMAIL}&nbsp;/&nbsp;{PHONE}\n"
    "Change: {CHANGE}\n"
)
_ATTRIBUTE_DE = (
    "Vorgang: {TICKET}\n"
    "Besitzer: <a href='https://directory.example.test/u/1' title='{PERSON}'>Profil</a>\n"
    "Kontakt: {EMAIL}&nbsp;/&nbsp;{PHONE}\n"
    "Aenderung: {CHANGE}\n"
)
_ATTRIBUTE_EL = (
    "Αίτημα: {TICKET}\n"
    "Κάτοχος: <a href='https://directory.example.test/u/1' title='{PERSON}'>προφίλ</a>\n"
    "Επικοινωνία: {EMAIL}&nbsp;/&nbsp;{PHONE}\n"
    "Αλλαγή: {CHANGE}\n"
)

#: Tier 4 — the timestamped history. The prefix is structure the parser preserves; the
#: bodies carry the markup, so every clip happens *inside* an eligible region, which is
#: the whole point of ADR-0027.
_HISTORY_EN = (
    "2026-04-03 09:12:04 - Service Desk: Logged {TICKET} for {MACHINE}.\n"
    "2026-04-03 10:44:19 - Automation: [url=https://runbook.example.test/{VERSION}]runbook[/url] "
    "applied under {CHANGE}.\n"
    "2026-04-03 11:31:52 - Service Desk: Caller {PERSON} reachable on {PHONE};"
    "​ see <i>{KB}</i>.\n"
    "2026-04-03 12:05:40 - Service Desk: <p>Confirmation sent to {EMAIL}.</p>\n"
)
_HISTORY_DE = (
    "2026-04-03 09:12:04 - Service Desk: {TICKET} fuer {MACHINE} eroeffnet.\n"
    "2026-04-03 10:44:19 - Automatisierung: [url=https://runbook.example.test/{VERSION}]Handbuch"
    "[/url] unter {CHANGE} verteilt.\n"
    "2026-04-03 11:31:52 - Service Desk: Anrufer {PERSON} erreichbar unter {PHONE};"
    "​ siehe <i>{KB}</i>.\n"
    "2026-04-03 12:05:40 - Service Desk: <p>Bestaetigung an {EMAIL} gesendet.</p>\n"
)
_HISTORY_EL = (
    "2026-04-03 09:12:04 - Service Desk: Καταγράφηκε {TICKET} για {MACHINE}.\n"
    "2026-04-03 10:44:19 - Αυτοματισμός: [url=https://runbook.example.test/{VERSION}]οδηγός[/url] "
    "με αλλαγή {CHANGE}.\n"
    "2026-04-03 11:31:52 - Service Desk: Ο καλών {PERSON} στο {PHONE}·"
    "​ δείτε <i>{KB}</i>.\n"
    "2026-04-03 12:05:40 - Service Desk: <p>Επιβεβαίωση στο {EMAIL}.</p>\n"
)

MARKUP_TEMPLATES: dict[str, tuple[TemplateSpec, ...]] = {
    "en": (
        TemplateSpec(tier=3, document_type=PLAIN, template=_NOTE_EN),
        TemplateSpec(tier=3, document_type=PLAIN, template=_ATTRIBUTE_EN),
        TemplateSpec(tier=4, document_type=TRANSCRIPT, template=_HISTORY_EN),
    ),
    "de": (
        TemplateSpec(tier=3, document_type=PLAIN, template=_NOTE_DE),
        TemplateSpec(tier=3, document_type=PLAIN, template=_ATTRIBUTE_DE),
        TemplateSpec(tier=4, document_type=TRANSCRIPT, template=_HISTORY_DE),
    ),
    "el": (
        TemplateSpec(tier=3, document_type=PLAIN, template=_NOTE_EL),
        TemplateSpec(tier=3, document_type=PLAIN, template=_ATTRIBUTE_EL),
        TemplateSpec(tier=4, document_type=TRANSCRIPT, template=_HISTORY_EL),
    ),
}


def markup_templates(language: str) -> tuple[TemplateSpec, ...]:
    """Templates for one language, in the shape ``build_corpus`` expects."""
    try:
        return MARKUP_TEMPLATES[language]
    except KeyError:
        raise CorpusError(
            f"no markup templates for language {language!r} "
            f"(have: {', '.join(sorted(MARKUP_TEMPLATES))})"
        ) from None
