"""Preserve existing segment folders while enabling the native folder tree."""
from finbyzreach.finbyzreach.doctype.reach_segment_folder.reach_segment_folder import setup_segment_folders


def execute():
    setup_segment_folders()
