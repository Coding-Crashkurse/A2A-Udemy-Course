# 03_tasks_basics (REST / HTTP+JSON)

## Start server
```bash
python 03_Tasks_Basics/server_rest.py
```

Server läuft standardmäßig auf Port 8002.

## Run client (polling, no streaming)
```bash
python 03_Tasks_Basics/client.py --port 8002 --text "Wie sind die Öffnungszeiten vom Bella Vista?"
```

Weitere Beispiele:

- "Wie lautet die Adresse vom Bella Vista?"
- "Kann ich einen Tisch reservieren?"
- "Wie ist die Telefonnummer?"

---

### Kurz: reicht dein Client?
**Ja, von der Idee her** (Card holen → ClientFactory → send_message iterieren).  
Für **REST-only + Tasks Basics** würde ich ihn aber genau so anpassen wie oben:

- `supported_transports=[TransportProtocol.http_json]`
- `streaming=False`
- `polling=True`
- kein `grpc` Import

Wenn du als Nächstes in Sektion 04 Richtung **Multi-Turn / input-required** gehen willst, kann man diesen Executor sehr gut erweitern: bei unklarer Frage zuerst `input_required` emitten, und bei der nächsten Message im selben `task_id` weiterarbeiten.
