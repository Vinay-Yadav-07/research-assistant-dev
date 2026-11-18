"""Knowledge graph endpoints (FR-33, SRS §9.1, §16.1).

Another user's workspace or job answers 404 (D-047).
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.deps import get_current_user, get_knowledge_graph_runner
from app.core.auth import CurrentUser
from app.schemas.conversations import CitationRead
from app.schemas.errors import ErrorResponse
from app.schemas.knowledge_graph import KGJobRead, KnowledgeGraphRead
from app.services.knowledge_graph_jobs import KnowledgeGraphRunner

router = APIRouter(
    tags=["knowledge-graph"],
    responses={
        status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ErrorResponse},
    },
)

User = Annotated[CurrentUser, Depends(get_current_user)]
Runner = Annotated[KnowledgeGraphRunner, Depends(get_knowledge_graph_runner)]
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0)]


@router.post(
    "/workspaces/{workspace_id}/knowledge-graph/jobs",
    response_model=KGJobRead,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="startKnowledgeGraphJob",
    responses={
        status.HTTP_200_OK: {
            "model": KGJobRead,
            "description": "The workspace already has an active job; that job is returned.",
        },
        status.HTTP_409_CONFLICT: {"model": ErrorResponse},
        status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ErrorResponse},
    },
)
async def start_job(
    workspace_id: UUID, response: Response, user: User, runner: Runner
) -> KGJobRead:
    """Generate the graph, or update it from the workspace's current papers.

    202 starts a job; 200 returns the job already running. 409 `no_ready_documents` when the
    workspace has no ready papers.
    """
    job, created = await runner.start(user.id, workspace_id)
    if not created:
        response.status_code = status.HTTP_200_OK
    return job


@router.get(
    "/workspaces/{workspace_id}/knowledge-graph/jobs/{job_id}",
    response_model=KGJobRead,
    operation_id="getKnowledgeGraphJob",
)
async def get_job(workspace_id: UUID, job_id: UUID, user: User, runner: Runner) -> KGJobRead:
    """A job's status and progress (papers read so far, then the build)."""
    return await runner.get_job(user.id, workspace_id, job_id)


@router.get(
    "/workspaces/{workspace_id}/knowledge-graph",
    response_model=KnowledgeGraphRead,
    operation_id="getKnowledgeGraph",
)
async def get_graph(workspace_id: UUID, user: User, runner: Runner) -> KnowledgeGraphRead:
    """The workspace graph's state, whether its papers changed, its active or last job, and its
    most-supported nodes and the edges between them."""
    return await runner.graph_status(user.id, workspace_id)


@router.get(
    "/workspaces/{workspace_id}/knowledge-graph/nodes/{node_id}/evidence",
    response_model=list[CitationRead],
    operation_id="getKnowledgeGraphNodeEvidence",
)
async def node_evidence(
    workspace_id: UUID,
    node_id: UUID,
    user: User,
    runner: Runner,
    limit: Limit = 20,
    offset: Offset = 0,
) -> list[CitationRead]:
    """Passages of the workspace's current papers that name the entity."""
    return await runner.node_evidence(user.id, workspace_id, node_id, limit=limit, offset=offset)


@router.get(
    "/workspaces/{workspace_id}/knowledge-graph/edges/{edge_id}/evidence",
    response_model=list[CitationRead],
    operation_id="getKnowledgeGraphEdgeEvidence",
)
async def edge_evidence(
    workspace_id: UUID,
    edge_id: UUID,
    user: User,
    runner: Runner,
    limit: Limit = 20,
    offset: Offset = 0,
) -> list[CitationRead]:
    """Passages of the workspace's current papers whose quote states the relationship."""
    return await runner.edge_evidence(user.id, workspace_id, edge_id, limit=limit, offset=offset)
