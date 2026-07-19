"""Helpers for CRM task attachments — filename sanitization + a
block-list of dangerous extensions.

This is an internal team tool: file types aren't known in advance
(pdf/docx/xlsx/zip/png/...), so a WHITE-list is impractical. Instead we
block a reasonable set of directly-executable/script extensions and
sniff a few dangerous magic bytes as defense-in-depth against a
renamed executable.
"""

import os
import re

# Extensions that can execute code directly (or via a common file
# association) on Windows/Linux/macOS. Not exhaustive — a deliberate
# block-list, not a security boundary against a determined attacker,
# but enough to stop the common "oops I uploaded a .exe" and casual
# malware-drop cases in an internal tool.
BLOCKED_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".exe", ".sh", ".bat", ".cmd", ".msi", ".js", ".mjs", ".jar",
        ".ps1", ".psm1", ".vbs", ".vbe", ".com", ".scr", ".dll", ".msp",
        ".hta", ".wsf", ".wsh", ".reg", ".lnk", ".app", ".apk", ".deb",
        ".rpm", ".cpl", ".gadget", ".pif", ".msc", ".job", ".workflow",
        ".dmg", ".bin", ".run", ".out", ".command", ".action",
    }
)

# Magic-byte prefixes that mark a file as a native executable / script
# regardless of the extension it was uploaded with (e.g. "invoice.pdf"
# that's actually a renamed Windows PE). Sniffed from the first bytes
# of the real body — the client-supplied filename/content-type is not
# trusted.
_DANGEROUS_MAGIC_PREFIXES: tuple[bytes, ...] = (
    b"MZ",  # Windows PE (.exe/.dll)
    b"\x7fELF",  # Linux ELF binary
    b"#!",  # POSIX shebang script
)

MAX_ATTACHMENT_SIZE_BYTES = 20 * 1024 * 1024  # 20MB cap


def sanitize_filename(filename: str) -> str:
    """Strips any path component and replaces anything but
    alnum/dot/dash/underscore — defuses path traversal
    (``../../etc/passwd``) and keeps the S3 object key predictable."""
    base = os.path.basename((filename or "").strip().replace("\\", "/"))
    base = re.sub(r"[^A-Za-z0-9._-]", "_", base)
    base = base.lstrip(".-") or "file"
    return base[:150]


def is_blocked_extension(filename: str) -> bool:
    ext = os.path.splitext((filename or "").lower())[1]
    return ext in BLOCKED_EXTENSIONS


def sniff_dangerous(data: bytes) -> bool:
    """True if the body itself looks like a native executable/script,
    independent of the (client-controlled) filename/content-type."""
    return data.startswith(_DANGEROUS_MAGIC_PREFIXES)
