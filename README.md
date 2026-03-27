![Screenshot](screenshot.png)
# MeshMonitor Chat Feed

A web-based real-time chat feed (think Twitter/X) for Meshtastic nodes running [MeshMonitor](https://github.com/Yeraze/meshmonitor).

## Features
- Modern dark theme with heavy glassmorphism design and animated ambient lighting.
- Real-time, perfectly smooth updates via HTMX and idiomoph DOM morphing.
- Threaded message grouping (Twitter-style quotes) automatically resolving `replyId` parents.
- Mobile-responsive layout.
- Visual `MQTT` badge indicators for bridged messages.
- Signal metrics (SNR, RSSI, Hops) visualized beautifully across messages.

## Setup
1.  **Environment Variables**:
    Create a `.env` file or set the following in your environment:
    - `MESH_MONITOR_API_BASE_URL`: The URL of your MeshMonitor API.
    - `MESH_MONITOR_API_TOKEN`: Your API Bearer token (starts with `mm_v1_`).
    - `POLL_INTERVAL_SECONDS`: How often to refresh the feed (default: 10).
    - `MESSAGE_LIMIT`: Number of initial messages to load (default: 50).
    - `PAGE_TITLE`: Custom title mapping for the header UI (default: "MeshMonitor").
    - `PAGE_SUBTITLE`: Custom subtitle string, can be left blank to hide (default: "Real-time Chat Feed").

2.  **Local Run**:
    ```bash
    python -m venv venv
    .\venv\Scripts\Activate.ps1 # Windows
    # source venv/bin/activate # Linux/Mac
    pip install -r requirements.txt
    python main.py
    ```

3.  **Docker**:
    ```bash
    docker build -t mesh-chat-feed .
    docker run -p 8000:8000 --env-file .env mesh-chat-feed
    ```
