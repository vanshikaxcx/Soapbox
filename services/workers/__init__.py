"""Durable worker entry points (WP-07).

Each module here is transport: it reads whatever the event source delivered,
calls one use case, and renders the reply that source expects. A worker that
contained a rule would put that rule outside the layer the tests describe.
"""
