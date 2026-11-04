from fastapi import APIRouter

from app.api.v1.agents import router as agents_router
from app.api.v1.auth import router as auth_router
from app.api.v1.conversations import router as conversations_router
from app.api.v1.dashboard import router as dashboard_router
from app.api.v1.evals import router as evals_router
from app.api.v1.health import router as health_router
from app.api.v1.knowledge import router as knowledge_router
from app.api.v1.logs import router as logs_router
from app.api.v1.orders import router as orders_router
from app.api.v1.public import router as public_router
from app.api.v1.tickets import router as tickets_router
from app.api.v1.workspaces import router as workspaces_router

api_router = APIRouter()
api_router.include_router(agents_router)
api_router.include_router(auth_router)
api_router.include_router(conversations_router)
api_router.include_router(dashboard_router)
api_router.include_router(evals_router)
api_router.include_router(health_router)
api_router.include_router(knowledge_router)
api_router.include_router(logs_router)
api_router.include_router(orders_router)
api_router.include_router(public_router)
api_router.include_router(tickets_router)
api_router.include_router(workspaces_router)
