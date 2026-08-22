from fastapi import APIRouter, Depends

from ..auth import get_current_admin
from ..xray_manager import enable_bbr, get_network_status

router = APIRouter(prefix="/api/system", tags=["system"], dependencies=[Depends(get_current_admin)])


@router.get("/network")
def network_status():
    return get_network_status()


@router.post("/network/enable-bbr")
def network_enable_bbr():
    return enable_bbr()
