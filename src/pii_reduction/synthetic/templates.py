"""Document templates by language and difficulty tier.

Tiers follow ``docs/02_PUBLIC_DATA_STRATEGY.md``:

1. **clean** — well-formed prose, PII in its most recognizable shape;
2. **noisy** — lowercase, abbreviations, dashed or compact phone formats, shortened
   names;
3. **structured** — key/value blocks where labels and operational identifiers sit
   beside the sensitive values;
4. **transcript** — timestamped speaker turns; the prefix is structure, the body is
   eligible.

Placeholders in braces are replaced by the injector, which records the exact span of
each replacement in the emitted string. ``PERSON``/``EMAIL``/``PHONE`` become ground
truth; ``TICKET``/``KB``/``MACHINE``/``VERSION``/``ORDER``/``CHANGE``/``REQUEST``/
``ASSET`` become protected tokens that must survive reduction untouched
(``docs/10_TESTING_QA.md`` §6).

These are the *benchmark* corpus's templates. The second profile — the incident-notes
over-redaction stress corpus — lives in :mod:`pii_reduction.synthetic.incidents` and
shares this placeholder vocabulary and the same generator (ADR-0022).
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["TEMPLATES", "TemplateSpec", "templates_for"]

PLAIN = "plain"
TRANSCRIPT = "transcript"


@dataclass(frozen=True)
class TemplateSpec:
    tier: int
    document_type: str
    template: str


TEMPLATES: dict[str, tuple[TemplateSpec, ...]] = {
    "en": (
        TemplateSpec(1, PLAIN, "Please email {PERSON} at {EMAIL} about ticket {TICKET}."),
        TemplateSpec(1, PLAIN, "{PERSON} asked us to call {PHONE} before the weekend."),
        TemplateSpec(1, PLAIN, "Contact details confirmed: {EMAIL} and {PHONE}. See {KB}."),
        TemplateSpec(1, PLAIN, "The account owner is {PERSON}; no further action needed."),
        TemplateSpec(2, PLAIN, "pls call {PERSON_SHORT} on {PHONE_DASHED} thx"),
        TemplateSpec(2, PLAIN, "cust {PERSON_SHORT} mailed {EMAIL} re {TICKET} - no reply yet"),
        TemplateSpec(2, PLAIN, "callback req {PHONE_COMPACT} ({PERSON_SHORT}) asap"),
        TemplateSpec(2, PLAIN, "reopened {TICKET}, machine {MACHINE} still on {VERSION}"),
        TemplateSpec(
            3,
            PLAIN,
            "Customer: {PERSON}\nMobile number: {PHONE}\nEmail: {EMAIL}\n"
            "Machine name: {MACHINE}\nDepartment: Support",
        ),
        TemplateSpec(
            3,
            PLAIN,
            "Ticket: {TICKET}\nRequested by: {PERSON}\nContact: {EMAIL}\n"
            "KB Article: {KB}\nOrder: {ORDER}",
        ),
        TemplateSpec(
            4,
            TRANSCRIPT,
            "2026-04-03 09:15:04 - Support Agent: Hello, how can I help?\n"
            "2026-04-03 09:15:13 - Guest: Hi, I'm {PERSON}. Please call me on {PHONE}.\n"
            "2026-04-03 09:15:42 - Support Agent: Thank you, I have logged {TICKET}.\n",
        ),
        TemplateSpec(
            4,
            TRANSCRIPT,
            "2026-04-03 14:02:10 - Support Agent: Can you confirm your email?\n"
            "2026-04-03 14:02:31 - Guest: {EMAIL}\n"
            "2026-04-03 14:02:55 - Support Agent: Noted. Machine {MACHINE} is affected.\n",
        ),
    ),
    "de": (
        TemplateSpec(1, PLAIN, "Bitte schreiben Sie {PERSON} an {EMAIL} zum Vorgang {TICKET}."),
        TemplateSpec(1, PLAIN, "{PERSON} bittet um einen Rückruf unter {PHONE}."),
        TemplateSpec(1, PLAIN, "Kontaktdaten bestätigt: {EMAIL} sowie {PHONE}. Siehe {KB}."),
        TemplateSpec(1, PLAIN, "Der Kontoinhaber ist {PERSON}; keine weitere Aktion nötig."),
        TemplateSpec(2, PLAIN, "bitte {PERSON_SHORT} unter {PHONE_DASHED} anrufen, danke"),
        TemplateSpec(2, PLAIN, "kunde {PERSON_SHORT} hat an {EMAIL} geschrieben, {TICKET} offen"),
        TemplateSpec(2, PLAIN, "rueckruf {PHONE_COMPACT} ({PERSON_SHORT}) dringend"),
        TemplateSpec(2, PLAIN, "{TICKET} erneut geoeffnet, rechner {MACHINE} laeuft {VERSION}"),
        TemplateSpec(
            3,
            PLAIN,
            "Kunde: {PERSON}\nTelefonnummer: {PHONE}\nE-Mail: {EMAIL}\n"
            "Rechnername: {MACHINE}\nAbteilung: Support",
        ),
        TemplateSpec(
            3,
            PLAIN,
            "Vorgang: {TICKET}\nGemeldet von: {PERSON}\nKontakt: {EMAIL}\n"
            "KB-Artikel: {KB}\nBestellung: {ORDER}",
        ),
        TemplateSpec(
            4,
            TRANSCRIPT,
            "2026-04-03 10:02:11 - Berater: Guten Tag, wie kann ich helfen?\n"
            "2026-04-03 10:02:30 - Kunde: Mein Name ist {PERSON}, meine Nummer ist {PHONE}.\n"
            "2026-04-03 10:03:02 - Berater: Danke, ich habe {TICKET} angelegt.\n",
        ),
        TemplateSpec(
            4,
            TRANSCRIPT,
            "2026-04-03 16:20:00 - Berater: Können Sie Ihre E-Mail bestätigen?\n"
            "2026-04-03 16:20:24 - Kunde: {EMAIL}\n"
            "2026-04-03 16:20:51 - Berater: Notiert. Rechner {MACHINE} ist betroffen.\n",
        ),
    ),
    "el": (
        TemplateSpec(
            1, PLAIN, "Παρακαλώ στείλτε email στον/στην {PERSON} στο {EMAIL} για το {TICKET}."
        ),
        TemplateSpec(1, PLAIN, "{PERSON} ζητά να τηλεφωνήσουμε στο {PHONE}."),
        TemplateSpec(1, PLAIN, "Επιβεβαιώθηκαν τα στοιχεία: {EMAIL} και {PHONE}. Δείτε {KB}."),
        TemplateSpec(
            1, PLAIN, "Ο κάτοχος του λογαριασμού είναι {PERSON}· δεν απαιτείται ενέργεια."
        ),
        TemplateSpec(2, PLAIN, "καλεστε {PERSON_SHORT} στο {PHONE_DASHED} ευχαριστω"),
        TemplateSpec(2, PLAIN, "ο πελατης {PERSON_SHORT} εστειλε στο {EMAIL} για {TICKET}"),
        TemplateSpec(2, PLAIN, "επικοινωνια {PHONE_COMPACT} ({PERSON_SHORT}) επειγον"),
        TemplateSpec(2, PLAIN, "{TICKET} ανοιξε ξανα, μηχανημα {MACHINE} με {VERSION}"),
        TemplateSpec(
            3,
            PLAIN,
            "Πελάτης: {PERSON}\nΤηλέφωνο: {PHONE}\nEmail: {EMAIL}\n"
            "Όνομα μηχανήματος: {MACHINE}\nΤμήμα: Support",
        ),
        TemplateSpec(
            3,
            PLAIN,
            "Αίτημα: {TICKET}\nΑπό: {PERSON}\nΕπικοινωνία: {EMAIL}\n"
            "Άρθρο KB: {KB}\nΠαραγγελία: {ORDER}",
        ),
        TemplateSpec(
            4,
            TRANSCRIPT,
            "2026-04-03 11:20:00 - Πράκτορας: Καλημέρα, πώς μπορώ να βοηθήσω;\n"
            "2026-04-03 11:20:24 - Πελάτης: Ονομάζομαι {PERSON}, τηλέφωνο {PHONE}.\n"
            "2026-04-03 11:21:03 - Πράκτορας: Ευχαριστώ, κατέγραψα το {TICKET}.\n",
        ),
        TemplateSpec(
            4,
            TRANSCRIPT,
            "2026-04-03 18:05:00 - Πράκτορας: Μπορείτε να επιβεβαιώσετε το email σας;\n"
            "2026-04-03 18:05:22 - Πελάτης: {EMAIL}\n"
            "2026-04-03 18:05:47 - Πράκτορας: Καταγράφηκε. Το {MACHINE} επηρεάζεται.\n",
        ),
    ),
}


def templates_for(language: str) -> tuple[TemplateSpec, ...]:
    return TEMPLATES[language]
