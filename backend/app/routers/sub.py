from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import PlainTextResponse, HTMLResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..link_builder import build_subscription_content, build_subscription_page_html
from ..models import ProxyLink

# NOTE: intentionally no auth dependency here -- v2rayNG/NekoRay/etc fetch
# this URL directly from the client app on a timer, they can't attach a
# bearer token. The sub_id itself (a short random token, same idea as
# client_id) is the secret; anyone who has it can already see the individual
# configs via connect_url, so this exposes nothing extra.
router = APIRouter(prefix="/sub", tags=["subscription"])


@router.get("/{sub_id}")
def get_subscription(sub_id: str, request: Request, db: Session = Depends(get_db)):
    links = (
        db.query(ProxyLink)
        .filter(ProxyLink.sub_id == sub_id, ProxyLink.is_active.is_(True))
        .all()
    )
    if not links:
        raise HTTPException(404, "Subscription not found or empty")

    # Proxy clients (v2rayNG, NekoRay, sing-box, ...) never send a browser
    # user-agent, and always want the raw base64 body -- only render the
    # pretty info page for an actual browser tab, or if explicitly asked via
    # ?view=html (handy for embedding/sharing a preview link).
    ua = request.headers.get("user-agent", "")
    wants_html = "mozilla" in ua.lower() or request.query_params.get("view") == "html"

    if wants_html:
        return HTMLResponse(build_subscription_page_html(links, sub_id))

    content = build_subscription_content(links)
    return PlainTextResponse(
        content,
        headers={
            "Profile-Title": "HAMI",
            "Profile-Update-Interval": "12",
        },
    )
