# scv-contracts

The single source of truth for the message shapes that cross a process boundary
in Smart Café Vision — currently the AI worker → backend event bus.

It is a real installable package rather than a copied file so that a change to
an event shape breaks both sides at install time instead of silently at 2am in
a café.

```bash
pip install -e ./shared     # from the repository root
```

Both `backend/requirements/base.txt` and `ai_worker/requirements.txt` install it,
and both Docker images copy `shared/` before installing dependencies.
