"""SQLAlchemy models. Import every model module here so `Base.metadata` is complete."""

from app.models.agent_run import AgentRun
from app.models.base import Base
from app.models.chunk import Chunk
from app.models.conversation import Approval, Citation, Claim, Conversation, Evidence, Message
from app.models.document import Document
from app.models.eval_run import EvalResult, EvalRun
from app.models.knowledge_graph import (
    KGDocumentExtraction,
    KGEdge,
    KGEdgeMention,
    KGEntityMention,
    KGGraph,
    KGJob,
    KGNode,
    KGNodeMention,
    KGRelationMention,
)
from app.models.research import Contradiction, ResearchGap, SavedFinding
from app.models.topic_profile import TopicProfile
from app.models.workspace import Workspace, WorkspaceDocument

__all__ = [
    "AgentRun",
    "Approval",
    "Base",
    "Chunk",
    "Citation",
    "Claim",
    "Contradiction",
    "Conversation",
    "Document",
    "EvalResult",
    "EvalRun",
    "Evidence",
    "KGDocumentExtraction",
    "KGEdge",
    "KGEdgeMention",
    "KGEntityMention",
    "KGGraph",
    "KGJob",
    "KGNode",
    "KGNodeMention",
    "KGRelationMention",
    "Message",
    "ResearchGap",
    "SavedFinding",
    "TopicProfile",
    "Workspace",
    "WorkspaceDocument",
]
