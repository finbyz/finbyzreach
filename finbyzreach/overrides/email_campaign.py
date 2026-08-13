import frappe
from erpnext.crm.doctype.campaign.campaign import Campaign as ERPNextCampaign
from erpnext.crm.doctype.email_campaign.email_campaign import (
	EmailCampaign as ERPNextEmailCampaign,
)
from frappe import _
from frappe.utils import getdate, now_datetime

from finbyzreach import email_marketing


class Campaign(ERPNextCampaign):
	"""ERPNext Campaign with Email Campaign Studio validation."""

	def validate(self):
		if email_marketing._is_email_broadcast(self):
			email_marketing.validate_campaign(self)
		parent_validate = getattr(super(), "validate", None)
		if parent_validate:
			return parent_validate()


class EmailCampaign(ERPNextEmailCampaign):
	"""ERPNext Email Campaign with Studio recipient-log behavior."""

	def before_insert(self):
		# Standard Email Campaigns keep ERPNext's native behavior. Studio rows may
		# only be created by the frozen-audience scheduler.
		if not self.campaign_name or not email_marketing._is_email_broadcast(self.campaign_name):
			parent_before_insert = getattr(super(), "before_insert", None)
			if parent_before_insert:
				return parent_before_insert()
			return None
		if not frappe.flags.get(email_marketing.SCHEDULER_RECIPIENT_INSERT_FLAG):
			frappe.throw(
				_(
					"Direct Email Campaign creation is disabled. "
					"Create and schedule campaigns from Email Campaign Studio."
				),
				frappe.PermissionError,
			)

	def validate(self):
		if not self.campaign_name or not email_marketing._is_email_broadcast(self.campaign_name):
			return super().validate()
		if not self.is_new():
			frappe.throw(
				_(
					"Email Campaign recipient records are read-only delivery logs. "
					"Manage the campaign from Email Campaign Studio."
				),
				frappe.PermissionError,
			)
		self.email_campaign_for = "Lead"
		if not self.campaign_name or not self.recipient:
			frappe.throw(_("Campaign and Lead are required for a broadcast recipient"))
		delivery_status = self.custom_delivery_status or "Planned"
		scheduled_at = self.custom_scheduled_at or now_datetime()
		self.start_date = getdate(scheduled_at)
		self.end_date = self.start_date
		self.status = (
			"Completed"
			if delivery_status in email_marketing.TERMINAL_DELIVERY_STATUSES
			else "Scheduled"
		)
		if delivery_status not in ("Skipped", "Cancelled"):
			email = self.custom_recipient_email or frappe.db.get_value(
				"Lead", self.recipient, "email_id"
			)
			if not email_marketing._normalized_email(email):
				frappe.throw(_("Lead {0} has no valid email address").format(self.recipient))

	def update_status(self):
		if not self.campaign_name or not email_marketing._is_email_broadcast(self.campaign_name):
			return super().update_status()
		delivery_status = self.custom_delivery_status or "Planned"
		expected = (
			"Completed"
			if delivery_status in email_marketing.TERMINAL_DELIVERY_STATUSES
			else "Scheduled"
		)
		if self.status != expected:
			self.db_set("status", expected, update_modified=False)
