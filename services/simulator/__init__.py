"""The independent payment provider simulator (WP-09).

A stand-in for a third party, built like one. It has its own table, its own
ledger and its own rules, and nothing outside it may write to that ledger. The
checkout task talks to it the way it would talk to a real provider: by key, over
a transport, with no shared memory and no assumption that a reply will arrive.

Nothing here moves money. There is no card number, no UPI handle, no bank. What
it simulates is the one thing that actually matters: a provider that sometimes
accepts a payment and then fails to tell you.
"""
