"""S7 centroid maths and profile maintenance with an in-memory store (FR-22, SRS §11.2)."""

import math
from uuid import UUID, uuid4

import pytest

from app.core.errors import CompatibilityWarningError, NotFoundError
from app.repositories.topic_profiles import ProfileState
from app.services.topic_profile import (
    CompatibilityOptions,
    TopicProfileService,
    add_to_centroid,
    cosine,
    is_compatible,
    mean_vector,
    normalize,
    remove_from_centroid,
    similarity,
)
from tests.unit.profile_fakes import InMemoryProfileStore, LinkResult

ALICE = uuid4()
BOB = uuid4()
OPTIONS = CompatibilityOptions(first_chunks=2, max_pages=3, threshold=0.5)
X = [1.0, 0.0, 0.0]
Y = [0.0, 1.0, 0.0]
Z = [0.0, 0.0, 1.0]


def close(a: list[float] | None, b: list[float]) -> bool:
    assert a is not None
    return all(math.isclose(x, y, abs_tol=1e-9) for x, y in zip(a, b, strict=True))


# --- maths ---


def test_normalize_and_mean() -> None:
    assert normalize([3.0, 4.0]) == [0.6, 0.8]
    assert normalize([0.0, 0.0]) == [0.0, 0.0]
    assert mean_vector([[1.0, 2.0], [3.0, 4.0]]) == [2.0, 3.0]


def test_cosine() -> None:
    assert cosine(X, X) == pytest.approx(1.0)
    assert cosine(X, Y) == pytest.approx(0.0)
    assert cosine([1.0, 1.0], [2.0, 2.0]) == pytest.approx(1.0)
    assert cosine([0.0, 0.0], [1.0, 0.0]) == 0.0


def test_first_document_becomes_the_centroid() -> None:
    state = add_to_centroid(ProfileState(centroid=None, document_count=0), X)

    assert state == ProfileState(centroid=X, document_count=1)


def test_incremental_mean_matches_the_batch_mean() -> None:
    state = ProfileState(centroid=None, document_count=0)
    for vector in (X, Y, Z):
        state = add_to_centroid(state, vector)

    assert state.document_count == 3
    assert close(state.centroid, mean_vector([X, Y, Z]))


def test_remove_undoes_add() -> None:
    state = add_to_centroid(add_to_centroid(ProfileState(None, 0), X), Y)

    state = remove_from_centroid(state, Y)

    assert state.document_count == 1
    assert close(state.centroid, X)


def test_removing_the_last_document_empties_the_profile() -> None:
    state = remove_from_centroid(ProfileState(centroid=X, document_count=1), X)

    assert state == ProfileState(centroid=None, document_count=0)


def test_empty_profile_has_no_score_and_is_compatible() -> None:
    score = similarity(ProfileState(None, 0), X)

    assert score is None
    assert is_compatible(score, 0.5)
    assert is_compatible(0.5, 0.5)
    assert not is_compatible(0.49, 0.5)


# --- service ---


def setup(
    *documents: tuple[UUID, list[list[float]]], owner: UUID = ALICE
) -> tuple[InMemoryProfileStore, TopicProfileService, UUID]:
    store = InMemoryProfileStore()
    workspace = uuid4()
    store.workspaces[workspace] = owner
    for document_id, vectors in documents:
        store.chunks[document_id] = (owner, vectors)
    return store, TopicProfileService(store, OPTIONS), workspace


async def test_include_uses_only_the_first_chunks() -> None:
    document = uuid4()
    store, profiles, workspace = setup((document, [X, X, Y]))

    score = await profiles.include(ALICE, workspace, document, override=False)

    assert score is None  # empty workspace: no check
    assert store.profiles[workspace] == ProfileState(centroid=X, document_count=1)


async def test_include_scores_against_the_centroid_before_adding() -> None:
    first, second = uuid4(), uuid4()
    store, profiles, workspace = setup((first, [X]), (second, [[1.0, 1.0, 0.0]]))
    await profiles.include(ALICE, workspace, first, override=False)

    score = await profiles.include(ALICE, workspace, second, override=False)

    assert score == pytest.approx(1 / math.sqrt(2))
    assert store.profiles[workspace].document_count == 2


async def test_unrelated_document_is_refused_without_changing_the_profile() -> None:
    first, unrelated = uuid4(), uuid4()
    store, profiles, workspace = setup((first, [X]), (unrelated, [Y]))
    await profiles.include(ALICE, workspace, first, override=False)

    with pytest.raises(CompatibilityWarningError) as caught:
        await profiles.include(ALICE, workspace, unrelated, override=False)

    assert caught.value.details == {"score": pytest.approx(0.0), "threshold": 0.5}
    assert store.profiles[workspace] == ProfileState(centroid=X, document_count=1)


async def test_override_adds_an_unrelated_document() -> None:
    first, unrelated = uuid4(), uuid4()
    store, profiles, workspace = setup((first, [X]), (unrelated, [Y]))
    await profiles.include(ALICE, workspace, first, override=False)

    score = await profiles.include(ALICE, workspace, unrelated, override=True)

    assert score == pytest.approx(0.0)
    assert store.profiles[workspace].document_count == 2


async def test_document_without_chunks_is_not_included() -> None:
    store, profiles, workspace = setup()

    assert await profiles.include(ALICE, workspace, uuid4(), override=False) is None
    assert workspace not in store.profiles


async def test_exclude_takes_the_document_out() -> None:
    first, second = uuid4(), uuid4()
    store, profiles, workspace = setup((first, [X]), (second, [Y]))
    await profiles.include(ALICE, workspace, first, override=True)
    await profiles.include(ALICE, workspace, second, override=True)

    await profiles.exclude(ALICE, workspace, second)

    assert store.profiles[workspace].document_count == 1
    assert close(store.profiles[workspace].centroid, X)


async def test_document_ready_scores_and_adds_in_every_linked_workspace() -> None:
    existing, new = uuid4(), uuid4()
    store, profiles, first = setup((existing, [X]), (new, [Y]))
    second = uuid4()
    store.workspaces[second] = ALICE
    await profiles.include(ALICE, first, existing, override=True)
    store.links[(first, new)] = LinkResult()
    store.links[(second, new)] = LinkResult(override=True)

    await profiles.document_ready(ALICE, new)

    # An unrelated document is never refused here: the user was warned before upload.
    assert store.links[(first, new)].score == pytest.approx(0.0)
    assert store.links[(first, new)].override is False
    assert store.links[(second, new)] == LinkResult(score=None, override=True)
    assert store.profiles[first].document_count == 2
    assert store.profiles[second] == ProfileState(centroid=Y, document_count=1)


async def test_other_users_workspace_is_not_found() -> None:
    document = uuid4()
    store, profiles, workspace = setup((document, [X]), owner=BOB)
    store.chunks[document] = (ALICE, [X])

    with pytest.raises(NotFoundError):
        await profiles.include(ALICE, workspace, document, override=True)
    assert workspace not in store.profiles


async def test_other_users_document_has_no_vector() -> None:
    document = uuid4()
    store, profiles, workspace = setup()
    store.chunks[document] = (BOB, [X])

    assert await profiles.include(ALICE, workspace, document, override=False) is None
    assert workspace not in store.profiles
