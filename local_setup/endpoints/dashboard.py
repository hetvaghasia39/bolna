from typing import List
from pydantic import BaseModel, field_validator
from bolna.models import Transcriber
from fastapi import APIRouter, HTTPException, Request
from vo_utils.database_utils import db
from config import settings
from vo_utils.clerk_auth_utils import get_user_id_from_Token
from datetime import datetime, timedelta
import logging


logger = logging.getLogger(__name__)
router = APIRouter()

class WeekDayCallData(BaseModel):
    name: str
    inbound: int
    outbound: int

    @field_validator("name")
    def validate_name(cls, value):
        if value not in ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]:
            raise ValueError("Invalid week day name")
        return value

class CallDurationData(BaseModel):
    name: str
    average_duration: float

class DashBoardModel(BaseModel):
    total_calls: int
    average_call_duration: int
    total_agents: int
    week_data: List[WeekDayCallData]
    call_duration_data: List[CallDurationData]

    @field_validator("total_calls")
    def validate_total_calls(cls, value):
        if value < 0:
            raise ValueError("Total calls cannot be negative")
        return value
    
    @field_validator("average_call_duration")
    def validate_average_call_duration(cls, value):
        if value < 0:
            raise ValueError("Average call duration cannot be negative")
        return value
    
    @field_validator("total_agents")
    def validate_total_agents(cls, value):
        if value < 0:
            raise ValueError("Total agents cannot be negative")
        return value
    
    @field_validator("week_data")
    def validate_week_data(cls, value):
        if len(value) != 7:
            raise ValueError("Week data should have 7 entries")
        return value
    
    @field_validator("call_duration_data")
    def validate_call_duration_data(cls, value):
        if len(value) != 4:
            raise ValueError("Call duration data should have 4 entries")
        return value

@router.get("/dashboard2", response_model=DashBoardModel)
def get_dashboard_data(header: Request):
    start_time = datetime.now()
    
    # Initialize counts and data structures
    total_calls = 0
    total_agents = 0
    total_duration = 0
    week_data = {day: WeekDayCallData(name=day, inbound=0, outbound=0) for day in ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]}
    call_duration_data = {f"Week {i+1}": CallDurationData(name=f"Week {i+1}", average_duration=0) for i in range(4)}
    
    # Assume user_id is fetched correctly
    user_id = 2

    # Fetch all agents for the user
    agents = list(db[settings.MONGO_COLLECTION].find({"user_id": user_id}, {"agent_id": 1}))
    agent_ids = [agent["agent_id"] for agent in agents]
    total_agents = len(agent_ids)

    # Fetch execution data in one query
    now = datetime.now()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    monday = today - timedelta(days=today.weekday())
    four_weeks_ago = monday - timedelta(days=21)

    executions = list(db[settings.EXECUTION_COLLECTION].find({
        "agent_id": {"$in": agent_ids},
        "created_at": {"$gte": four_weeks_ago.isoformat()}
    }, {"agent_id": 1, "conversation_time": 1, "created_at": 1}).sort("created_at", 1))

    # Aggregate data
    call_counts = {agent_id: {"total_calls": 0, "total_duration": 0} for agent_id in agent_ids}

    for exec in executions:
        agent_id = exec["agent_id"]
        call_counts[agent_id]["total_calls"] += 1
        call_counts[agent_id]["total_duration"] += exec["conversation_time"]

        # Update week data
        created_at = datetime.fromisoformat(exec["created_at"])
        if monday <= created_at < monday + timedelta(days=7):
            day_name = created_at.strftime("%a")
            week_data[day_name].outbound += 1

        # Update call duration data
        week_index = (created_at - four_weeks_ago).days // 7
        
        if 0 <= week_index < 4:
            week = f"Week {week_index + 1}"
            call_duration_data[week].average_duration += exec["conversation_time"]

    # Compute total calls and average call duration
    for counts in call_counts.values():
        total_calls += counts["total_calls"]
        total_duration += counts["total_duration"]

    for week_index, week_data_obj in enumerate(call_duration_data.values()):
        if week_data_obj.average_duration > 0:
            num_calls = sum(1 for exec in executions if (datetime.fromisoformat(exec["created_at"]) - four_weeks_ago).days // 7 == week_index)
            week_data_obj.average_duration = week_data_obj.average_duration // num_calls if num_calls > 0 else 0

    average_call_duration = total_duration // total_calls if total_calls > 0 else 0

    # Create response model
    dbm = DashBoardModel(
        total_calls=total_calls,
        average_call_duration=average_call_duration,
        total_agents=total_agents,
        week_data=list(week_data.values()),
        call_duration_data=list(call_duration_data.values())
    )

    logger.info(f"Time taken to fetch dashboard data: {datetime.now() - start_time}")
    return dbm