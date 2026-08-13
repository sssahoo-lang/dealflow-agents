import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.routes import agents, auth, crm
from app.events.bus import event_bus
from app.events.handlers import register_agent_handlers
from app.services.errors import NotFound

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    register_agent_handlers(event_bus)
    yield


app = FastAPI(title="DealFlow Agents", version="0.1.0", lifespan=lifespan)


@app.exception_handler(NotFound)
async def not_found_handler(request: Request, exc: NotFound):
    return JSONResponse(status_code=404, content={"detail": str(exc)})


app.include_router(auth.router)
app.include_router(crm.companies)
app.include_router(crm.contacts)
app.include_router(crm.deals)
app.include_router(crm.activities)
app.include_router(agents.router)


@app.get("/health", tags=["ops"])
def health():
    return {"status": "ok"}
