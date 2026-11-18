"""An SMS button must stay an sms: link in the sent email, not become a link on this site."""
from unittest import TestCase

import frappe.email.email_body as email_body
import frappe.utils as frappe_utils
import frappe.utils.data as frappe_data

from finbyzreach.utils import relative_urls  # noqa: F401  (installs the wrapper)


class RelativeUrlsTest(TestCase):
	def test_chat_and_phone_schemes_stay_as_written_everywhere_frappe_uses_the_function(self):
		html = '<a href="sms:+41791234567?body=Hi">sms</a><a href=\'whatsapp://send?phone=41791234567\'>wa</a><a href="SMS:+41791234567">upper</a>'
		for expand in (frappe_data.expand_relative_urls, frappe_utils.expand_relative_urls, email_body.expand_relative_urls, frappe_data.scrub_urls):
			out = expand(html)
			self.assertIn('href="sms:+41791234567?body=Hi"', out)
			self.assertIn("href='whatsapp://send?phone=41791234567'", out)
			self.assertIn('href="SMS:+41791234567"', out)
			self.assertNotIn("http-kept", out)

	def test_other_links_are_expanded_exactly_as_before(self):
		out = frappe_data.expand_relative_urls('<a href="/files/a.pdf">file</a><a href="mailto:a@b.ch">m</a><a href="tel:+4144">t</a><a href="https://x.ch">w</a><img src="/files/i.png">')
		site = frappe_data.get_url().rstrip("/")
		self.assertIn(f'href="{site}/files/a.pdf"', out)
		self.assertIn('href="mailto:a@b.ch"', out)
		self.assertIn('href="tel:+4144"', out)
		self.assertIn('href="https://x.ch"', out)
		self.assertIn(f'src="{site}/files/i.png"', out)

	def test_installing_twice_does_not_wrap_twice(self):
		before = frappe_data.expand_relative_urls
		relative_urls.install()
		self.assertIs(frappe_data.expand_relative_urls, before)
