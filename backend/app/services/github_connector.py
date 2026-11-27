"""Conector GitHub de solo lectura con escáner de secretos y cero retención para entrenamiento (V3 §15)."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

SECRET_PATTERNS: List[tuple[str, re.Pattern[str]]] = [
    ("github_token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("generic_api_key", re.compile(r"(?i)(?:api_key|secret_key|password|token)\s*[:=]\s*['\"][A-Za-z0-9_\-]{12,}['\"]")),
    ("private_key_block", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
]


class GitHubReadOnlyConnector:
    """Inspecciona metadatos y documentación de un repositorio en modo solo lectura."""

    @staticmethod
    def scan_secrets(text: str) -> List[Dict[str, str]]:
        hits: List[Dict[str, str]] = []
        for kind, pat in SECRET_PATTERNS:
            for _ in pat.finditer(text or ""):
                hits.append({"type": kind})
        return hits

    @classmethod
    def redact_secrets(cls, text: str) -> str:
        out = text or ""
        for kind, pat in SECRET_PATTERNS:
            out = pat.sub(f"[SECRETO_REDACTADO_{kind.upper()}]", out)
        return out

    @classmethod
    def analyze_repository_snapshot(
        cls,
        repo_url: str,
        readme_text: str = "",
        file_tree: Optional[List[str]] = None,
        package_files: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Extrae capacidades de producto sin almacenar código fuente completo ni entrenar modelos."""
        files = list(file_tree or [])
        combined = "\n".join([readme_text or ""] + list((package_files or {}).values()))
        secrets_found = cls.scan_secrets(combined)
        safe_readme = cls.redact_secrets(readme_text or "")

        stack: List[str] = []
        joined_files = " ".join(files).lower() + " " + safe_readme.lower()
        for tech in ("python", "flask", "fastapi", "vue", "react", "typescript", "postgres", "sqlite", "docker"):
            if tech in joined_files:
                stack.append(tech)

        return {
            "repo_url": repo_url,
            "mode": "read_only",
            "training_opt_out": True,
            "secrets_detected_count": len(secrets_found),
            "secrets_redacted": len(secrets_found) > 0,
            "detected_stack": stack,
            "files_count": len(files),
            "product_summary": safe_readme[:800],
        }
