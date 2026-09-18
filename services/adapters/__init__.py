"""Concrete adapters for the ports the application layer declares (WP-07).

This is the only package allowed to import a cloud SDK. Everything above it
talks to ``services.application.ports``, which is what lets the whole P3 lane
run against ``MemoryStore`` with no AWS account at all.
"""
