import requests
from tools.base import BaseTool
from config import TAVILY_API_KEY

class WebSearchTool(BaseTool):
    """Search the web for LLM-optimized results using Tavily."""

    @property
    def name(self) -> str:
        return "web_search"

    @property
    def description(self) -> str:
        return "Search the internet for real-time information, documentation, or bug reports. Returns a list of relevant snippets and URLs."

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query"
                },
                "search_depth": {
                    "type": "string",
                    "enum": ["basic", "advanced"],
                    "description": "Search depth: 'basic' for speed, 'advanced' for thoroughness",
                    "default": "basic"
                }
            },
            "required": ["query"]
        }

    def run(self, query: str, search_depth: str = "basic") -> str:
        if not TAVILY_API_KEY:
            return "Error: TAVILY_API_KEY not configured in environment."

        url = "https://api.tavily.com/search"
        payload = {
            "api_key": TAVILY_API_KEY,
            "query": query,
            "search_depth": search_depth,
            "include_answer": True
        }

        try:
            response = requests.post(url, json=payload)
            response.raise_for_status()
            data = response.json()

            results = data.get("results", [])
            if not results:
                return "No results found for the query."

            output = []
            if data.get("answer"):
                output.append(f"Summary: {data['answer']}\n")

            for i, res in enumerate(results, 1):
                output.append(f"[{i}] {res['title']}\nURL: {res['url']}\nSnippet: {res['content']}\n")

            return "\n".join(output)
        except Exception as e:
            return f"Web search failed: {e}"


class WebReadTool(BaseTool):
    """Extract clean content from a specific URL using Tavily."""

    @property
    def name(self) -> str:
        return "web_read"

    @property
    def description(self) -> str:
        return "Read the full content of a webpage. Use this when a search snippet is not enough to understand the documentation or code."

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL of the page to read"
                }
            },
            "required": ["url"]
        }

    def run(self, url: str) -> str:
        if not TAVILY_API_KEY:
            return "Error: TAVILY_API_KEY not configured in environment."

        api_url = "https://api.tavily.com/extract"
        payload = {
            "api_key": TAVILY_API_KEY,
            "urls": [url]
        }

        try:
            response = requests.post(api_url, json=payload)
            response.raise_for_status()
            data = response.json()

            results = data.get("results", [])
            if not results:
                return "Failed to extract content from the provided URL."

            # Tavily extract returns a list of results per URL
            content = results[0].get("raw_content") or results[0].get("content", "No content found.")
            return content
        except Exception as e:
            return f"Web read failed: {e}"
