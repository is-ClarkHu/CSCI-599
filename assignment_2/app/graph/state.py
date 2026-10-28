import operator
from typing import Annotated, TypedDict

from app.types import Category, Citation, WorkerName, WorkerResult


class GraphState(TypedDict, total=False):
    query: str
    category: Category
    plan: list[WorkerName]          # produced by the supervisor; dispatch may insert research
    plan_reason: str
    cursor: int                     # index of the next plan step to run
    results: Annotated[list[WorkerResult], operator.add]   # appended by each worker
    next_node: str                  # "research" | "data" | "summary" | "finalize"
    transition_reason: str
    final_answer: str
    final_citations: list[Citation]
