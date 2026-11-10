"""MCP server: lets an AI agent work the slide QC queue.

Tools can read QC results, explain a slide, draft a rescan request, and report
metrics. There is no tool to approve or send a request: a named person does that
with `python -m slideguard.cli approve`.

    pip install -r requirements-mcp.txt
    python mcp_server.py
"""

from contextlib import closing

from mcp.server.fastmcp import FastMCP

from slideguard import service, store
from slideguard.cli import DB_PATH

mcp = FastMCP("slideguard")


@mcp.tool()
def failed_slides(reason: str | None = None, limit: int = 20) -> dict:
    """List slides held back by QC, with the reason for each.

    Args:
        reason: optional filter: blur, low_tissue, pen_mark, faded, overstained.
        limit: max slides to return (1-50).
    """
    with closing(store.connect(DB_PATH)) as conn:
        return service.failed_slides(conn, reason, limit)


@mcp.tool()
def get_slide(slide_id: str) -> dict:
    """Get one slide's QC metrics, the thresholds they were judged against, and any rescan requests."""
    with closing(store.connect(DB_PATH)) as conn:
        return service.slide_detail(conn, slide_id)


@mcp.tool()
def draft_rescan_request(slide_id: str) -> dict:
    """Draft a rescan request for a failed slide. Saved as pending_approval; NOT sent."""
    with closing(store.connect(DB_PATH)) as conn:
        return service.draft_rescan(conn, slide_id, actor="mcp-agent")


@mcp.tool()
def qc_metrics() -> dict:
    """QC KPIs: slides checked, fail rate, failures by reason, pending requests,
    approval rate, and how often people edit the drafted requests."""
    with closing(store.connect(DB_PATH)) as conn:
        return service.metrics(conn)


if __name__ == "__main__":
    mcp.run()
