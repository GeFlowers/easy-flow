"""定义跨续跑目标及其评估结果的线程状态结构。"""

from __future__ import annotations

from typing import Any, Literal, NotRequired, TypedDict

GoalBlocker = Literal[
    "none",
    "missing_evidence",
    "needs_user_input",
    "run_failed",
    "external_wait",
    "goal_not_met_yet",
]


class GoalEvaluation(TypedDict):
    """记录一次目标完成度评估的结论、阻塞原因与证据摘要。"""

    satisfied: bool
    blocker: GoalBlocker
    reason: str
    evidence_summary: NotRequired[str]


class GoalState(TypedDict):
    """保存活动目标的续跑计数、进度阈值和最近评估结果。"""

    objective: str
    status: Literal["active"]
    created_at: str
    updated_at: str
    continuation_count: int
    max_continuations: int
    no_progress_count: int
    max_no_progress_continuations: int
    last_evaluation: NotRequired[dict[str, Any]]
