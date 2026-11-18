"""Version 1 API router."""

from fastapi import APIRouter

from app.api.routes import (
    conversations,
    documents,
    health,
    knowledge_graph,
    papers,
    research,
    retrieval,
    workspaces,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(workspaces.router)
api_router.include_router(documents.router)
api_router.include_router(retrieval.router)
api_router.include_router(conversations.router)
api_router.include_router(research.router)
api_router.include_router(papers.router)
api_router.include_router(knowledge_graph.router)
