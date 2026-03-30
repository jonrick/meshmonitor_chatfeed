import os
import httpx
from datetime import datetime
from typing import List, Optional, Union, Any
import asyncio
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

# Environment variables with defaults
API_BASE_URL = os.getenv("MESH_MONITOR_API_BASE_URL", "").rstrip("/")
API_TOKEN = os.getenv("MESH_MONITOR_API_TOKEN", "")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL_SECONDS", "10"))
LIMIT = int(os.getenv("MESSAGE_LIMIT", "50"))
PAGE_TITLE = os.getenv("PAGE_TITLE", "MeshMonitor")
PAGE_SUBTITLE = os.getenv("PAGE_SUBTITLE", "Real-time Chat Feed")

app = FastAPI(title="MeshMonitor Chat Feed")
templates = Jinja2Templates(directory="templates")

PARENT_MESSAGE_CACHE = {}
PARENT_FETCH_SEMAPHORE = asyncio.Semaphore(2)  # Reduced to avoid overwhelming single-threaded APIs

# Models for the API response
class Node(BaseModel):
    nodeId: str
    longName: Optional[str] = None
    shortName: Optional[str] = None

class NodeApiResponse(BaseModel):
    success: bool
    count: int
    data: List[Node]

class Message(BaseModel):
    id: str
    fromNodeId: str
    fromLongName: Optional[str] = None  # New field for resolved name
    toNodeId: str
    textAddress: Optional[str] = None
    text: str = ""
    timestamp: Union[str, int]
    rxSnr: Optional[float] = 0.0
    hopStart: Optional[int] = 0
    rxRssi: Optional[float] = 0.0
    rxTime: Optional[int] = 0
    viaMqtt: Optional[bool] = False
    deliveryState: Optional[str] = "unknown"
    replyId: Optional[Union[int, str]] = None
    parent_msg: Optional[Any] = None

class ApiResponse(BaseModel):
    success: bool
    count: int
    data: List[Message]

async def fetch_nodes() -> dict:
    url = f"{API_BASE_URL}/api/v1/nodes"
    headers = {"Authorization": f"Bearer {API_TOKEN}"} if API_TOKEN else {}
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, headers=headers, timeout=10.0)
            response.raise_for_status()
            data = response.json()
            node_data = NodeApiResponse(**data)
            return {node.nodeId: node.longName for node in node_data.data if node.longName}
        except Exception as e:
            print(f"ERROR: Could not fetch nodes: {e}")
            return {}

async def fetch_messages() -> List[Message]:
    # Fetch nodes first to resolve names
    node_map = await fetch_nodes()
    
    url = f"{API_BASE_URL}/api/v1/messages?limit={LIMIT}"
    headers = {"Authorization": f"Bearer {API_TOKEN}"} if API_TOKEN else {}
    
    async with httpx.AsyncClient() as client:
        try:
            print(f"DEBUG: Fetching from {url}...")
            response = await client.get(url, headers=headers, timeout=10.0)
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict) or "data" not in data:
                print(f"ERROR: Invalid API response format: {data}")
                return []
            api_response = ApiResponse(**data)
            
            # Resolve names
            for msg in api_response.data:
                msg.fromLongName = node_map.get(msg.fromNodeId, msg.fromNodeId)
                
            def normalize_id(nid) -> str:
                ns = str(nid)
                if ns.startswith("msg_"):
                    return ns[4:]
                return ns

            # Resolve threads (parent messages)
            msg_by_id = {}
            for m in api_response.data:
                full_id = normalize_id(m.id)
                msg_by_id[full_id] = m
                if "_" in full_id:
                    short_id = full_id.split("_")[-1]
                    msg_by_id[short_id] = m
            
            async def resolve_parent(msg: Message):
                if not msg.replyId:
                    return
                str_reply_id = normalize_id(msg.replyId)
                
                # 1. Check current batch
                if str_reply_id in msg_by_id:
                    msg.parent_msg = msg_by_id[str_reply_id]
                    return
                    
                # 2. Check global cache
                if str_reply_id in PARENT_MESSAGE_CACHE:
                    msg.parent_msg = PARENT_MESSAGE_CACHE[str_reply_id]
                    return
                
                # 3. Fetch from API with concurrency limit
                async with PARENT_FETCH_SEMAPHORE:
                    try:
                        print(f"DEBUG: Fetching missing parent {str_reply_id} from network...")
                        parent_url = f"{API_BASE_URL}/api/v1/messages/{str_reply_id}"
                        # Super strict timeout of 2.0s per request to prevent hanging
                        p_response = await client.get(parent_url, headers=headers, timeout=2.0)
                        if p_response.status_code == 200:
                            p_data = p_response.json()
                            
                            p_msg_dict = None
                            if isinstance(p_data, dict):
                                if "data" in p_data:
                                    if isinstance(p_data["data"], list) and len(p_data["data"]) > 0:
                                        p_msg_dict = p_data["data"][0]
                                    elif isinstance(p_data["data"], dict):
                                        p_msg_dict = p_data["data"]
                                else:
                                    p_msg_dict = p_data
                            elif isinstance(p_data, list) and len(p_data) > 0:
                                p_msg_dict = p_data[0]
                                
                            if p_msg_dict and isinstance(p_msg_dict, dict):
                                parent = Message(**p_msg_dict)
                                parent.fromLongName = node_map.get(parent.fromNodeId, parent.fromNodeId)
                                msg.parent_msg = parent
                                PARENT_MESSAGE_CACHE[str_reply_id] = parent
                                print(f"DEBUG: Successfully resolved parent {str_reply_id} from network")
                            else:
                                print(f"DEBUG: Received 200 but could not parse message dict for parent {str_reply_id}. Data: {p_data}")
                        elif p_response.status_code == 404:
                            # Cache explicitly as None so we don't spam 404s
                            PARENT_MESSAGE_CACHE[str_reply_id] = None
                        else:
                            print(f"DEBUG: Unexpected status {p_response.status_code} for parent {str_reply_id}")
                    except asyncio.CancelledError:
                        raise  # Always re-raise CancelledError
                    except Exception as e:
                        print(f"DEBUG: Could not fetch parent {str_reply_id} for thread: {type(e).__name__} - {e}")

            try:
                # Give the entire parent fetching process a maximum of 4 seconds to complete
                await asyncio.wait_for(
                    asyncio.gather(*(resolve_parent(msg) for msg in api_response.data)),
                    timeout=4.0
                )
            except asyncio.TimeoutError:
                print("WARNING: Timed out globally waiting for parent messages to resolve. Returning partial threads.")
            except asyncio.CancelledError:
                print("WARNING: Request was cancelled by the client (browser disconnect/refresh).")
                raise
                
            return api_response.data
        except httpx.HTTPStatusError as e:
            print(f"ERROR: API returned status {e.response.status_code} for {url}")
            return []
        except httpx.ConnectError as e:
            print(f"ERROR: Connection error to {API_BASE_URL}. Verify the URL and DNS connectivity. Error: {e}")
            return []
        except Exception as e:
            print(f"ERROR: Unexpected error fetching messages: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            return []

def format_timestamp(ts: Union[str, int]) -> str:
    if not ts:
        return ""
    try:
        # Handle Unix timestamp (int) - assume milliseconds
        if isinstance(ts, int):
            # Check if it looks like seconds or milliseconds
            if ts > 10**12: # Milliseconds
                dt = datetime.fromtimestamp(ts / 1000.0)
            else: # Seconds
                dt = datetime.fromtimestamp(ts)
            return dt.strftime("%b %d, %H:%M:%S")
            
        # Handle ISO string
        clean_ts = ts
        if clean_ts.endswith("Z"):
            clean_ts = clean_ts.replace("Z", "+00:00")
        dt = datetime.fromisoformat(clean_ts)
        return dt.strftime("%b %d, %H:%M:%S")
    except Exception as e:
        print(f"WARNING: Could not parse timestamp '{ts}': {e}")
        return str(ts)

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    messages = await fetch_messages()
    return templates.TemplateResponse(
        request=request, 
        name="index.html", 
        context={
            "messages": messages,
            "poll_interval": POLL_INTERVAL,
            "format_timestamp": format_timestamp,
            "page_title": PAGE_TITLE,
            "page_subtitle": PAGE_SUBTITLE
        }
    )

@app.get("/feed", response_class=HTMLResponse)
async def chat_feed_fragment(request: Request):
    messages = await fetch_messages()
    return templates.TemplateResponse(
        request=request, 
        name="fragments/message_list.html", 
        context={
            "messages": messages,
            "format_timestamp": format_timestamp
        }
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
