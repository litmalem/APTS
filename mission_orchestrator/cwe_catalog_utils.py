from __future__ import annotations

import re
from typing import Any, Dict


# Lightweight local CWE enrichment for common web-application and CTI mapping cases.
# The text is intentionally short and paraphrased so it can be used as a UI summary.
CWE_KNOWLEDGE: dict[str, dict[str, str]] = {
    "CWE-20": {
        "name": "Improper Input Validation",
        "description": "The software does not validate or incorrectly validates input, allowing malformed or hostile data to reach security-sensitive logic.",
    },
    "CWE-22": {
        "name": "Improper Limitation of a Pathname to a Restricted Directory",
        "description": "The software allows path traversal so an attacker may access files outside the intended directory boundary.",
    },
    "CWE-74": {
        "name": "Improper Neutralization of Special Elements in Output Used by a Downstream Component",
        "description": "Special characters are not neutralized before data is passed to another component, enabling injection-style attacks.",
    },
    "CWE-77": {
        "name": "Improper Neutralization of Special Elements used in a Command",
        "description": "Input is placed into a command without adequate neutralization, allowing an attacker to alter command semantics.",
    },
    "CWE-78": {
        "name": "Improper Neutralization of Special Elements used in an OS Command",
        "description": "Untrusted input can influence an operating-system command, potentially enabling command execution on the host.",
    },
    "CWE-79": {
        "name": "Improper Neutralization of Input During Web Page Generation",
        "description": "Untrusted input is included in a web page without proper output encoding, allowing cross-site scripting execution in a browser.",
    },
    "CWE-89": {
        "name": "Improper Neutralization of Special Elements used in an SQL Command",
        "description": "Untrusted input is incorporated into an SQL query without proper parameterization or escaping, enabling SQL injection.",
    },
    "CWE-94": {
        "name": "Improper Control of Generation of Code",
        "description": "The software constructs code from externally influenced input, allowing an attacker to modify or execute code.",
    },
    "CWE-95": {
        "name": "Improper Neutralization of Directives in Dynamically Evaluated Code",
        "description": "Input reaches dynamic evaluation logic without sufficient neutralization, enabling code-injection behavior.",
    },
    "CWE-200": {
        "name": "Exposure of Sensitive Information to an Unauthorized Actor",
        "description": "Sensitive information is exposed to parties that should not be able to read it.",
    },
    "CWE-269": {
        "name": "Improper Privilege Management",
        "description": "Privileges are assigned, changed, or enforced incorrectly, allowing access beyond the intended authority.",
    },
    "CWE-284": {
        "name": "Improper Access Control",
        "description": "The software does not restrict access to resources or actions according to the intended security policy.",
    },
    "CWE-285": {
        "name": "Improper Authorization",
        "description": "Authorization checks are missing, incomplete, or incorrectly enforced for a protected action or resource.",
    },
    "CWE-287": {
        "name": "Improper Authentication",
        "description": "The software does not correctly prove the identity of a user, process, or system before granting access.",
    },
    "CWE-288": {
        "name": "Authentication Bypass Using an Alternate Path or Channel",
        "description": "An alternate route or interface bypasses the normal authentication mechanism.",
    },
    "CWE-306": {
        "name": "Missing Authentication for Critical Function",
        "description": "A critical function can be reached without requiring authentication.",
    },
    "CWE-307": {
        "name": "Improper Restriction of Excessive Authentication Attempts",
        "description": "The software does not adequately limit repeated authentication attempts, enabling brute-force or guessing attacks.",
    },
    "CWE-319": {
        "name": "Cleartext Transmission of Sensitive Information",
        "description": "Sensitive information is transmitted without sufficient encryption, exposing it to interception.",
    },
    "CWE-320": {
        "name": "Key Management Errors",
        "description": "The software handles cryptographic keys incorrectly, such as during generation, storage, distribution, rotation, or destruction.",
    },
    "CWE-321": {
        "name": "Use of Hard-coded Cryptographic Key",
        "description": "A cryptographic key is embedded in the software or configuration, making compromise likely if the application or binary is inspected.",
    },
    "CWE-326": {
        "name": "Inadequate Encryption Strength",
        "description": "The software uses encryption that is too weak for the required protection level.",
    },
    "CWE-327": {
        "name": "Use of a Broken or Risky Cryptographic Algorithm",
        "description": "A cryptographic algorithm with known weaknesses is used, reducing the protection of confidentiality or integrity.",
    },
    "CWE-328": {
        "name": "Use of Weak Hash",
        "description": "The software uses a hash algorithm that is insufficient for the intended security purpose.",
    },
    "CWE-330": {
        "name": "Use of Insufficiently Random Values",
        "description": "Random values are predictable or have insufficient entropy, weakening tokens, keys, or security decisions.",
    },
    "CWE-331": {
        "name": "Insufficient Entropy",
        "description": "The system does not provide enough entropy for cryptographic or security-sensitive random values.",
    },
    "CWE-352": {
        "name": "Cross-Site Request Forgery",
        "description": "The application cannot ensure that a state-changing request was intentionally initiated by the authenticated user.",
    },
    "CWE-400": {
        "name": "Uncontrolled Resource Consumption",
        "description": "The software does not adequately limit resource usage, enabling denial-of-service conditions.",
    },
    "CWE-434": {
        "name": "Unrestricted Upload of File with Dangerous Type",
        "description": "The application allows upload of files that can be interpreted or executed dangerously by the server or clients.",
    },
    "CWE-502": {
        "name": "Deserialization of Untrusted Data",
        "description": "Untrusted serialized data is processed in a way that can alter control flow, instantiate unsafe objects, or execute code.",
    },
    "CWE-522": {
        "name": "Insufficiently Protected Credentials",
        "description": "Credentials are stored, transmitted, or handled without adequate protection against disclosure or misuse.",
    },
    "CWE-601": {
        "name": "URL Redirection to Untrusted Site",
        "description": "User-controllable redirection can send victims to an attacker-controlled destination.",
    },
    "CWE-611": {
        "name": "Improper Restriction of XML External Entity Reference",
        "description": "XML external entity processing is not restricted, enabling data disclosure, SSRF, or denial-of-service behavior.",
    },
    "CWE-639": {
        "name": "Authorization Bypass Through User-Controlled Key",
        "description": "A user-controlled key or identifier is trusted for authorization decisions, enabling access to other users' objects.",
    },
    "CWE-787": {
        "name": "Out-of-bounds Write",
        "description": "The software writes data outside the intended memory boundary, potentially causing crashes or code execution.",
    },
    "CWE-798": {
        "name": "Use of Hard-coded Credentials",
        "description": "Credentials are embedded in source code, binaries, or configuration, making them difficult to rotate and easy to recover.",
    },
    "CWE-862": {
        "name": "Missing Authorization",
        "description": "The software does not perform an authorization check before allowing access to a resource or function.",
    },
    "CWE-863": {
        "name": "Incorrect Authorization",
        "description": "Authorization logic exists but evaluates the wrong subject, object, role, or condition.",
    },
    "CWE-918": {
        "name": "Server-Side Request Forgery",
        "description": "The server can be induced to make attacker-controlled requests, often reaching internal or otherwise restricted services.",
    },
    "CWE-922": {
        "name": "Insecure Storage of Sensitive Information",
        "description": "Sensitive information is stored without controls appropriate to its confidentiality requirements.",
    },
    "NVD-CWE-NOINFO": {
        "name": "Insufficient CWE Information",
        "description": "NVD did not provide a specific CWE classification for this vulnerability record.",
    },
    "NVD-CWE-OTHER": {
        "name": "Other CWE Classification",
        "description": "NVD classified the weakness as other or not represented by a more specific CWE in the record.",
    },
}


def normalize_cwe_id(value: Any) -> str:
    """Return a stable CWE identifier such as CWE-79 or NVD-CWE-NOINFO."""
    if value is None:
        return ""
    text = str(value).strip().upper().replace("_", "-")
    if not text:
        return ""
    if text.startswith("CWE-") or text.startswith("NVD-CWE-"):
        return text
    if text.isdigit():
        return f"CWE-{text}"
    return text


def cwe_definition_url(cwe_id: Any) -> str:
    """Build the canonical CWE definition URL when the ID is numeric."""
    cwe_id = normalize_cwe_id(cwe_id)
    m = re.match(r"^CWE-(\d+)$", cwe_id)
    if not m:
        return ""
    return f"https://cwe.mitre.org/data/definitions/{m.group(1)}.html"


def _first_non_empty(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def enrich_cwe_item(item: Dict[str, Any] | None) -> Dict[str, str]:
    """
    Add name, description, and official URL to a CWE row.

    The function prefers values already stored in the database, then falls back to
    the local lightweight catalog, then finally generates a URL from the CWE ID.
    """
    item = dict(item or {})
    cwe_id = normalize_cwe_id(_first_non_empty(item.get("cwe_id"), item.get("id"), item.get("cwe")))
    known = CWE_KNOWLEDGE.get(cwe_id, {})

    name = _first_non_empty(
        item.get("cwe_name"),
        item.get("name"),
        item.get("title"),
        known.get("name"),
    )
    url = _first_non_empty(
        item.get("cwe_url"),
        item.get("url"),
        known.get("url"),
        cwe_definition_url(cwe_id),
    )
    description = _first_non_empty(
        item.get("description_text"),
        item.get("cwe_description"),
        item.get("description"),
        item.get("summary"),
        known.get("description"),
    )
    if not description and cwe_id:
        description = "Uraian belum tersedia di katalog lokal. Buka URL CWE untuk melihat definisi resmi."

    return {
        "cwe_id": cwe_id,
        "cwe_name": name,
        "cwe_url": url,
        "description_text": description,
    }
