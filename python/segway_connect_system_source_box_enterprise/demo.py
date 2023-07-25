import orjson
import json
import time
import asyncio

import os

from boxsdk import Client, JWTAuth
from boxsdk.exception import BoxException
from boxsdk.object.events import EnterpriseEventsStreamType
import requests
import backoff

class EventStream():
    cancelled: bool = False
    _MAX_CHUNK_SIZE: int = 500
    _MAX_RETRY_COUNT: int = 3
    _EVENTS_TYPE: str= "admin_events"
    _DATE_FMT_STRING: str='%Y-%m-%dT%H:%M:%S-00:00'

    def __init__(self):
        self._client = None
        self._next_stream_position = None
        print("init")
        self.auth()

    def auth(self):
        f = open('box.json')
        self.auth_dict = json.load(f)
        f.close()
        try:
            result=JWTAuth.from_settings_dictionary(self.auth_dict)
        except (TypeError, ValueError, KeyError):
            logger.error('Could not load JWT from settings dictionary')
            return False
        self._client = Client(result)

    
    def run(self):
        """Simple Run method to create the loop"""
        asyncio.run(self.receive_batch())

    async def receive_batch(self):
        params = {
            'limit': self._MAX_CHUNK_SIZE,
            'stream_type': EnterpriseEventsStreamType.ADMIN_LOGS,
            'stream_position': 0
        }
        timeout=5
        while not self.cancelled:
            # self.cancelled = True
            # try:
            print("polling")
            box_response = self._get_events(params)
            
            if not box_response:
                print("sleep")
                time.sleep(timeout)
            else:
                events = box_response
                print(events)
                            
                for event in events["entries"]:
                    print(event)
                    # print(f'Got {event.event_type} event')
                if events['next_stream_position'] and int(events['next_stream_position'])>0:
                    params['stream_position']=events['next_stream_position']
                if int(events['chunk_size']) == 0:
                    print("chunk sleep")
                    time.sleep(timeout)

    def backoff_hdlr(details):
        print ("Backing off {wait:0.1f} seconds after {tries} tries "
            "calling function {target} with args {args} and kwargs "
            "{kwargs}".format(**details))
                                        
    @backoff.on_exception(backoff.expo,
                        (requests.exceptions.Timeout,
                        requests.exceptions.ConnectionError),max_time=300,on_backoff=backoff_hdlr)
    @backoff.on_predicate(backoff.expo, lambda x: x['entries'] == [],max_time=300,on_backoff=backoff_hdlr)
    def _get_events(self,params):
        box_response = self._client.make_request(
            'GET',
            self._client.get_url('events'),
            params=params,
            timeout=30
        )
        result = box_response.json()
        print(result)
        return result

if __name__ == '__main__':
    o = EventStream()
    o.run()