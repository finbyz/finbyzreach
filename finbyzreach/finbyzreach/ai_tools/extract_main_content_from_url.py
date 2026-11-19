# LangChain tool: extract_main_content_from_url
# Module: Finbyzreach
# Copied from AI-CRM so the Company Research agent can read a lead's website.

from langchain_core.tools import tool
import requests
from bs4 import BeautifulSoup


@tool("extract_main_content_from_url", return_direct=False)
def extract_main_content_from_url_tool(url: str) -> str:
	"""
	Extracts all text inside the <main> tag from the given website URL.

	Args:
		url (str): The URL of the website.

	Returns:
		str: Text content inside the <main> tag (or the body if there is none),
		or an error message if the page could not be fetched.
	"""
	from frappe.utils import validate_url

	if not url or not validate_url(url, valid_schemes=["http", "https"]):
		return "Error: a valid http or https URL is required."

	try:
		response = requests.get(url, timeout=10)
		response.raise_for_status()
	except requests.RequestException as e:
		return f"Error fetching URL: {e}"

	soup = BeautifulSoup(response.text, "html.parser")
	node = soup.find("main") or soup.find("body")
	if not node:
		return "Error: the page has no readable content."
	return node.get_text(separator="\n", strip=True)[:20000]
