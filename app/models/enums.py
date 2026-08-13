import enum


class RoleEnum(str, enum.Enum):
    admin = "admin"
    rep = "rep"


class DealStage(str, enum.Enum):
    new = "new"
    qualified = "qualified"
    proposal = "proposal"
    negotiation = "negotiation"
    won = "won"
    lost = "lost"


class Priority(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"


class ActivityType(str, enum.Enum):
    note = "note"
    call = "call"
    email = "email"
    meeting = "meeting"
    agent_generated = "agent_generated"
