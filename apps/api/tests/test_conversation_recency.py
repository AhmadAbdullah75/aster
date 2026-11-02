from datetime import timedelta

from conftest import register
from nexus.config import settings
from nexus.db import transaction
from nexus.models import Conversation, now


def test_existing_conversation_moves_to_top_after_message(client, monkeypatch):
    monkeypatch.setattr(settings, 'openai_api_key', 'synthetic-test-key')
    register(client)
    first = client.post('/conversations', json={'title': 'First'}).json()
    client.post('/conversations', json={'title': 'Second'})
    with transaction() as db:
        db.get(Conversation, first['id']).updated_at = now() - timedelta(days=1)
    response = client.post(f"/conversations/{first['id']}/runs", json={'message': 'Continue here'})
    assert response.status_code == 202, response.text
    listing = client.get('/conversations').json()
    assert listing[0]['id'] == first['id']
