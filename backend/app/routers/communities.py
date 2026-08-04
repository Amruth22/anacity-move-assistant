from fastapi import APIRouter, HTTPException

from ..store import store

router = APIRouter(prefix="/api/communities", tags=["communities"])


@router.get("")
def list_communities():
    """Everything the role switcher and docs page need in one call."""
    out = []
    for c in store.communities.values():
        out.append({
            "id": c["id"],
            "name": c["name"],
            "city": c["city"],
            "profile": c["profile"],
            "policies": c["policies"],
        })
    return out


@router.get("/{community_id}/residents")
def residents(community_id: str):
    if store.community(community_id) is None:
        raise HTTPException(404, "Unknown community")
    out = []
    for r in store.residents_in(community_id):
        unit = store.unit(r["unit_id"])
        out.append({**r, "unit_label": unit["label"] if unit else r["unit_id"]})
    return out
