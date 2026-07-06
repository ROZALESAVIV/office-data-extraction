from fastapi import APIRouter, Depends, HTTPException, status

from app.deps import get_current_user_with_tenant
from app.schemas import SenderCreate, SenderOut
from models.models import Sender

router = APIRouter(prefix="/senders", tags=["senders"])


@router.get("", response_model=list[SenderOut])
def list_senders(ctx=Depends(get_current_user_with_tenant)):
    db, user = ctx
    return (
        db.query(Sender)
        .filter(Sender.is_active.is_(True))
        .order_by(Sender.name)
        .all()
    )


@router.post("", response_model=SenderOut, status_code=status.HTTP_201_CREATED)
def create_sender(body: SenderCreate, ctx=Depends(get_current_user_with_tenant)):
    db, user = ctx
    if user.role != "owner":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
    sender = Sender(
        tenant_id=user.tenant_id,
        name=body.name,
        odcanit_prefix=body.odcanit_prefix,
    )
    db.add(sender)
    db.commit()
    db.refresh(sender)
    return sender
