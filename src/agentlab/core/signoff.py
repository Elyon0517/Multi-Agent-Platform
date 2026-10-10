from __future__ import annotations

from agentlab.core.schemas import SignoffReport


def report_text(report: SignoffReport) -> str:
    criteria = "\n".join(f"- {criterion}" for criterion in report.acceptance_criteria) or "无"
    checks = "FULL Gate 通过。" if report.automated_checks == "passed" else "未经过自动测试。"
    findings = "\n".join(
        f"- [{finding.severity}] {finding.file}{':' + str(finding.line) if finding.line is not None else ''} "
        f"· {finding.reviewer_id}: {finding.issue}"
        for finding in report.findings
    ) or "无"
    return (f"任务目标与验收标准\n目标: {report.goal}\n验收标准:\n{criteria}\n\n"
            f"自动检查\n{checks}\n\n未解决的 findings\n{findings}")
