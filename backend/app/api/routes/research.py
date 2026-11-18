"""Research endpoints (SRS §16.1): A4 literature analysis on demand; another user's workspace or
a paper outside the workspace answers 404 (D-047). Contradictions are stored, replacing the
workspace's previous ones; so are corpus gaps. Saved findings export as Markdown or BibTeX."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from app.agents.literature_analysis import (
    ComparisonTable,
    ContradictionReport,
    GapReport,
    LiteratureAnalysisAgent,
    ThemeSynthesis,
)
from app.api.deps import get_current_user, get_literature_analysis_agent, get_research_service
from app.core.auth import CurrentUser
from app.schemas.errors import ErrorResponse
from app.schemas.research import (
    CompareRequest,
    ContradictionsRequest,
    FindingCreate,
    FindingRead,
    GapsRequest,
    SynthesizeRequest,
)
from app.services.research import ResearchService

router = APIRouter(
    tags=["research"],
    responses={
        status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ErrorResponse},
    },
)


@router.post(
    "/workspaces/{workspace_id}/compare",
    response_model=ComparisonTable,
    operation_id="comparePapers",
)
async def compare_papers(
    workspace_id: UUID,
    body: CompareRequest,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    agent: Annotated[LiteratureAnalysisAgent, Depends(get_literature_analysis_agent)],
) -> ComparisonTable:
    """A comparison table of the given papers; every cell is cited or "Not reported" (FR-19)."""
    return await agent.compare(user.id, workspace_id, body.document_ids)


@router.post(
    "/workspaces/{workspace_id}/synthesize",
    response_model=ThemeSynthesis,
    operation_id="synthesizePapers",
)
async def synthesize_papers(
    workspace_id: UUID,
    body: SynthesizeRequest,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    agent: Annotated[LiteratureAnalysisAgent, Depends(get_literature_analysis_agent)],
) -> ThemeSynthesis:
    """Themes on a topic across the given papers; each claim cites every paper it names (FR-18)."""
    return await agent.synthesize(user.id, workspace_id, body.topic.strip(), body.document_ids)


@router.post(
    "/workspaces/{workspace_id}/contradictions",
    response_model=ContradictionReport,
    operation_id="findContradictions",
)
async def find_contradictions(
    workspace_id: UUID,
    body: ContradictionsRequest,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    agent: Annotated[LiteratureAnalysisAgent, Depends(get_literature_analysis_agent)],
    research: Annotated[ResearchService, Depends(get_research_service)],
) -> ContradictionReport:
    """Potential contradictions on a topic between the given papers, with both passages and the
    conditions that may explain them (FR-20)."""
    report = await agent.find_contradictions(
        user.id, workspace_id, body.topic.strip(), body.document_ids
    )
    await research.save_contradictions(user.id, workspace_id, report.records())
    return report


@router.post(
    "/workspaces/{workspace_id}/gaps",
    response_model=GapReport,
    operation_id="findGaps",
)
async def find_gaps(
    workspace_id: UUID,
    body: GapsRequest,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    agent: Annotated[LiteratureAnalysisAgent, Depends(get_literature_analysis_agent)],
    research: Annotated[ResearchService, Depends(get_research_service)],
) -> GapReport:
    """Potential research gaps across the given papers' limitations and future work, each citing
    every paper it names (FR-21, corpus scope)."""
    report = await agent.find_gaps(user.id, workspace_id, body.document_ids)
    await research.save_gaps(user.id, workspace_id, report.records())
    return report


@router.get(
    "/workspaces/{workspace_id}/findings",
    response_model=list[FindingRead],
    operation_id="listFindings",
)
async def list_findings(
    workspace_id: UUID,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    research: Annotated[ResearchService, Depends(get_research_service)],
) -> list[FindingRead]:
    """The workspace's saved findings, oldest first (FR-26)."""
    return await research.list_findings(user.id, workspace_id)


@router.post(
    "/workspaces/{workspace_id}/findings",
    response_model=FindingRead,
    status_code=status.HTTP_201_CREATED,
    operation_id="saveFinding",
)
async def save_finding(
    workspace_id: UUID,
    body: FindingCreate,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    research: Annotated[ResearchService, Depends(get_research_service)],
) -> FindingRead:
    """Save an answer, comparison, contradiction, gap, or review (FR-26)."""
    return await research.save_finding(user.id, workspace_id, body)


_EXPORTS = {
    "md": ("text/markdown", "findings.md"),
    "bibtex": ("application/x-bibtex", "findings.bib"),
}


@router.get(
    "/workspaces/{workspace_id}/findings/export",
    response_class=Response,
    responses={
        status.HTTP_200_OK: {"content": {media: {} for media, _ in _EXPORTS.values()}},
    },
    operation_id="exportFindings",
)
async def export_findings(
    workspace_id: UUID,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    research: Annotated[ResearchService, Depends(get_research_service)],
    format: Annotated[Literal["md", "bibtex"], Query()] = "md",
) -> Response:
    """Saved findings as a Markdown file, or the papers they cite as a BibTeX file (FR-32)."""
    if format == "md":
        text = await research.export_markdown(user.id, workspace_id)
    else:
        text = await research.export_bibtex(user.id, workspace_id)
    media_type, filename = _EXPORTS[format]
    return Response(
        text,
        media_type=f"{media_type}; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
