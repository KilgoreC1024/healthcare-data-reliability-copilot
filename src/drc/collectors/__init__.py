"""Collectors: turn a platform's native operational metadata into a standard `IncidentBundle`.

Collectors are strictly read-only. They open databases in read-only mode, never write into the
platform's data directory, and never call the pipeline itself.
"""
