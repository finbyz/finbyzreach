from __future__ import annotations

import frappe
from frappe import _


def get_data(data=None):
	return {

		"fieldname": "campaign_name",
		"non_standard_fieldnames": {},
		"transactions": [
			{
				"label": _("Email Broadcast"),
				"items": ["Email Campaign"],
			},
		],
	}

