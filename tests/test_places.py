from unittest.mock import Mock, patch

import pytest
import requests
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.config import Settings
from backend.main import create_app
from backend.places import lookup


def test_predictions_and_session():
    response = Mock()
    response.json.return_value = {'suggestions': [{'placePrediction': {'placeId': 'abc', 'text': {'text': '123 Main St'}}}]}
    with patch('backend.places.requests.post', return_value=response) as post:
        assert lookup('private', 'session', query='123 Main')['suggestions'][0]['id'] == 'abc'
        assert post.call_args.kwargs['json']['sessionToken'] == 'session'
        assert post.call_args.kwargs['headers']['X-Goog-Api-Key'] == 'private'


def test_details_include_zip_and_unit():
    response = Mock()
    response.json.return_value = {'addressComponents': [
        {'types': [kind], 'shortText': value} for kind, value in {
            'street_number': '123', 'route': 'Main St', 'locality': 'Philadelphia',
            'administrative_area_level_1': 'PA', 'postal_code': '19103', 'subpremise': '2',
        }.items()
    ]}
    with patch('backend.places.requests.get', return_value=response):
        assert lookup('private', 'session', place_id='abc')['address'] == '123 Main St Unit 2, Philadelphia, PA 19103'
    response.json.return_value = {}
    with patch('backend.places.requests.get', return_value=response), pytest.raises(HTTPException) as exc:
        lookup('private', 'session', place_id='abc')
    assert exc.value.status_code == 422


def test_errors_do_not_expose_key():
    with patch('backend.places.requests.post', side_effect=requests.Timeout('private')), pytest.raises(HTTPException) as exc:
        lookup('private', 'session', query='123 Main')
    assert exc.value.status_code == 503
    assert 'private' not in exc.value.detail


def test_api_validation_limits_and_missing_key(tmp_path):
    settings = Settings(database_url='', database_path=str(tmp_path/'places.sqlite3'), google_places_key='private')
    with TestClient(create_app(settings=settings, providers=[])) as client, patch('backend.main.lookup', return_value={'suggestions': []}) as call:
        assert client.get('/api/address-suggestions', params={'q': 'abc', 'token': 'x'*16}).status_code == 422
        assert client.get('/api/address-details', params={'place_id': '../secret', 'token': 'x'*16}).status_code == 422
        for _ in range(120):
            assert client.get('/api/address-suggestions', params={'q': '123 Main', 'token': 'x'*16}).status_code == 200
        assert client.get('/api/address-suggestions', params={'q': '123 Main', 'token': 'x'*16}).status_code == 429
        assert call.call_count == 120
        settings.google_places_key = ''
        assert client.get('/api/address-suggestions', params={'q': '123 Main', 'token': 'x'*16}).status_code == 503
