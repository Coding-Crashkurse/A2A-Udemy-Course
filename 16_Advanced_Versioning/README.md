# Advanced Versioning - Runbook

This folder contains the versioning demo for lesson 16. Use the commands below
to start the servers and run the client checks.

## Server

Start the servers in separate terminals:

```bash
python server.py --mode legacy --port 8001 --agent-version 0.1.0-demo
python server.py --mode v1 --port 8002 --agent-version 0.2.0-demo
```

## Client

### Agent version checks

Expected: **BLOCKED** because agent `0.1.0` < `0.2.0`.

```bash
python client.py --target legacy --protocol-version 0.3 --min-agent-version 0.2.0
```

Expected: **OK** because agent `0.2.0` >= `0.2.0`.

```bash
python client.py --target v1 --protocol-version 1.0 --min-agent-version 0.2.0
```

### Protocol version mismatch (should fail)

```bash
python client.py --target v1 --protocol-version 0.3 --min-agent-version 0.2.0
python client.py --target legacy --protocol-version 1.0 --min-agent-version 0.2.0
```
