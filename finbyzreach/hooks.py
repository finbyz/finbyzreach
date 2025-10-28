app_name = "finbyzreach"
app_title = "Finbyzreach"
app_publisher = "Finbyz Tech Pvt Ltd"
app_description = "AI-Powered Follow-ups and Smart Email Outreach"
app_email = "info@finbyz.tech"
app_license = "MIT"
required_apps = ["finbyz/finbyzai"]
# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/finbyzreach/css/finbyzreach.css"
# app_include_js = "/assets/finbyzreach/js/finbyzreach.js"

# include js, css files in header of web template
# web_include_css = "/assets/finbyzreach/css/finbyzreach.css"
# web_include_js = "/assets/finbyzreach/js/finbyzreach.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "finbyzreach/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "finbyzreach.utils.jinja_methods",
# 	"filters": "finbyzreach.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "finbyzreach.install.before_install"
# after_install = "finbyzreach.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "finbyzreach.uninstall.before_uninstall"
# after_uninstall = "finbyzreach.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "finbyzreach.utils.before_app_install"
# after_app_install = "finbyzreach.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "finbyzreach.utils.before_app_uninstall"
# after_app_uninstall = "finbyzreach.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "finbyzreach.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# DocType Class
# ---------------
# Override standard doctype classes

# override_doctype_class = {
# 	"ToDo": "custom_app.overrides.CustomToDo"
# }

# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
# 	}
# }

# Scheduled Tasks
# ---------------

scheduler_events = {
	# "all": [
	# 	"finbyzreach.tasks.all"
	# ],
	# "daily": [
	# 	"finbyzreach.tasks.daily",
	# ],
	# "hourly": [
	# 	"finbyzreach.tasks.hourly"
	# ],
	# "weekly": [
	# 	"finbyzreach.tasks.weekly"
	# ],
	# "monthly": [
	# 	"finbyzreach.tasks.monthly"
	# ],
	"cron": {
		"*/10 * * * *": [
			"finbyzreach.tasks.every_10_min.enqueue_outbound_emails.enqueue_outbound_emails"
		]
	}
}

# Testing
# -------

# before_tests = "finbyzreach.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "finbyzreach.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "finbyzreach.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["finbyzreach.utils.before_request"]
# after_request = ["finbyzreach.utils.after_request"]

# Job Events
# ----------
# before_job = ["finbyzreach.utils.before_job"]
# after_job = ["finbyzreach.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"finbyzreach.auth.validate"
# ]
