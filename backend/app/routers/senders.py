from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError

from app import audit
from app.deps import TenantContext, get_current_user_with_tenant, require_owner
from app.models.models import Sender
from app.schemas import SenderCreate, SenderOut

router = APIRouter(prefix="/senders", tags=["senders"])


@router.get("", response_model=list[SenderOut])
def list_senders(ctx: TenantContext = Depends(get_current_user_with_tenant)):
    return (
        ctx.db.query(Sender)
        .filter(Sender.tenant_id == ctx.user.tenant_id, Sender.is_active.is_(True))
        .order_by(Sender.name)
        .all()
    )


@router.post("", response_model=SenderOut, status_code=status.HTTP_201_CREATED)
def create_sender(body: SenderCreate, ctx: TenantContext = Depends(require_owner)):
    sender = Sender(
        tenant_id=ctx.user.tenant_id,
        name=body.name,
        odcanit_prefix=body.odcanit_prefix,
    )
    ctx.db.add(sender)
    try:
        ctx.db.flush()
    except IntegrityError:
        # uq_senders_tenant_name — a duplicate name is a client mistake, not a
        # server fault.
        ctx.db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A sender with this name already exists",
        ) from None
    audit.record(ctx.db, ctx.user, "sender.created", details={"name": sender.name})
    ctx.db.commit()
    ctx.db.refresh(sender)
    return sender
