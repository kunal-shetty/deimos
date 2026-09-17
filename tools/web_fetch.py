import requests
from bs4 import BeautifulSoup
from tools.base import BaseTool

class FetchUrlTool(BaseTool):
    """
    Fetches content from a URL and converts it to clean markdown-like text.
    Useful for reading documentation, GitHub issues, and web pages.
    """

    @property
    def name(self) -> str:
        return "fetch_url"

    @property
    def description(self) -> str:
        return "Fetches the content of a URL and returns a clean text summary of the page."

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "The URL to fetch."}
            },
            "required": ["url"]
        }

    def run(self, url: str) -> str:
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, "html.parser")

            # Remove noise
            for element in soup(["script", "style", "nav", "footer", "header", "aside"]):
                element.decompose()

            # Try to find main content
            main_content = soup.find("main") or soup.find("article") or soup.find("body")

            if not main_content:
                return "Error: Could not find main content on the page."

            # Extract text and clean up whitespace
            text = main_content.get_text(separator="\n")
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            clean_text = "\n".join(lines)

            return f"Content from {url}:\n\n{clean_text[:10000]}" # Cap output size
        except requests.exceptions.RequestException as e:
            return f"Error fetching URL: {e}"
        except Exception as e:
            return f"Unexpected error while fetching URL: {e}"
