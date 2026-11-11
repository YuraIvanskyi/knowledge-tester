"""Validation report: plain, path-based messages that can be pasted back to an LLM."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Issue:
    path: str
    message: str


@dataclass
class ValidationReport:
    errors: list[Issue] = field(default_factory=list)
    warnings: list[Issue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def error(self, path: str, message: str) -> None:
        issue = Issue(path, message)
        if issue not in self.errors:
            self.errors.append(issue)

    def warn(self, path: str, message: str) -> None:
        issue = Issue(path, message)
        if issue not in self.warnings:
            self.warnings.append(issue)

    def as_text(self) -> str:
        """Text for people and LLMs, one line per problem."""
        if not self.errors and not self.warnings:
            return "No problems found."
        lines: list[str] = []
        if self.errors:
            lines.append(
                f"The test file has {len(self.errors)} error(s) and cannot be imported. "
                "Fix every ERROR below and send back the complete corrected JSON file."
            )
        else:
            lines.append("The test file can be imported. Warnings are optional to fix.")
        lines.append("")
        lines.extend(f"ERROR  {i.path}: {i.message}" for i in self.errors)
        lines.extend(f"WARN   {i.path}: {i.message}" for i in self.warnings)
        return "\n".join(lines)
